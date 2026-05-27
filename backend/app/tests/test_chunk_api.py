from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Document, DocumentChunk, DocumentChunkResult, DocumentParseResult
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.services import chunk_service


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


def _chunk(document_id: str):
    with TestClient(app) as client:
        return client.post(f"/api/documents/{document_id}/chunks")


def _chunk_rows(document_id: str) -> list[DocumentChunk]:
    with SessionLocal() as db:
        return list(db.query(DocumentChunk).filter(DocumentChunk.document_id == document_id).all())


def test_parsed_document_chunks_successfully_and_hides_content(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_chunk_chars", 12)
    monkeypatch.setattr(settings, "chunk_overlap_chars", 2)
    document = _upload("chunk-me.md", b"alpha beta gamma delta")
    parsed = _parse(document["id"])

    response = _chunk(document["id"])

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "chunked"
    assert data["chunk_count"] > 0
    assert data["parse_content_sha256"] == parsed["content_sha256"]

    with TestClient(app) as client:
        by_document = client.get(f"/api/documents/{document['id']}/chunks")
        all_chunks = client.get(f"/api/chunks?document_id={document['id']}")

    assert by_document.status_code == 200
    assert all_chunks.status_code == 200
    assert by_document.json()["data"]["chunks"]
    assert "content" not in by_document.json()["data"]["chunks"][0]
    assert "content" not in all_chunks.json()["data"]["items"][0]

    chunk_id = by_document.json()["data"]["chunks"][0]["id"]
    with TestClient(app) as client:
      chunk_detail = client.get(f"/api/chunks/{chunk_id}")

    assert chunk_detail.status_code == 200
    assert chunk_detail.json()["data"]["content"]


def test_chunk_content_rejects_archived_document() -> None:
    document = _upload("archived-detail.md", b"archived detail text")
    _parse(document["id"])
    assert _chunk(document["id"]).status_code == 200

    with TestClient(app) as client:
        chunks = client.get(f"/api/documents/{document['id']}/chunks").json()["data"]["chunks"]
        client.patch(f"/api/documents/{document['id']}/status", json={"status": "archived"})
        detail = client.get(f"/api/chunks/{chunks[0]['id']}")

    assert detail.status_code == 400


def test_chunking_preserves_parsed_crlf_hash() -> None:
    document = _upload("crlf.md", b"line one\r\nline two")
    _parse(document["id"])

    response = _chunk(document["id"])

    assert response.status_code == 200
    assert response.json()["data"]["status"] == "chunked"


def test_unparsed_archived_and_failed_parse_documents_return_400() -> None:
    unparsed = _upload("unparsed.md", b"unparsed")
    archived = _upload("archived-for-chunk.md", b"archived")
    failed = _upload("failed-parse.md", b"failed")

    with TestClient(app) as client:
        client.patch(f"/api/documents/{archived['id']}/status", json={"status": "archived"})
    with SessionLocal() as db:
        db.add(
            DocumentParseResult(
                document_id=failed["id"],
                status="failed",
                source_sha256=failed["sha256"],
                char_count=0,
                truncated=False,
                error_message="forced failed parse",
            )
        )
        db.commit()

    assert _chunk(unparsed["id"]).status_code == 400
    assert _chunk(archived["id"]).status_code == 400
    assert _chunk(failed["id"]).status_code == 400


def test_parsed_path_escape_is_rejected_without_chunks() -> None:
    document = _upload("unsafe-chunk.md", b"unsafe")
    _parse(document["id"])
    with SessionLocal() as db:
        result = db.get(DocumentParseResult, document["id"])
        assert result is not None
        result.parsed_relative_path = "../files/unsafe.txt"
        db.commit()

    response = _chunk(document["id"])

    assert response.status_code == 500
    assert not _chunk_rows(document["id"])


def test_missing_parsed_file_records_failed_result() -> None:
    document = _upload("missing-parsed.md", b"missing parsed")
    parsed = _parse(document["id"])
    (settings.data_path / parsed["parsed_relative_path"]).unlink()

    response = _chunk(document["id"])

    assert response.status_code == 400
    with SessionLocal() as db:
        result = db.get(DocumentChunkResult, document["id"])
        assert result is not None
        assert result.status == "failed"
        assert result.chunk_count == 0
        assert not db.query(DocumentChunk).filter(DocumentChunk.document_id == document["id"]).all()


def test_parsed_sha_mismatch_rejects_chunking() -> None:
    document = _upload("changed-parsed.md", b"original parsed")
    parsed = _parse(document["id"])
    (settings.data_path / parsed["parsed_relative_path"]).write_text("changed parsed", encoding="utf-8")

    response = _chunk(document["id"])

    assert response.status_code == 400
    assert "checksum" in response.json()["detail"]["message"].lower()
    assert not _chunk_rows(document["id"])


def test_repeated_chunking_reuses_existing_result() -> None:
    document = _upload("reuse-chunk.md", b"reuse chunk text")
    _parse(document["id"])

    first = _chunk(document["id"])
    second = _chunk(document["id"])

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["data"]["chunked_at"] == second.json()["data"]["chunked_at"]
    assert len(_chunk_rows(document["id"])) == first.json()["data"]["chunk_count"]


def test_failed_chunk_result_can_retry(monkeypatch) -> None:
    document = _upload("retry-chunk.md", b"retry chunk")
    _parse(document["id"])

    def fail_clean(text: str) -> str:
        raise RuntimeError("temporary chunk failure")

    monkeypatch.setattr(chunk_service, "clean_text", fail_clean)
    failed = _chunk(document["id"])
    assert failed.status_code == 400

    monkeypatch.undo()
    retried = _chunk(document["id"])
    assert retried.status_code == 200
    assert retried.json()["data"]["status"] == "chunked"


def test_overlap_greater_than_or_equal_to_max_chunk_chars_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_chunk_chars", 10)
    monkeypatch.setattr(settings, "chunk_overlap_chars", 10)
    document = _upload("invalid-overlap.md", b"invalid overlap")
    _parse(document["id"])

    response = _chunk(document["id"])

    assert response.status_code == 400
    assert "less than" in response.json()["detail"]["message"]
    assert not _chunk_rows(document["id"])


def test_empty_cleaned_text_is_chunked_successfully() -> None:
    document = _upload("empty-cleaned.md", b" \n\t \n")
    _parse(document["id"])

    response = _chunk(document["id"])

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "chunked"
    assert data["chunk_count"] == 0
    assert _chunk_rows(document["id"]) == []


def test_max_chunks_truncates_result(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_chunk_chars", 10)
    monkeypatch.setattr(settings, "chunk_overlap_chars", 0)
    monkeypatch.setattr(settings, "max_chunks_per_document", 2)
    document = _upload("truncate-chunks.md", b"abcdefghij" * 5)
    _parse(document["id"])

    response = _chunk(document["id"])

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["chunk_count"] == 2
    assert data["truncated"] is True
    assert len(_chunk_rows(document["id"])) == 2


def test_markdown_headings_start_new_chunks(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_chunk_chars", 80)
    monkeypatch.setattr(settings, "chunk_overlap_chars", 0)
    document = _upload("heading-aware.md", b"# One\nalpha paragraph\n\n# Two\nbeta paragraph")
    _parse(document["id"])

    response = _chunk(document["id"])

    assert response.status_code == 200
    chunks = _chunk_rows(document["id"])
    assert [chunk.content for chunk in chunks] == ["# One\nalpha paragraph", "# Two\nbeta paragraph"]
    assert response.json()["data"]["chunker_name"] == "paragraph-markdown-boundary-chunker"
    assert response.json()["data"]["chunker_version"] == "2"


def test_paragraph_boundaries_are_preferred(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_chunk_chars", 45)
    monkeypatch.setattr(settings, "chunk_overlap_chars", 0)
    document = _upload("paragraph-aware.md", b"first paragraph stays together\n\nsecond paragraph stays together\n\nthird")
    _parse(document["id"])

    response = _chunk(document["id"])

    assert response.status_code == 200
    chunks = _chunk_rows(document["id"])
    assert chunks[0].content == "first paragraph stays together"
    assert chunks[1].content == "second paragraph stays together\n\nthird"


def test_chunking_db_failure_rolls_back_partial_chunks(monkeypatch) -> None:
    document = _upload("chunk-db-failure.md", b"db failure chunks")
    _parse(document["id"])

    def fail_commit(self: Session) -> None:
        raise RuntimeError("forced chunk commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(f"/api/documents/{document['id']}/chunks")

    assert response.status_code == 500
    with SessionLocal() as db:
        assert not db.query(DocumentChunk).filter(DocumentChunk.document_id == document["id"]).all()
        assert db.get(DocumentChunkResult, document["id"]) is None


def test_delete_document_removes_chunk_records() -> None:
    document = _upload("delete-chunks.md", b"delete chunk records")
    _parse(document["id"])
    assert _chunk(document["id"]).status_code == 200

    with TestClient(app) as client:
        response = client.delete(f"/api/documents/{document['id']}")

    assert response.status_code == 200
    with SessionLocal() as db:
        assert db.get(Document, document["id"]) is None
        assert db.get(DocumentChunkResult, document["id"]) is None
        assert not db.query(DocumentChunk).filter(DocumentChunk.document_id == document["id"]).all()


def test_intelligence_routes_still_return_501() -> None:
    expected_body = {
        "success": False,
        "code": "NOT_IMPLEMENTED",
        "message": "This API is reserved for later stages.",
        "data": None,
    }
    with TestClient(app) as client:
        for method, path in []:
            response = client.request(method, path)
            assert response.status_code == 501
            assert response.json() == expected_body
