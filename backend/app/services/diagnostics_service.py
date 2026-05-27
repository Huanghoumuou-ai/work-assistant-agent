from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import DocumentEmbeddingResult, DocumentPipelineJob, ProviderDiagnosticRun
from backend.app.services.embedding_provider import get_embedding_provider
from backend.app.services.llm_provider import get_chat_provider
from backend.app.services.pipeline_service import RECOVERED_MESSAGE
from backend.app.services.vector_store import ChromaVectorStore


@dataclass(frozen=True)
class ProviderDiagnostic:
    provider: str
    model: str
    configured: bool
    ok: bool
    latency_ms: int
    message: str
    dimension: int | None = None
    response_preview: str | None = None


def _api_error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "success": False,
            "code": code,
            "message": message,
            "data": None,
        },
    )


def _bad_request(message: str) -> HTTPException:
    return _api_error(status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", message)


def _short_error(error: Exception) -> str:
    if isinstance(error, HTTPException):
        detail = error.detail
        if isinstance(detail, dict) and isinstance(detail.get("message"), str):
            return detail["message"][:500]
    message = str(error).strip()
    return message[:500] if message else "Diagnostic request failed."


def _record_provider_diagnostic(
    db: Session,
    *,
    provider_kind: str,
    provider: str,
    model: str,
    configured: bool,
    ok: bool,
    latency_ms: int,
    message: str,
    dimension: int | None = None,
    response_preview: str | None = None,
    error_message: str | None = None,
) -> ProviderDiagnosticRun:
    run = ProviderDiagnosticRun(
        provider_kind=provider_kind,
        provider=provider,
        model=model,
        configured=configured,
        ok=ok,
        latency_ms=max(0, latency_ms),
        message=message[:500],
        dimension=dimension,
        response_preview=response_preview[:200] if response_preview else None,
        error_message=error_message[:500] if error_message else None,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run


def record_embedding_provider_failure(db: Session, error: Exception, *, latency_ms: int = 0) -> ProviderDiagnosticRun:
    try:
        info = get_embedding_provider().info
        provider = info.provider
        model = info.model
        configured = info.configured
    except Exception:
        provider = settings.embedding_provider
        model = settings.embedding_model
        configured = False
    message = _short_error(error)
    return _record_provider_diagnostic(
        db,
        provider_kind="embedding",
        provider=provider,
        model=model,
        configured=configured,
        ok=False,
        latency_ms=latency_ms,
        message=message,
        error_message=message,
    )


def record_llm_provider_failure(db: Session, error: Exception, *, latency_ms: int = 0) -> ProviderDiagnosticRun:
    try:
        info = get_chat_provider().info
        provider = info.provider
        model = info.model
        configured = info.configured
    except Exception:
        provider = settings.llm_provider
        model = settings.openai_model
        configured = False
    message = _short_error(error)
    return _record_provider_diagnostic(
        db,
        provider_kind="llm",
        provider=provider,
        model=model,
        configured=configured,
        ok=False,
        latency_ms=latency_ms,
        message=message,
        error_message=message,
    )


def record_provider_diagnostic_success(
    db: Session,
    *,
    provider_kind: str,
    diagnostic: ProviderDiagnostic,
) -> ProviderDiagnosticRun:
    return _record_provider_diagnostic(
        db,
        provider_kind=provider_kind,
        provider=diagnostic.provider,
        model=diagnostic.model,
        configured=diagnostic.configured,
        ok=diagnostic.ok,
        latency_ms=diagnostic.latency_ms,
        message=diagnostic.message,
        dimension=diagnostic.dimension,
        response_preview=diagnostic.response_preview,
    )


def _dashscope_embedding_model_looks_wrong() -> bool:
    base_url = settings.openai_base_url.lower()
    model = settings.embedding_model.lower()
    if "dashscope" not in base_url:
        return False
    if "embedding" in model or model.startswith("text-embedding"):
        return False
    return model.startswith("qwen")


def test_embedding_provider() -> ProviderDiagnostic:
    provider = get_embedding_provider()
    info = provider.info
    if info.provider == "openai" and not info.configured:
        raise _bad_request("OPENAI_API_KEY must be configured when EMBEDDING_PROVIDER=openai.")
    if _dashscope_embedding_model_looks_wrong():
        raise _bad_request(
            "DashScope embedding model appears to be a chat model. "
            "Set EMBEDDING_MODEL to an embedding model such as text-embedding-v4."
        )

    started = time.perf_counter()
    try:
        embeddings = provider.embed_texts(["WorkMemory provider diagnostic test."])
    except Exception as error:
        raise _bad_request(_short_error(error)) from error
    latency_ms = int((time.perf_counter() - started) * 1000)

    if not embeddings or not isinstance(embeddings[0], list):
        raise _bad_request("Embedding provider returned an invalid response shape.")
    dimension = len(embeddings[0])
    if dimension <= 0:
        raise _bad_request("Embedding provider returned an empty vector.")
    return ProviderDiagnostic(
        provider=info.provider,
        model=info.model,
        configured=info.configured,
        ok=True,
        dimension=dimension,
        latency_ms=latency_ms,
        message="Embedding provider test succeeded.",
    )


def test_llm_provider() -> ProviderDiagnostic:
    provider = get_chat_provider()
    info = provider.info
    if info.provider == "openai" and not info.configured:
        raise _bad_request("OPENAI_API_KEY must be configured when LLM_PROVIDER=openai.")

    started = time.perf_counter()
    try:
        result = provider.complete(
            [
                {"role": "system", "content": "Return a short provider diagnostic response."},
                {"role": "user", "content": "Reply with pong."},
            ]
        )
    except Exception as error:
        raise _bad_request(_short_error(error)) from error
    latency_ms = int((time.perf_counter() - started) * 1000)
    preview = " ".join(result.content.split())[:160]
    return ProviderDiagnostic(
        provider=result.provider,
        model=result.model,
        configured=info.configured,
        ok=True,
        latency_ms=latency_ms,
        response_preview=preview,
        message="LLM provider test succeeded.",
    )


def get_index_diagnostics(db: Session) -> dict:
    store = ChromaVectorStore(settings.chroma_collection_name)
    vector_count = store.count()
    collection_dimension = store.collection_dimension()
    indexed_document_count = db.execute(
        select(func.count())
        .select_from(DocumentEmbeddingResult)
        .where(DocumentEmbeddingResult.status == "indexed")
        .where(DocumentEmbeddingResult.vector_collection == settings.chroma_collection_name)
    ).scalar_one()
    dimensions = db.execute(
        select(DocumentEmbeddingResult.embedding_dimension)
        .where(DocumentEmbeddingResult.status == "indexed")
        .where(DocumentEmbeddingResult.vector_collection == settings.chroma_collection_name)
        .where(DocumentEmbeddingResult.embedding_dimension > 0)
        .distinct()
        .order_by(DocumentEmbeddingResult.embedding_dimension.asc())
    ).scalars().all()
    db_dimensions = [int(item) for item in dimensions]

    provider_rows = db.execute(
        select(
            DocumentEmbeddingResult.provider,
            DocumentEmbeddingResult.model,
            DocumentEmbeddingResult.status,
            func.count(),
        )
        .where(DocumentEmbeddingResult.vector_collection == settings.chroma_collection_name)
        .group_by(DocumentEmbeddingResult.provider, DocumentEmbeddingResult.model, DocumentEmbeddingResult.status)
        .order_by(DocumentEmbeddingResult.provider.asc(), DocumentEmbeddingResult.model.asc(), DocumentEmbeddingResult.status.asc())
    ).all()
    provider_model_counts = [
        {
            "provider": provider,
            "model": model,
            "status": status_value,
            "count": count,
        }
        for provider, model, status_value, count in provider_rows
    ]

    failures = db.execute(
        select(DocumentEmbeddingResult)
        .where(DocumentEmbeddingResult.status == "failed")
        .where(DocumentEmbeddingResult.vector_collection == settings.chroma_collection_name)
        .order_by(DocumentEmbeddingResult.updated_at.desc())
        .limit(8)
    ).scalars().all()
    recent_failures = [
        {
            "document_id": failure.document_id,
            "provider": failure.provider,
            "model": failure.model,
            "error_message": failure.error_message,
            "updated_at": failure.updated_at,
        }
        for failure in failures
    ]

    warning: str | None = None
    if len(db_dimensions) > 1:
        warning = "Indexed DB metadata contains mixed embedding dimensions."
    elif collection_dimension is not None and db_dimensions and collection_dimension not in db_dimensions:
        warning = "Chroma collection dimension does not match DB embedding metadata."

    return {
        "status": "warning" if warning else "ok",
        "collection_name": settings.chroma_collection_name,
        "persist_path": str(settings.chroma_path),
        "vector_count": vector_count,
        "collection_dimension": collection_dimension,
        "indexed_document_count": indexed_document_count,
        "db_embedding_dimensions": db_dimensions,
        "provider_model_counts": provider_model_counts,
        "recent_failures": recent_failures,
        "warning": warning,
    }


def list_index_collections(db: Session) -> dict:
    ChromaVectorStore(settings.chroma_collection_name)
    names = ChromaVectorStore.list_collection_names()
    if settings.chroma_collection_name not in names:
        names.append(settings.chroma_collection_name)

    items: list[dict] = []
    for name in sorted(set(names)):
        store = ChromaVectorStore(name)
        indexed_document_count = db.execute(
            select(func.count())
            .select_from(DocumentEmbeddingResult)
            .where(DocumentEmbeddingResult.status == "indexed")
            .where(DocumentEmbeddingResult.vector_collection == name)
        ).scalar_one()
        items.append(
            {
                "name": name,
                "vector_count": store.count(),
                "dimension": store.collection_dimension(),
                "indexed_document_count": indexed_document_count,
                "is_current": name == settings.chroma_collection_name,
            }
        )

    return {
        "items": items,
        "total": len(items),
    }


def get_provider_diagnostic_history(
    db: Session,
    *,
    provider_kind: str | None = None,
    limit: int = 20,
) -> dict:
    if provider_kind and provider_kind not in {"embedding", "llm"}:
        raise _bad_request("Invalid provider diagnostic kind.")
    query = select(ProviderDiagnosticRun)
    if provider_kind:
        query = query.where(ProviderDiagnosticRun.provider_kind == provider_kind)
    items = list(
        db.execute(
            query.order_by(ProviderDiagnosticRun.created_at.desc()).limit(max(1, min(limit, 100)))
        ).scalars().all()
    )
    return {
        "items": items,
        "total": len(items),
    }


def reset_current_index(
    db: Session,
    *,
    confirm: str,
    collection_name: str,
    clear_embedding_results: bool,
) -> dict:
    if confirm != "RESET_INDEX":
        raise _bad_request("Index reset confirmation is invalid.")

    active_count = db.execute(
        select(func.count())
        .select_from(DocumentPipelineJob)
        .where(
            (
                (DocumentPipelineJob.status == "running")
                | (
                    (DocumentPipelineJob.status == "queued")
                    & (DocumentPipelineJob.next_run_at <= datetime.now(timezone.utc))
                )
            )
            & or_(
                DocumentPipelineJob.error_message.is_(None),
                DocumentPipelineJob.error_message != RECOVERED_MESSAGE,
            )
        )
    ).scalar_one()
    if active_count:
        raise _bad_request("Cannot reset index while pipeline jobs are queued or running.")

    store = ChromaVectorStore(collection_name)
    store.reset_collection()

    deleted_count = 0
    if clear_embedding_results:
        deleted_count = db.execute(
            select(func.count())
            .select_from(DocumentEmbeddingResult)
            .where(DocumentEmbeddingResult.vector_collection == collection_name)
        ).scalar_one()
        db.execute(delete(DocumentEmbeddingResult).where(DocumentEmbeddingResult.vector_collection == collection_name))
        db.commit()

    return {
        "collection_name": collection_name,
        "vectors_deleted": True,
        "embedding_results_deleted": int(deleted_count),
    }
