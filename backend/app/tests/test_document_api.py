from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Document, Project
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.services import document_service


def _document_count() -> int:
    with SessionLocal() as db:
        return len(db.execute(select(Document)).scalars().all())


def test_upload_file_saves_metadata_and_relative_path() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("notes.md", b"# Notes\nSecond stage.", "text/markdown")},
        )

    assert response.status_code == 200
    body = response.json()
    document = body["data"]
    assert body["code"] == "OK"
    assert document["original_filename"] == "notes.md"
    assert document["stored_filename"] == f"{document['id']}.md"
    assert document["relative_path"].startswith("files/")
    assert not Path(document["relative_path"]).is_absolute()
    assert document["status"] == "uploaded"

    stored_path = settings.data_path / document["relative_path"]
    assert stored_path.exists()
    assert stored_path.read_bytes() == b"# Notes\nSecond stage."


def test_upload_empty_file_does_not_create_document() -> None:
    before = _document_count()
    with TestClient(app) as client:
        response = client.post("/api/upload", files={"file": ("empty.txt", b"", "text/plain")})

    assert response.status_code == 400
    assert _document_count() == before


def test_upload_unsupported_extension_does_not_create_document() -> None:
    before = _document_count()
    with TestClient(app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("script.exe", b"not allowed", "application/octet-stream")},
        )

    assert response.status_code == 400
    assert _document_count() == before


def test_upload_rejects_path_traversal_filename() -> None:
    before = _document_count()
    with TestClient(app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("../secret.md", b"bad", "text/markdown")},
        )

    assert response.status_code == 400
    assert _document_count() == before


def test_upload_rejects_file_over_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    before = _document_count()
    monkeypatch.setattr(settings, "max_upload_size_mb", 0)

    with TestClient(app) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("large.md", b"x", "text/markdown")},
        )

    assert response.status_code == 400
    assert _document_count() == before


def test_upload_rejects_missing_project_id() -> None:
    before = _document_count()
    with TestClient(app) as client:
        response = client.post(
            "/api/upload",
            data={"project_id": "00000000-0000-0000-0000-000000000000"},
            files={"file": ("notes.md", b"hello", "text/markdown")},
        )

    assert response.status_code == 400
    assert _document_count() == before


def test_upload_allows_existing_project_id() -> None:
    with SessionLocal() as db:
        project = Project(name="Upload Project")
        db.add(project)
        db.commit()
        db.refresh(project)

    with TestClient(app) as client:
        response = client.post(
            "/api/upload",
            data={"project_id": project.id},
            files={"file": ("project.csv", b"name,value\nA,1\n", "text/csv")},
        )

    assert response.status_code == 200
    assert response.json()["data"]["project_id"] == project.id


def test_create_text_document_saves_markdown_document() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/documents/text",
            json={
                "title": "Copied requirement",
                "content": "This copied paragraph should enter the knowledge base.",
            },
        )

    assert response.status_code == 200
    document = response.json()["data"]
    assert document["original_filename"] == "Copied requirement.md"
    assert document["stored_filename"] == f"{document['id']}.md"
    assert document["relative_path"].startswith("files/")
    assert document["extension"] == ".md"
    assert document["mime_type"] == "text/markdown"
    assert document["status"] == "uploaded"
    assert (settings.data_path / document["relative_path"]).read_text(encoding="utf-8") == "This copied paragraph should enter the knowledge base."


def test_create_text_document_rejects_empty_content() -> None:
    before = _document_count()
    with TestClient(app) as client:
        response = client.post(
            "/api/documents/text",
            json={"title": "Empty", "content": "   "},
        )

    assert response.status_code == 400
    assert _document_count() == before


def test_database_failure_removes_saved_file(monkeypatch: pytest.MonkeyPatch) -> None:
    before_files = {path for path in settings.files_path.rglob("*") if path.is_file()}

    def fail_commit(self: Session) -> None:
        raise RuntimeError("forced commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/upload",
            files={"file": ("cleanup.md", b"cleanup", "text/markdown")},
        )

    after_files = {path for path in settings.files_path.rglob("*") if path.is_file()}
    assert response.status_code == 500
    assert after_files == before_files


def test_get_documents_paginates_and_validates_query() -> None:
    with TestClient(app) as client:
        upload = client.post(
            "/api/upload",
            files={"file": ("list.md", b"list", "text/markdown")},
        )
        assert upload.status_code == 200

        response = client.get("/api/documents")
        invalid_limit = client.get("/api/documents?limit=101")
        invalid_offset = client.get("/api/documents?offset=-1")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["limit"] == 50
    assert data["offset"] == 0
    assert data["total"] >= 1
    assert isinstance(data["items"], list)
    assert invalid_limit.status_code == 422
    assert invalid_offset.status_code == 422


def test_get_document_by_id() -> None:
    with TestClient(app) as client:
        upload = client.post(
            "/api/upload",
            files={"file": ("single.pdf", b"%PDF-pretend", "application/pdf")},
        )
        document_id = upload.json()["data"]["id"]
        response = client.get(f"/api/documents/{document_id}")

    assert response.status_code == 200
    assert response.json()["data"]["id"] == document_id
