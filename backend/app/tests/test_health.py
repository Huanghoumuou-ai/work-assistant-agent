from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.main import app


def test_health_root_returns_200() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["code"] == "OK"


def test_health_api_returns_200() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["code"] == "OK"


def test_settings_status_does_not_expose_api_key() -> None:
    original_key = settings.openai_api_key
    settings.openai_api_key = "sk-test-secret-value"
    try:
        with TestClient(app) as client:
            response = client.get("/api/settings/status")
    finally:
        settings.openai_api_key = original_key
    body = response.json()
    text = response.text.lower()

    assert response.status_code == 200
    assert body["code"] == "OK"
    assert body["data"]["providers"]["openai_configured"] is True
    migration = body["data"]["database"]["migration"]
    assert set(migration) == {"current_revision", "head_revision", "up_to_date"}
    assert migration["head_revision"]
    assert migration["up_to_date"] is True
    pipeline_worker = body["data"]["pipeline_worker"]
    assert set(pipeline_worker) == {"running", "worker_id", "concurrency", "poll_interval_seconds", "lock_timeout_seconds"}
    assert pipeline_worker["concurrency"] == 1
    assert "openai_api_key" not in text
    assert "api_key" not in text
    assert "sk-test-secret-value" not in response.text


def test_settings_status_exposes_safe_runtime_limits() -> None:
    with TestClient(app) as client:
        response = client.get("/api/settings/status")

    assert response.status_code == 200
    limits = response.json()["data"]["limits"]
    assert limits == {
        "max_upload_size_mb": settings.max_upload_size_mb,
        "max_parse_chars": settings.max_parse_chars,
        "max_parse_pages": settings.max_parse_pages,
        "max_parse_rows": settings.max_parse_rows,
        "max_parse_sheets": settings.max_parse_sheets,
        "max_chunk_chars": settings.max_chunk_chars,
        "chunk_overlap_chars": settings.chunk_overlap_chars,
        "max_chunks_per_document": settings.max_chunks_per_document,
        "embedding_batch_size": settings.embedding_batch_size,
        "embedding_timeout_seconds": settings.embedding_timeout_seconds,
        "default_retrieval_top_k": settings.default_retrieval_top_k,
        "max_retrieval_top_k": settings.max_retrieval_top_k,
        "llm_timeout_seconds": settings.llm_timeout_seconds,
        "rag_top_k": settings.rag_top_k,
        "rag_max_context_chars": settings.rag_max_context_chars,
        "rag_source_excerpt_chars": settings.rag_source_excerpt_chars,
        "rag_query_rewrite_enabled": settings.rag_query_rewrite_enabled,
        "rag_query_rewrite_max_chars": settings.rag_query_rewrite_max_chars,
        "memory_context_max_chars_per_item": settings.memory_context_max_chars_per_item,
        "memory_context_max_total_chars": settings.memory_context_max_total_chars,
        "chat_context_recent_messages": settings.chat_context_recent_messages,
        "chat_context_max_chars": settings.chat_context_max_chars,
        "conversation_summary_max_messages": settings.conversation_summary_max_messages,
        "conversation_summary_max_chars": settings.conversation_summary_max_chars,
        "conversation_summary_target_chars": settings.conversation_summary_target_chars,
        "auto_summary_enabled": settings.auto_summary_enabled,
        "auto_summary_min_new_messages": settings.auto_summary_min_new_messages,
        "auto_summary_min_total_messages": settings.auto_summary_min_total_messages,
        "auto_summary_max_per_chat": settings.auto_summary_max_per_chat,
    }
