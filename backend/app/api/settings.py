from __future__ import annotations

from fastapi import APIRouter

from backend.app.core.config import settings
from backend.app.core.runtime import ensure_runtime_dirs
from backend.app.api.health import _database_ok
from backend.app.db.migrations import migration_status
from backend.app.services.pipeline_service import worker_snapshot


router = APIRouter()


@router.get("/status")
async def settings_status() -> dict:
    ensure_runtime_dirs()
    pipeline_worker = worker_snapshot()
    return {
        "success": True,
        "code": "OK",
        "message": "Settings loaded.",
        "data": {
            "app": {
                "name": settings.app_name,
                "environment": settings.app_env,
                "version": settings.app_version,
                "timezone": settings.app_timezone,
            },
            "backend": {
                "host": settings.backend_host,
                "port": settings.backend_port,
            },
            "paths": {
                "data_dir": str(settings.data_path),
                "files_dir": str(settings.files_path),
                "parsed_dir": str(settings.parsed_path),
                "sqlite_db_path": str(settings.sqlite_path),
                "chroma_persist_dir": str(settings.chroma_path),
            },
            "database": {
                "type": "sqlite",
                "ok": _database_ok(),
                "migration": migration_status(),
            },
            "providers": {
                "openai_configured": bool(settings.openai_api_key),
                "openai_base_url_configured": bool(settings.openai_base_url),
                "openai_model": settings.openai_model,
                "llm_provider": settings.llm_provider,
                "embedding_provider": settings.embedding_provider,
                "embedding_model": settings.embedding_model,
                "chroma_collection_name": settings.chroma_collection_name,
            },
            "pipeline_worker": {
                "running": pipeline_worker["worker_running"],
                "worker_id": pipeline_worker["worker_id"],
                "concurrency": pipeline_worker["worker_concurrency"],
                "poll_interval_seconds": settings.pipeline_poll_interval_seconds,
                "lock_timeout_seconds": settings.pipeline_lock_timeout_seconds,
            },
            "limits": {
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
            },
        },
    }
