from __future__ import annotations

import logging
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.models import Document
from backend.app.db.session import SessionLocal
from backend.app.main import app


def _upload(name: str, content: bytes = b"stage3") -> dict:
    with TestClient(app) as client:
        response = client.post(
            "/api/upload",
            files={"file": (name, content, "text/markdown")},
        )
    assert response.status_code == 200
    return response.json()["data"]


def _create_project(name: str) -> dict:
    with TestClient(app) as client:
        response = client.post("/api/projects", json={"name": name})
    assert response.status_code == 200
    return response.json()["data"]


def test_archive_and_restore_change_only_status() -> None:
    document = _upload("archive-target.md")
    file_path = settings.data_path / document["relative_path"]

    with TestClient(app) as client:
        archived = client.patch(f"/api/documents/{document['id']}/status", json={"status": "archived"})
        restored = client.patch(f"/api/documents/{document['id']}/status", json={"status": "uploaded"})

    assert archived.status_code == 200
    assert archived.json()["data"]["status"] == "archived"
    assert restored.status_code == 200
    assert restored.json()["data"]["status"] == "uploaded"
    assert file_path.exists()
    with SessionLocal() as db:
        assert db.get(Document, document["id"]) is not None


def test_invalid_document_status_returns_400() -> None:
    document = _upload("invalid-status.md")

    with TestClient(app) as client:
        response = client.patch(f"/api/documents/{document['id']}/status", json={"status": "processing"})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "BAD_REQUEST"


def test_delete_document_removes_record_and_file_with_fixed_response() -> None:
    document = _upload("delete-target.md")
    file_path = settings.data_path / document["relative_path"]
    assert file_path.exists()

    with TestClient(app) as client:
        response = client.delete(f"/api/documents/{document['id']}")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "code": "OK",
        "message": "Document deleted.",
        "data": {"id": document["id"]},
    }
    assert not file_path.exists()
    with SessionLocal() as db:
        assert db.get(Document, document["id"]) is None


def test_delete_document_succeeds_when_file_is_missing() -> None:
    document = _upload("missing-file.md")
    file_path = settings.data_path / document["relative_path"]
    file_path.unlink()

    with TestClient(app) as client:
        response = client.delete(f"/api/documents/{document['id']}")

    assert response.status_code == 200
    with SessionLocal() as db:
        assert db.get(Document, document["id"]) is None


def test_delete_document_refuses_unsafe_file_path_and_logs_error(caplog) -> None:
    document = _upload("unsafe-path.md")
    with SessionLocal() as db:
        stored = db.get(Document, document["id"])
        assert stored is not None
        stored.relative_path = "../sqlite/workmemory.db"
        db.commit()

    caplog.set_level(logging.ERROR)
    with TestClient(app) as client:
        response = client.delete(f"/api/documents/{document['id']}")

    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "UNSAFE_FILE_PATH"
    assert "outside data/files" in caplog.text
    with SessionLocal() as db:
        assert db.get(Document, document["id"]) is not None


def test_get_documents_filters_sorts_and_counts_total() -> None:
    project = _create_project("Filter Project")

    with TestClient(app) as client:
        first = client.post(
            "/api/upload",
            data={"project_id": project["id"]},
            files={"file": ("filter-a.md", b"a", "text/markdown")},
        ).json()["data"]
        second = client.post(
            "/api/upload",
            data={"project_id": project["id"]},
            files={"file": ("filter-b.md", b"b", "text/markdown")},
        ).json()["data"]
        client.patch(f"/api/documents/{first['id']}/status", json={"status": "archived"})

        uploaded = client.get(f"/api/documents?project_id={project['id']}&status=uploaded&limit=10&offset=0")
        archived = client.get(f"/api/documents?project_id={project['id']}&status=archived&limit=10&offset=0")
        invalid_status = client.get("/api/documents?status=processing")

    assert uploaded.status_code == 200
    assert uploaded.json()["data"]["total"] == 1
    assert uploaded.json()["data"]["items"][0]["id"] == second["id"]
    assert archived.status_code == 200
    assert archived.json()["data"]["total"] == 1
    assert archived.json()["data"]["items"][0]["id"] == first["id"]
    assert invalid_status.status_code == 400
