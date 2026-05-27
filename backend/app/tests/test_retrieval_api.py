from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.models import DocumentEmbeddingResult
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.services.vector_store import ChromaVectorStore, VectorRecord


def _use_fake_collection(monkeypatch) -> str:  # type: ignore[no-untyped-def]
    collection_name = f"retrieval_{uuid4().hex}"
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    monkeypatch.setattr(settings, "chroma_collection_name", collection_name)
    monkeypatch.setattr(settings, "default_retrieval_top_k", 5)
    monkeypatch.setattr(settings, "max_retrieval_top_k", 20)
    return collection_name


def _upload(name: str, content: bytes, project_id: str | None = None) -> dict:
    data = {"project_id": project_id} if project_id else None
    with TestClient(app) as client:
        response = client.post(
            "/api/upload",
            data=data,
            files={"file": (name, content, "text/plain")},
        )
    assert response.status_code == 200
    return response.json()["data"]


def _create_project(name: str) -> dict:
    with TestClient(app) as client:
        response = client.post("/api/projects", json={"name": name, "description": None})
    assert response.status_code == 200
    return response.json()["data"]


def _ready_indexed_document(monkeypatch, name: str = "retrieval.md", content: bytes = b"alpha beta gamma") -> dict:  # type: ignore[no-untyped-def]
    _use_fake_collection(monkeypatch)
    document = _upload(name, content)
    with TestClient(app) as client:
        assert client.post(f"/api/documents/{document['id']}/parse").status_code == 200
        assert client.post(f"/api/documents/{document['id']}/chunks").status_code == 200
        assert client.post(f"/api/documents/{document['id']}/index").status_code == 200
    return document


def _search(payload: dict):
    with TestClient(app) as client:
        return client.post("/api/retrieval/search", json=payload)


def test_retrieval_returns_source_metadata_without_content(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    document = _ready_indexed_document(monkeypatch, content=b"alpha beta gamma source metadata")

    response = _search({"query": "alpha", "top_k": 5})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["query"] == "alpha"
    assert data["items"]
    item = data["items"][0]
    assert item["rank"] == 1
    assert item["document_id"] == document["id"]
    assert item["source_filename"] == document["original_filename"]
    assert item["score"] == 1 / (1 + max(item["distance"], 0))
    assert "content" not in item
    assert "embedding" not in item


def test_empty_query_and_invalid_top_k_return_400(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_collection(monkeypatch)

    empty = _search({"query": "   "})
    zero = _search({"query": "alpha", "top_k": 0})
    too_large = _search({"query": "alpha", "top_k": 21})

    assert empty.status_code == 400
    assert zero.status_code == 400
    assert too_large.status_code == 400


def test_missing_project_or_document_filter_returns_400(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_collection(monkeypatch)

    missing_project = _search({"query": "alpha", "project_id": str(uuid4())})
    missing_document = _search({"query": "alpha", "document_id": str(uuid4())})

    assert missing_project.status_code == 400
    assert missing_document.status_code == 400


def test_archived_document_filter_returns_empty_and_default_search_excludes_archived(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    document = _ready_indexed_document(monkeypatch, content=b"archive alpha")
    with TestClient(app) as client:
        archive = client.patch(f"/api/documents/{document['id']}/status", json={"status": "archived"})
    assert archive.status_code == 200

    by_document = _search({"query": "archive", "document_id": document["id"]})
    default = _search({"query": "archive"})

    assert by_document.status_code == 200
    assert by_document.json()["data"]["items"] == []
    assert default.status_code == 200
    assert default.json()["data"]["items"] == []


def test_project_and_document_filters_work(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    collection_name = _use_fake_collection(monkeypatch)
    project = _create_project(f"Retrieval Project {uuid4().hex[:8]}")
    matching = _upload("matching.md", b"alpha project document", project_id=project["id"])
    other = _upload("other.md", b"alpha other document")
    with TestClient(app) as client:
        for document in [matching, other]:
            assert client.post(f"/api/documents/{document['id']}/parse").status_code == 200
            assert client.post(f"/api/documents/{document['id']}/chunks").status_code == 200
            assert client.post(f"/api/documents/{document['id']}/index").status_code == 200

    project_response = _search({"query": "alpha", "project_id": project["id"], "top_k": 10})
    document_response = _search({"query": "alpha", "document_id": other["id"], "top_k": 10})

    assert project_response.status_code == 200
    assert {item["document_id"] for item in project_response.json()["data"]["items"]} == {matching["id"]}
    assert document_response.status_code == 200
    assert {item["document_id"] for item in document_response.json()["data"]["items"]} == {other["id"]}
    assert ChromaVectorStore(collection_name).count() >= 2


def test_sqlite_second_pass_drops_stale_chunk_set_hits(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    document = _ready_indexed_document(monkeypatch, content=b"stale alpha")
    with SessionLocal() as db:
        result = db.get(DocumentEmbeddingResult, document["id"])
        assert result is not None
        result.chunk_set_sha256 = "0" * 64
        db.commit()

    response = _search({"query": "stale", "top_k": 5})

    assert response.status_code == 200
    assert response.json()["data"]["items"] == []


def test_no_vectors_returns_empty_items(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_collection(monkeypatch)

    response = _search({"query": "nothing indexed"})

    assert response.status_code == 200
    assert response.json()["data"]["items"] == []


def test_openai_without_api_key_returns_400(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "embedding_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "chroma_collection_name", f"retrieval_openai_{uuid4().hex}")

    response = _search({"query": "needs key"})

    assert response.status_code == 400
    assert "OPENAI_API_KEY" in response.json()["detail"]["message"]


def test_embedding_dimension_mismatch_returns_400(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    collection_name = _use_fake_collection(monkeypatch)
    ChromaVectorStore(collection_name).upsert(
        [
            VectorRecord(
                id="manual:dimension",
                embedding=[0.1, 0.2, 0.3],
                metadata={"document_id": "manual"},
                document="manual",
            )
        ]
    )

    response = _search({"query": "dimension"})

    assert response.status_code == 400
    assert "dimension" in response.json()["detail"]["message"].lower()

