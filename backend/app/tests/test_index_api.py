from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.models import Document, DocumentChunk, DocumentEmbeddingResult
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.services import index_service
from backend.app.services.embedding_provider import EmbeddingProviderInfo
from backend.app.services.vector_store import ChromaVectorStore, VectorRecord


@pytest.fixture(autouse=True)
def isolate_chroma_collection(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "chroma_collection_name", f"index_{uuid4().hex}")


def _upload(name: str, content: bytes, content_type: str = "text/plain") -> dict:
    with TestClient(app) as client:
        response = client.post("/api/upload", files={"file": (name, content, content_type)})
    assert response.status_code == 200
    return response.json()["data"]


def _parse(document_id: str) -> dict:
    with TestClient(app) as client:
        response = client.post(f"/api/documents/{document_id}/parse")
    assert response.status_code == 200
    return response.json()["data"]


def _chunk(document_id: str) -> dict:
    with TestClient(app) as client:
        response = client.post(f"/api/documents/{document_id}/chunks")
    assert response.status_code == 200
    return response.json()["data"]


def _index(document_id: str):
    with TestClient(app) as client:
        return client.post(f"/api/documents/{document_id}/index")


def _ready_document(name: str = "index.md", content: bytes = b"index me") -> dict:
    document = _upload(name, content)
    _parse(document["id"])
    _chunk(document["id"])
    return document


def _embedding_result(document_id: str) -> DocumentEmbeddingResult | None:
    with SessionLocal() as db:
        return db.get(DocumentEmbeddingResult, document_id)


def test_fake_provider_indexes_chunked_document(monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    document = _ready_document("fake-index.md", b"alpha beta gamma")

    response = _index(document["id"])

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "indexed"
    assert data["provider"] == "fake"
    assert data["embedding_dimension"] == 8
    assert data["indexed_chunk_count"] >= 1
    assert json.loads(data["vector_ids_json"])

    with TestClient(app) as client:
        loaded = client.get(f"/api/documents/{document['id']}")
        index_loaded = client.get(f"/api/documents/{document['id']}/index")
        status = client.get("/api/index/status")

    assert loaded.status_code == 200
    assert loaded.json()["data"]["embedding_result"]["status"] == "indexed"
    assert index_loaded.status_code == 200
    assert status.status_code == 200
    assert status.json()["data"]["provider_configured"] is True
    assert "api_key" not in status.text.lower()


def test_openai_provider_without_api_key_returns_400_without_writes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    document = _ready_document("openai-missing-key.md", b"needs key")

    response = _index(document["id"])

    assert response.status_code == 400
    assert _embedding_result(document["id"]) is None


def test_unparsed_unchunked_archived_and_failed_chunk_return_400(monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    unparsed = _upload("unparsed-index.md", b"unparsed")
    unchunked = _upload("unchunked-index.md", b"unchunked")
    _parse(unchunked["id"])
    archived = _ready_document("archived-index.md", b"archived")
    with TestClient(app) as client:
        client.patch(f"/api/documents/{archived['id']}/status", json={"status": "archived"})

    assert _index(unparsed["id"]).status_code == 400
    assert _index(unchunked["id"]).status_code == 400
    assert _index(archived["id"]).status_code == 400


def test_empty_chunk_count_indexes_successfully_without_vectors(monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    document = _ready_document("empty-index.md", b" \n\t \n")

    response = _index(document["id"])

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "indexed"
    assert data["indexed_chunk_count"] == 0
    assert json.loads(data["vector_ids_json"]) == []


def test_all_empty_chunk_content_indexes_without_vectors(monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    document = _ready_document("empty-content-index.md", b"non-empty")
    with SessionLocal() as db:
        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == document["id"]).all()
        assert chunks
        for chunk in chunks:
            chunk.content = ""
        db.commit()

    response = _index(document["id"])

    assert response.status_code == 200
    assert response.json()["data"]["indexed_chunk_count"] == 0


def test_chunk_set_sha256_uses_fixed_metadata_fields() -> None:
    chunks = [
        DocumentChunk(id="b", document_id="doc", chunk_index=1, content="beta", content_sha256="sha-b", char_start=10, char_end=20, char_count=4),
        DocumentChunk(id="a", document_id="doc", chunk_index=0, content="alpha", content_sha256="sha-a", char_start=0, char_end=5, char_count=5),
    ]
    digest = hashlib.sha256()
    for parts in [
        ["a", "sha-a", "0", "0", "5"],
        ["b", "sha-b", "1", "10", "20"],
    ]:
        digest.update("\x1f".join(parts).encode("utf-8"))
        digest.update(b"\n")

    assert index_service.compute_chunk_set_sha256(chunks) == digest.hexdigest()


def test_reuses_existing_index_when_fingerprint_provider_and_model_match(monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    document = _ready_document("reuse-index.md", b"reuse index")

    first = _index(document["id"])
    second = _index(document["id"])

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["indexed_at"] == second.json()["data"]["indexed_at"]


def test_reindexes_when_fingerprint_changes(monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    document = _ready_document("reindex.md", b"before")
    first = _index(document["id"]).json()["data"]

    with SessionLocal() as db:
        chunk = db.query(DocumentChunk).filter(DocumentChunk.document_id == document["id"]).first()
        assert chunk is not None
        chunk.content = "after"
        chunk.content_sha256 = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
        db.commit()

    second = _index(document["id"])

    assert second.status_code == 200
    assert second.json()["data"]["chunk_set_sha256"] != first["chunk_set_sha256"]


def test_invalid_vector_ids_json_falls_back_to_document_filter(monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    document = _ready_document("fallback-delete.md", b"fallback")
    assert _index(document["id"]).status_code == 200
    with SessionLocal() as db:
        result = db.get(DocumentEmbeddingResult, document["id"])
        assert result is not None
        result.vector_ids_json = "not json"
        chunk = db.query(DocumentChunk).filter(DocumentChunk.document_id == document["id"]).first()
        assert chunk is not None
        chunk.content = "fallback changed"
        chunk.content_sha256 = hashlib.sha256(chunk.content.encode("utf-8")).hexdigest()
        db.commit()

    response = _index(document["id"])

    assert response.status_code == 200
    assert json.loads(response.json()["data"]["vector_ids_json"])


def test_collection_dimension_mismatch_refuses_index(monkeypatch) -> None:
    collection_name = f"dimension_mismatch_{uuid4().hex}"
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    monkeypatch.setattr(settings, "chroma_collection_name", collection_name)
    store = ChromaVectorStore(collection_name)
    store.upsert(
        [
            VectorRecord(
                id="manual:dimension",
                embedding=[0.1, 0.2, 0.3],
                metadata={"document_id": "manual"},
                document="manual",
            )
        ]
    )
    document = _ready_document("dimension-mismatch.md", b"dimension mismatch")

    response = _index(document["id"])

    assert response.status_code == 400
    assert "dimension" in response.json()["detail"]["message"].lower()


@dataclass
class FailingProvider:
    message: str = "forced embedding failure"

    @property
    def info(self) -> EmbeddingProviderInfo:
        return EmbeddingProviderInfo(provider="fake", model=settings.embedding_model, configured=True)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError(self.message)


def test_embedding_batch_failure_writes_failed_without_vectors(monkeypatch) -> None:
    document = _ready_document("embedding-failure.md", b"embedding failure")
    monkeypatch.setattr(index_service, "get_embedding_provider", lambda: FailingProvider())

    response = _index(document["id"])

    assert response.status_code == 400
    result = _embedding_result(document["id"])
    assert result is not None
    assert result.status == "failed"
    assert result.indexed_chunk_count == 0


def test_chroma_upsert_failure_writes_failed(monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    document = _ready_document("upsert-failure.md", b"upsert failure")

    class FailingStore(ChromaVectorStore):
        def upsert(self, records):  # type: ignore[no-untyped-def]
            raise RuntimeError("forced upsert failure")

    monkeypatch.setattr(index_service, "ChromaVectorStore", FailingStore)

    response = _index(document["id"])

    assert response.status_code == 400
    result = _embedding_result(document["id"])
    assert result is not None
    assert result.status == "failed"


def test_db_write_failure_cleans_upserted_vectors_and_records_orphan_warning(monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    document = _ready_document("db-write-failure.md", b"db write failure")
    deleted_ids: list[str] = []

    class TrackingStore(ChromaVectorStore):
        def delete_ids(self, ids):  # type: ignore[no-untyped-def]
            deleted_ids.extend(ids)
            super().delete_ids(ids)

    def fail_write(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("forced db write failure")

    monkeypatch.setattr(index_service, "ChromaVectorStore", TrackingStore)
    monkeypatch.setattr(index_service, "_write_indexed_result", fail_write)

    response = _index(document["id"])

    assert response.status_code == 400
    assert deleted_ids
    result = _embedding_result(document["id"])
    assert result is not None
    assert result.status == "failed"


def test_db_write_failure_logs_orphan_warning_when_compensation_fails(monkeypatch, caplog) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    document = _ready_document("orphan-warning.md", b"orphan warning")

    class BrokenDeleteStore(ChromaVectorStore):
        def delete_ids(self, ids):  # type: ignore[no-untyped-def]
            raise RuntimeError("forced compensation failure")

    def fail_write(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("forced db write failure")

    monkeypatch.setattr(index_service, "ChromaVectorStore", BrokenDeleteStore)
    monkeypatch.setattr(index_service, "_write_indexed_result", fail_write)

    response = _index(document["id"])

    assert response.status_code == 400
    result = _embedding_result(document["id"])
    assert result is not None
    assert "orphan vectors" in (result.error_message or "").lower()
    assert "Failed to delete vectors" in caplog.text


def test_delete_document_removes_vectors_and_embedding_result(monkeypatch) -> None:
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    document = _ready_document("delete-index.md", b"delete indexed document")
    assert _index(document["id"]).status_code == 200

    with TestClient(app) as client:
        delete = client.delete(f"/api/documents/{document['id']}")

    assert delete.status_code == 200
    with SessionLocal() as db:
        assert db.get(Document, document["id"]) is None
        assert db.get(DocumentEmbeddingResult, document["id"]) is None
    store = ChromaVectorStore(settings.chroma_collection_name)
    remaining = store.collection.get(where={"document_id": document["id"]})
    assert remaining["ids"] == []
