from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.models import Document, DocumentChunkResult, DocumentEmbeddingResult, DocumentParseResult, DocumentPipelineJob
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.services.vector_store import ChromaVectorStore
from backend.app.services.vector_store import VectorRecord


@pytest.fixture(autouse=True)
def isolate_chroma_collection(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "chroma_collection_name", f"diagnostics_{uuid4().hex}")


def _upload(name: str = "diagnostic.md", content: bytes = b"diagnostic content") -> dict:
    with TestClient(app) as client:
        response = client.post("/api/upload", files={"file": (name, content, "text/markdown")})
    assert response.status_code == 200
    return response.json()["data"]


def _ready_indexed_document(monkeypatch) -> dict:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    document = _upload("diagnostic-index.md", b"alpha beta gamma")
    with TestClient(app) as client:
        assert client.post(f"/api/documents/{document['id']}/parse").status_code == 200
        assert client.post(f"/api/documents/{document['id']}/chunks").status_code == 200
        index = client.post(f"/api/documents/{document['id']}/index")
    assert index.status_code == 200
    assert json.loads(index.json()["data"]["vector_ids_json"])
    return document


def test_fake_embedding_provider_test_returns_dimension(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "embedding_provider", "fake")

    with TestClient(app) as client:
        response = client.post("/api/providers/embedding/test")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "fake"
    assert data["ok"] is True
    assert data["dimension"] == 8
    assert data["latency_ms"] >= 0


def test_fake_llm_provider_test_returns_preview(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "llm_provider", "fake")

    with TestClient(app) as client:
        response = client.post("/api/providers/llm/test")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["provider"] == "fake"
    assert data["ok"] is True
    assert data["response_preview"]
    assert data["latency_ms"] >= 0


def test_openai_provider_tests_without_api_key_return_400_without_leak(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "embedding_provider", "openai")
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")

    with TestClient(app) as client:
        embedding = client.post("/api/providers/embedding/test")
        llm = client.post("/api/providers/llm/test")

    assert embedding.status_code == 400
    assert llm.status_code == 400
    assert "OPENAI_API_KEY" in embedding.json()["detail"]["message"]
    assert "OPENAI_API_KEY" in llm.json()["detail"]["message"]
    assert "sk-" not in embedding.text
    assert "sk-" not in llm.text

    with TestClient(app) as client:
        history = client.get("/api/providers/diagnostics/history?provider_kind=embedding")

    assert history.status_code == 200
    assert history.json()["data"]["items"]
    assert "sk-" not in history.text


def test_dashscope_chat_model_as_embedding_model_returns_clear_error(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "embedding_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "openai_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    monkeypatch.setattr(settings, "embedding_model", "qwen3-max")

    with TestClient(app) as client:
        response = client.post("/api/providers/embedding/test")

    assert response.status_code == 400
    message = response.json()["detail"]["message"]
    assert "DashScope embedding model" in message
    assert "text-embedding-v4" in message


def test_index_diagnostics_does_not_expose_sensitive_or_content(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "openai_api_key", "sk-diagnostics-secret")
    document = _ready_indexed_document(monkeypatch)

    with TestClient(app) as client:
        response = client.get("/api/index/diagnostics")

    assert response.status_code == 200
    text = response.text
    data = response.json()["data"]
    assert data["collection_name"] == settings.chroma_collection_name
    assert data["vector_count"] >= 1
    assert data["collection_dimension"] == 8
    assert data["indexed_document_count"] >= 1
    assert "sk-diagnostics-secret" not in text
    assert "alpha beta gamma" not in text


def test_index_diagnostics_detects_mixed_db_dimensions() -> None:
    first_id = str(uuid4())
    second_id = str(uuid4())
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        db.add_all(
            [
                DocumentEmbeddingResult(
                    document_id=first_id,
                    status="indexed",
                    provider="fake",
                    model="a",
                    embedding_dimension=8,
                    chunk_set_sha256="a" * 64,
                    indexed_chunk_count=1,
                    vector_collection=settings.chroma_collection_name,
                    indexed_at=now,
                    created_at=now,
                    updated_at=now,
                ),
                DocumentEmbeddingResult(
                    document_id=second_id,
                    status="indexed",
                    provider="fake",
                    model="b",
                    embedding_dimension=12,
                    chunk_set_sha256="b" * 64,
                    indexed_chunk_count=1,
                    vector_collection=settings.chroma_collection_name,
                    indexed_at=now,
                    created_at=now,
                    updated_at=now,
                ),
            ]
        )
        db.commit()

    with TestClient(app) as client:
        response = client.get("/api/index/diagnostics")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "warning"
    assert sorted(data["db_embedding_dimensions"]) == [8, 12]
    assert "mixed" in data["warning"].lower()
    with SessionLocal() as db:
        for document_id in (first_id, second_id):
            result = db.get(DocumentEmbeddingResult, document_id)
            if result is not None:
                db.delete(result)
        db.commit()


def test_index_reset_requires_confirmation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _ready_indexed_document(monkeypatch)

    with TestClient(app) as client:
        response = client.post(
            "/api/index/maintenance/reset",
            json={
                "confirm": "NOPE",
                "collection_name": settings.chroma_collection_name,
                "clear_embedding_results": True,
            },
        )

    assert response.status_code == 400


def test_index_reset_refuses_when_pipeline_active(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    document = _upload("active-reset.md", b"active reset")
    with SessionLocal() as db:
        db.add(DocumentPipelineJob(document_id=document["id"], status="queued"))
        db.commit()

    with TestClient(app) as client:
        response = client.post(
            "/api/index/maintenance/reset",
            json={
                "confirm": "RESET_INDEX",
                "collection_name": settings.chroma_collection_name,
                "clear_embedding_results": True,
            },
        )

    assert response.status_code == 400
    assert "pipeline" in response.json()["detail"]["message"].lower()
    with SessionLocal() as db:
        jobs = db.query(DocumentPipelineJob).filter(DocumentPipelineJob.document_id == document["id"]).all()
        for job in jobs:
            job.status = "failed"
        db.commit()


def test_index_reset_deletes_vectors_and_embedding_results_only(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    document = _ready_indexed_document(monkeypatch)
    store = ChromaVectorStore(settings.chroma_collection_name)
    assert store.count() >= 1

    with TestClient(app) as client:
        response = client.post(
            "/api/index/maintenance/reset",
            json={
                "confirm": "RESET_INDEX",
                "collection_name": settings.chroma_collection_name,
                "clear_embedding_results": True,
            },
        )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["vectors_deleted"] is True
    assert data["embedding_results_deleted"] >= 1

    with SessionLocal() as db:
        assert db.get(Document, document["id"]) is not None
        assert db.get(DocumentParseResult, document["id"]) is not None
        assert db.get(DocumentChunkResult, document["id"]) is not None
        assert db.get(DocumentEmbeddingResult, document["id"]) is None
    assert ChromaVectorStore(settings.chroma_collection_name).count() == 0


def test_index_collections_and_non_current_reset(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    document = _ready_indexed_document(monkeypatch)
    current_collection = settings.chroma_collection_name
    other_collection = f"other_{uuid4().hex}"
    other_doc = _upload("other-collection.md", b"other")
    other_store = ChromaVectorStore(other_collection)
    other_store.upsert(
        [
            VectorRecord(
                id=f"manual:{other_doc['id']}",
                embedding=[0.1] * 8,
                metadata={"document_id": other_doc["id"]},
                document="other",
            )
        ]
    )
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        db.add(
            DocumentEmbeddingResult(
                document_id=other_doc["id"],
                status="indexed",
                provider="fake",
                model=settings.embedding_model,
                embedding_dimension=8,
                chunk_set_sha256="c" * 64,
                indexed_chunk_count=1,
                vector_collection=other_collection,
                indexed_at=now,
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()

    with TestClient(app) as client:
        collections = client.get("/api/index/collections")
        reset = client.post(
            "/api/index/maintenance/reset",
            json={
                "confirm": "RESET_INDEX",
                "collection_name": other_collection,
                "clear_embedding_results": True,
            },
        )

    assert collections.status_code == 200
    collection_names = {item["name"] for item in collections.json()["data"]["items"]}
    assert {current_collection, other_collection}.issubset(collection_names)
    assert reset.status_code == 200
    assert reset.json()["data"]["collection_name"] == other_collection
    assert ChromaVectorStore(other_collection).count() == 0
    assert ChromaVectorStore(current_collection).count() >= 1
    with SessionLocal() as db:
        assert db.get(DocumentEmbeddingResult, other_doc["id"]) is None
        assert db.get(DocumentEmbeddingResult, document["id"]) is not None


def test_reset_then_batch_process_missing_can_create_job(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    document = _ready_indexed_document(monkeypatch)
    with TestClient(app) as client:
        reset = client.post(
            "/api/index/maintenance/reset",
            json={
                "confirm": "RESET_INDEX",
                "collection_name": settings.chroma_collection_name,
                "clear_embedding_results": True,
            },
        )
        batch = client.post("/api/pipeline/batch/process-missing")

    assert reset.status_code == 200
    assert batch.status_code == 202
    items = batch.json()["data"]["items"]
    assert any(item["document_id"] == document["id"] for item in items)
    with SessionLocal() as db:
        jobs = db.query(DocumentPipelineJob).filter(DocumentPipelineJob.document_id == document["id"]).all()
        for job in jobs:
            if job.status in {"queued", "running"}:
                job.status = "failed"
        db.commit()
