"""Private PDF storage: upload PDFs one by one or as zip archives, list them,
download them (one at a time, or all as one zip) and delete them (one at a time, or all at once). Only developers and file uploaders can use these
routes (require_file_access). A file uploader sees only their own files; a
developer sees everyone's, with the uploader's email. Files live in the
developer_files table.

Files can be sorted into folders (developer_file_folders, migration 046). The
folder list is shared by everyone with file access; developers add and remove
folders. The list, "download all" and "delete all" take a folder: a folder id,
"none" for files in no folder, or nothing for every file.
"""
from __future__ import annotations

import hashlib
import io
import posixpath
import uuid
import zipfile
from collections.abc import Iterable, Iterator
from datetime import date, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.auth import Access, require_developer, require_file_access
from app.database.session import engine

router = APIRouter(prefix="/api/v1/files", tags=["files"])

MAX_PDF_BYTES = 50 * 1024 * 1024
MAX_UPLOAD_BYTES = 200 * 1024 * 1024
# What one request may unpack from its zips: guards against zip bombs.
MAX_UNPACKED_BYTES = 500 * 1024 * 1024
MAX_ZIP_ENTRIES = 2000


class StoredFile(BaseModel):
    id: str
    filename: str
    source_zip: str | None
    size_bytes: int
    uploaded_at: datetime
    uploaded_by: str | None = None
    folder_id: str | None = None


class Folder(BaseModel):
    id: str
    name: str
    file_count: int


class NewFolder(BaseModel):
    name: str


class MoveFile(BaseModel):
    folder_id: str | None


class Skipped(BaseModel):
    filename: str
    reason: str


class UploadResult(BaseModel):
    saved: list[StoredFile]
    skipped: list[Skipped]


def is_pdf(content: bytes) -> bool:
    # The header may follow a few bytes of junk; readers accept it within the first 1 KB.
    return b"%PDF-" in content[:1024]


def clean_name(name: str) -> str:
    """The file's own name, without folders from the zip or the browser."""
    base = posixpath.basename(name.replace("\\", "/")).strip()
    return base[:255] or "file.pdf"


def pdfs_in_zip(content: bytes, zip_name: str) -> tuple[list[tuple[str, bytes]], list[Skipped]]:
    """The PDFs in a zip archive (nested folders included) and the entries left out."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        return [], [Skipped(filename=zip_name, reason="not a valid zip file")]
    entries = [info for info in archive.infolist() if not info.is_dir()]
    if len(entries) > MAX_ZIP_ENTRIES:
        return [], [Skipped(filename=zip_name, reason=f"more than {MAX_ZIP_ENTRIES} files")]
    pdfs, skipped, unpacked = [], [], 0
    for info in entries:
        name = clean_name(info.filename)
        # macOS adds __MACOSX/._name resource forks to zips made in Finder.
        if info.filename.startswith("__MACOSX/") or name.startswith("._") or name == ".DS_Store":
            continue
        if not name.lower().endswith(".pdf"):
            skipped.append(Skipped(filename=name, reason="not a PDF"))
            continue
        if info.file_size > MAX_PDF_BYTES:
            skipped.append(Skipped(filename=name, reason="larger than 50 MB"))
            continue
        if unpacked + info.file_size > MAX_UNPACKED_BYTES:
            skipped.append(Skipped(filename=name, reason="zip unpacks to more than 500 MB; upload the rest separately"))
            continue
        try:
            with archive.open(info) as handle:
                data = handle.read(MAX_PDF_BYTES + 1)
        except (zipfile.BadZipFile, RuntimeError, NotImplementedError):
            # RuntimeError: encrypted entry; NotImplementedError: unsupported compression.
            skipped.append(Skipped(filename=name, reason="could not be unpacked (encrypted or damaged)"))
            continue
        if len(data) > MAX_PDF_BYTES:
            skipped.append(Skipped(filename=name, reason="larger than 50 MB"))
            continue
        unpacked += len(data)
        pdfs.append((name, data))
    return pdfs, skipped


def _row(row) -> StoredFile:
    folder_id = row.get("folder_id")
    return StoredFile(id=str(row["id"]), filename=row["filename"], source_zip=row["source_zip"],
                      size_bytes=row["size_bytes"], uploaded_at=row["uploaded_at"], uploaded_by=row.get("uploaded_by"),
                      folder_id=str(folder_id) if folder_id else None)


# Whose files a user may see: a developer every file, anyone else their own.
OWNED = "(:developer OR f.user_id = CAST(:user_id AS uuid))"


def _scope(access: Access) -> dict:
    return {"user_id": access.user_id, "developer": access.is_developer}


def folder_filter(folder: str | None) -> tuple[str, dict]:
    """SQL to add to a WHERE on developer_files f for a folder query parameter."""
    if not folder:
        return "", {}
    if folder == "none":
        return " AND f.folder_id IS NULL", {}
    return " AND f.folder_id = CAST(:folder_id AS uuid)", {"folder_id": _folder_uuid(folder)}


def _folder_uuid(folder_id: str) -> str:
    try:
        return str(uuid.UUID(folder_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Folder not found.") from None


def _require_folder(connection, folder_id: str | None) -> str | None:
    if not folder_id:
        return None
    folder_id = _folder_uuid(folder_id)
    if not connection.execute(text("SELECT 1 FROM developer_file_folders WHERE id = CAST(:id AS uuid)"),
                              {"id": folder_id}).first():
        raise HTTPException(status_code=404, detail="Folder not found.")
    return folder_id


@router.get("/folders", response_model=list[Folder])
def list_folders(access: Access = Depends(require_file_access)) -> list[Folder]:
    """Every folder, with how many of the user's visible files are in it."""
    with engine.connect() as connection:
        rows = connection.execute(text(f"""SELECT d.id, d.name, COUNT(f.id) FILTER (WHERE {OWNED}) AS file_count
            FROM developer_file_folders d LEFT JOIN developer_files f ON f.folder_id = d.id
            GROUP BY d.id, d.name ORDER BY lower(d.name)"""), _scope(access)).mappings().all()
    return [Folder(id=str(row["id"]), name=row["name"], file_count=row["file_count"]) for row in rows]


@router.post("/folders", response_model=Folder, status_code=201)
def create_folder(body: NewFolder, access: Access = Depends(require_developer)) -> Folder:
    name = " ".join(body.name.split())[:100]
    if not name:
        raise HTTPException(status_code=400, detail="Give the folder a name.")
    with engine.begin() as connection:
        if connection.execute(text("SELECT 1 FROM developer_file_folders WHERE lower(name) = lower(:name)"),
                              {"name": name}).first():
            raise HTTPException(status_code=409, detail=f"There is already a folder called {name}.")
        row = connection.execute(text("INSERT INTO developer_file_folders (name) VALUES (:name) RETURNING id, name"),
                                 {"name": name}).mappings().one()
    return Folder(id=str(row["id"]), name=row["name"], file_count=0)


@router.delete("/folders/{folder_id}", status_code=204)
def delete_folder(folder_id: str, access: Access = Depends(require_developer)) -> Response:
    """Only an empty folder (no one's files in it) can be removed."""
    with engine.begin() as connection:
        folder_id = _require_folder(connection, folder_id)
        if connection.execute(text("SELECT 1 FROM developer_files WHERE folder_id = CAST(:id AS uuid) LIMIT 1"),
                              {"id": folder_id}).first():
            raise HTTPException(status_code=409, detail="Move or delete the files in this folder first.")
        connection.execute(text("DELETE FROM developer_file_folders WHERE id = CAST(:id AS uuid)"), {"id": folder_id})
    return Response(status_code=204)


@router.get("", response_model=list[StoredFile])
def list_files(folder: str | None = Query(None), access: Access = Depends(require_file_access)) -> list[StoredFile]:
    where, params = folder_filter(folder)
    with engine.connect() as connection:
        rows = connection.execute(text(f"""SELECT f.id, f.filename, f.source_zip, f.size_bytes, f.uploaded_at,
                f.folder_id, u.email AS uploaded_by
            FROM developer_files f LEFT JOIN user_accounts u ON u.user_id = f.user_id
            WHERE {OWNED}{where} ORDER BY f.uploaded_at DESC, f.filename"""),
            {**_scope(access), **params}).mappings().all()
    return [_row(row) for row in rows]


@router.post("", response_model=UploadResult)
async def upload_files(files: list[UploadFile] = File(...), folder_id: str | None = Form(None),
                       access: Access = Depends(require_file_access)) -> UploadResult:
    candidates: list[tuple[str, bytes, str | None]] = []
    skipped: list[Skipped] = []
    total = 0
    for upload in files:
        name = clean_name(upload.filename or "")
        content = await upload.read(MAX_UPLOAD_BYTES + 1)
        total += len(content)
        if total > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Uploads are limited to 200 MB at a time.")
        if name.lower().endswith(".zip"):
            pdfs, left_out = pdfs_in_zip(content, name)
            candidates += [(pdf_name, data, name) for pdf_name, data in pdfs]
            skipped += left_out
        elif name.lower().endswith(".pdf"):
            if len(content) > MAX_PDF_BYTES:
                skipped.append(Skipped(filename=name, reason="larger than 50 MB"))
            else:
                candidates.append((name, content, None))
        else:
            skipped.append(Skipped(filename=name, reason="only PDF and zip files can be uploaded"))
    saved: list[StoredFile] = []
    with engine.begin() as connection:
        folder_id = _require_folder(connection, folder_id)
        for name, content, source_zip in candidates:
            if not is_pdf(content):
                skipped.append(Skipped(filename=name, reason="not a valid PDF"))
                continue
            row = connection.execute(text("""INSERT INTO developer_files
                (user_id, filename, source_zip, size_bytes, sha256, content, folder_id)
                VALUES (:user_id, :filename, :source_zip, :size, :sha256, :content, CAST(:folder_id AS uuid))
                ON CONFLICT (user_id, sha256) DO NOTHING
                RETURNING id, filename, source_zip, size_bytes, uploaded_at, folder_id"""), {
                    "user_id": access.user_id, "filename": name, "source_zip": source_zip, "folder_id": folder_id,
                    "size": len(content), "sha256": hashlib.sha256(content).hexdigest(), "content": content,
                }).mappings().first()
            if row:
                saved.append(_row(row))
            else:
                skipped.append(Skipped(filename=name, reason="already uploaded"))
    return UploadResult(saved=saved, skipped=skipped)


class _Chunks(io.RawIOBase):
    """A write-only stream that hands what was written to zip_stream in chunks."""

    def __init__(self) -> None:
        self.parts: list[bytes] = []

    def writable(self) -> bool:
        return True

    def write(self, data) -> int:
        self.parts.append(bytes(data))
        return len(data)

    def take(self) -> bytes:
        data, self.parts = b"".join(self.parts), []
        return data


def unique_name(name: str, used: set[str]) -> str:
    """'notice.pdf', then 'notice (2).pdf', ...: two files with one name both go in the zip."""
    stem, dot, suffix = name.rpartition(".") if "." in name else (name, "", "")
    candidate, number = name, 1
    while candidate.lower() in used:
        number += 1
        candidate = f"{stem} ({number}){dot}{suffix}"
    used.add(candidate.lower())
    return candidate


def zip_stream(files: Iterable[tuple[str, bytes]]) -> Iterator[bytes]:
    """A zip of the files, produced as it is written, so the whole archive is never in memory.
    PDFs are already compressed, so they are stored as they are."""
    sink, used = _Chunks(), set()
    with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for name, content in files:
            archive.writestr(unique_name(name, used), content)
            yield sink.take()
    yield sink.take()


class DeleteAllResult(BaseModel):
    deleted: int


@router.delete("", response_model=DeleteAllResult)
def delete_all_files(folder: str | None = Query(None),
                     access: Access = Depends(require_file_access)) -> DeleteAllResult:
    """Every file the user can see (in the folder, when one is given): a file uploader's own files, or, for a
    developer, everyone's."""
    where, params = folder_filter(folder)
    with engine.begin() as connection:
        deleted = connection.execute(text(f"DELETE FROM developer_files f WHERE {OWNED}{where}"),
                                     {**_scope(access), **params}).rowcount
    return DeleteAllResult(deleted=deleted)


@router.get("/download-all")
def download_all(folder: str | None = Query(None),
                 access: Access = Depends(require_file_access)) -> StreamingResponse:
    """Every file the user can see (in the folder, when one is given), as one zip (newest first, as listed)."""
    where, params = folder_filter(folder)
    scope = {**_scope(access), **params}
    with engine.connect() as connection:
        if not connection.execute(text(f"SELECT 1 FROM developer_files f WHERE {OWNED}{where} LIMIT 1"), scope).first():
            raise HTTPException(status_code=404, detail="There are no files to download.")

    def rows() -> Iterator[tuple[str, bytes]]:
        # One row at a time from a server-side cursor.
        with engine.connect().execution_options(stream_results=True, yield_per=1) as connection:
            for row in connection.execute(text(f"""SELECT f.filename, f.content FROM developer_files f
                    WHERE {OWNED}{where} ORDER BY f.uploaded_at DESC, f.filename"""), scope):
                yield row[0], bytes(row[1])

    name = f"sheriffsalehunter-files-{date.today().isoformat()}.zip"
    return StreamingResponse(zip_stream(rows()), media_type="application/zip", headers={
        "Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@router.get("/{file_id}/download")
def download_file(file_id: str, access: Access = Depends(require_file_access)) -> Response:
    with engine.connect() as connection:
        row = connection.execute(text(f"""SELECT filename, content_type, content FROM developer_files f
            WHERE f.id::text = :id AND {OWNED}"""), {"id": file_id, **_scope(access)}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="File not found.")
    ascii_name = row["filename"].encode("ascii", "replace").decode().replace('"', "'")
    return Response(content=bytes(row["content"]), media_type=row["content_type"], headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(row['filename'])}",
        "Cache-Control": "no-store",
    })


@router.patch("/{file_id}", response_model=StoredFile)
def move_file(file_id: str, body: MoveFile, access: Access = Depends(require_file_access)) -> StoredFile:
    """Put a file in a folder, or (folder_id null) take it out of its folder."""
    with engine.begin() as connection:
        folder_id = _require_folder(connection, body.folder_id)
        row = connection.execute(text(f"""UPDATE developer_files f SET folder_id = CAST(:folder_id AS uuid)
            WHERE f.id::text = :id AND {OWNED}
            RETURNING f.id, f.filename, f.source_zip, f.size_bytes, f.uploaded_at, f.folder_id"""),
            {"id": file_id, "folder_id": folder_id, **_scope(access)}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="File not found.")
    return _row(row)


@router.delete("/{file_id}", status_code=204)
def delete_file(file_id: str, access: Access = Depends(require_file_access)) -> Response:
    with engine.begin() as connection:
        deleted = connection.execute(text(f"""DELETE FROM developer_files f
            WHERE f.id::text = :id AND {OWNED}"""), {"id": file_id, **_scope(access)}).rowcount
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found.")
    return Response(status_code=204)
