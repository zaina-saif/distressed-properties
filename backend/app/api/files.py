"""Private PDF storage for developer accounts: upload PDFs one by one or as zip
archives, list them, download them and delete them. Each user sees only their
own files, and only developers can use these routes (main.py mounts the router
behind require_developer). Files live in the developer_files table.
"""
from __future__ import annotations

import hashlib
import io
import posixpath
import zipfile
from datetime import datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel
from sqlalchemy import text

from app.auth import Access, require_developer
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
    return StoredFile(id=str(row["id"]), filename=row["filename"], source_zip=row["source_zip"],
                      size_bytes=row["size_bytes"], uploaded_at=row["uploaded_at"])


@router.get("", response_model=list[StoredFile])
def list_files(access: Access = Depends(require_developer)) -> list[StoredFile]:
    with engine.connect() as connection:
        rows = connection.execute(text("""SELECT id, filename, source_zip, size_bytes, uploaded_at
            FROM developer_files WHERE user_id = :user_id ORDER BY uploaded_at DESC, filename"""),
            {"user_id": access.user_id}).mappings().all()
    return [_row(row) for row in rows]


@router.post("", response_model=UploadResult)
async def upload_files(files: list[UploadFile] = File(...),
                       access: Access = Depends(require_developer)) -> UploadResult:
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
        for name, content, source_zip in candidates:
            if not is_pdf(content):
                skipped.append(Skipped(filename=name, reason="not a valid PDF"))
                continue
            row = connection.execute(text("""INSERT INTO developer_files
                (user_id, filename, source_zip, size_bytes, sha256, content)
                VALUES (:user_id, :filename, :source_zip, :size, :sha256, :content)
                ON CONFLICT (user_id, sha256) DO NOTHING
                RETURNING id, filename, source_zip, size_bytes, uploaded_at"""), {
                    "user_id": access.user_id, "filename": name, "source_zip": source_zip,
                    "size": len(content), "sha256": hashlib.sha256(content).hexdigest(), "content": content,
                }).mappings().first()
            if row:
                saved.append(_row(row))
            else:
                skipped.append(Skipped(filename=name, reason="already uploaded"))
    return UploadResult(saved=saved, skipped=skipped)


@router.get("/{file_id}/download")
def download_file(file_id: str, access: Access = Depends(require_developer)) -> Response:
    with engine.connect() as connection:
        row = connection.execute(text("""SELECT filename, content_type, content FROM developer_files
            WHERE id::text = :id AND user_id = :user_id"""),
            {"id": file_id, "user_id": access.user_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="File not found.")
    ascii_name = row["filename"].encode("ascii", "replace").decode().replace('"', "'")
    return Response(content=bytes(row["content"]), media_type=row["content_type"], headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(row['filename'])}",
        "Cache-Control": "no-store",
    })


@router.delete("/{file_id}", status_code=204)
def delete_file(file_id: str, access: Access = Depends(require_developer)) -> Response:
    with engine.begin() as connection:
        deleted = connection.execute(text("""DELETE FROM developer_files
            WHERE id::text = :id AND user_id = :user_id"""), {"id": file_id, "user_id": access.user_id}).rowcount
    if not deleted:
        raise HTTPException(status_code=404, detail="File not found.")
    return Response(status_code=204)
