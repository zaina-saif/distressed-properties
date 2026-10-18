import io
import zipfile

from fastapi.testclient import TestClient

import pytest
from fastapi import HTTPException

from app.api.files import (clean_name, download_token, folder_filter, is_pdf, pdfs_in_zip, read_download_token,
                           unique_name, zip_stream)
from app.auth import Access, current_user
from app.main import app

PDF = b"%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF\n"


def zip_of(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in entries.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def test_zip_yields_its_pdfs_including_nested_folders():
    pdfs, skipped = pdfs_in_zip(zip_of({"a.pdf": PDF, "Queens/b.PDF": PDF, "notes.txt": b"hi",
                                        "__MACOSX/._a.pdf": b"x", ".DS_Store": b"x"}), "batch.zip")
    assert [name for name, _ in pdfs] == ["a.pdf", "b.PDF"]
    assert [(s.filename, s.reason) for s in skipped] == [("notes.txt", "not a PDF")]


def test_a_damaged_zip_is_reported():
    pdfs, skipped = pdfs_in_zip(b"not a zip", "bad.zip")
    assert pdfs == [] and skipped[0].reason == "not a valid zip file"


def test_names_lose_their_folders_and_pdfs_are_checked_by_content():
    assert clean_name("Queens/sub\\notice.pdf") == "notice.pdf"
    assert clean_name("") == "file.pdf"
    assert is_pdf(PDF) and not is_pdf(b"<html>")


def test_file_routes_are_for_developers_and_file_uploaders_only():
    app.dependency_overrides[current_user] = lambda: Access(user_id="u1", email="a@example.com", plan="pro",
                                                            plan_status="active")
    try:
        client = TestClient(app)
        assert client.get("/api/v1/files").status_code == 403
        assert client.post("/api/v1/files", files={"files": ("a.pdf", PDF, "application/pdf")}).status_code == 403
        assert client.delete("/api/v1/files/x").status_code == 403
        assert client.delete("/api/v1/files").status_code == 403
        assert client.get("/api/v1/files/folders").status_code == 403
        assert client.patch("/api/v1/files/x", json={"folder_id": None}).status_code == 403
        assert client.get("/api/v1/files/download-all").status_code == 403
        assert client.post("/api/v1/files/download-all/link").status_code == 403
        assert client.get("/api/v1/files/download-all/zip?token=x.y").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_only_developers_add_or_remove_folders():
    app.dependency_overrides[current_user] = lambda: Access(user_id="u1", email="a@example.com", role="file_uploader")
    try:
        client = TestClient(app)
        assert client.post("/api/v1/files/folders", json={"name": "Queens"}).status_code == 403
        assert client.delete("/api/v1/files/folders/x").status_code == 403
    finally:
        app.dependency_overrides.clear()


def test_download_all_zips_every_file_and_keeps_both_of_two_same_names():
    archive = zipfile.ZipFile(io.BytesIO(b"".join(zip_stream([("a.pdf", PDF), ("A.pdf", PDF + b"2"), ("b.pdf", PDF)]))))
    assert archive.namelist() == ["a.pdf", "A (2).pdf", "b.pdf"]
    assert archive.read("A (2).pdf") == PDF + b"2" and archive.testzip() is None
    assert unique_name("notes", {"notes"}) == "notes (2)"


def test_download_links_carry_the_users_scope_and_expire():
    uploader = Access(user_id="u1", email="a@example.com", role="file_uploader")
    token = download_token(uploader, "none", now=1000)
    assert read_download_token(token, now=1200) == {"user_id": "u1", "developer": False, "folder": "none",
                                                     "expires": 1300}
    with pytest.raises(HTTPException, match="expired"):
        read_download_token(token, now=1301)
    signature = token.split(".")[1]
    forged = download_token(Access(user_id="u2", email="b@example.com", role="developer"), None, now=1000)
    with pytest.raises(HTTPException, match="not valid"):
        read_download_token(f"{forged.split('.')[0]}.{signature}", now=1200)


def test_folder_filter_takes_a_folder_id_none_or_nothing():
    assert folder_filter(None) == ("", {})
    assert folder_filter("none") == (" AND f.folder_id IS NULL", {})
    folder_id = "8f14e45f-ceea-467a-9575-a1b2c3d4e5f6"
    assert folder_filter(folder_id) == (" AND f.folder_id = CAST(:folder_id AS uuid)", {"folder_id": folder_id})
    with pytest.raises(HTTPException):
        folder_filter("not-a-folder")
