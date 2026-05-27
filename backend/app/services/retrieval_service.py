from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Document, DocumentChunk, DocumentEmbeddingResult, DocumentParseResult, Project
from backend.app.schemas.retrieval import RetrievalHitOut, RetrievalSearchOut
from backend.app.services.embedding_provider import get_embedding_provider
from backend.app.services.vector_store import ChromaVectorStore, VectorQueryHit


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalSearchParams:
    query: str
    top_k: int | None = None
    project_id: str | None = None
    document_id: str | None = None


@dataclass(frozen=True)
class RetrievalContextHit:
    rank: int
    document_id: str
    chunk_id: str
    chunk_index: int
    score: float
    distance: float
    source_filename: str
    project_id: str | None
    uploaded_at: datetime
    char_start: int
    char_end: int
    content_sha256: str
    parse_content_sha256: str
    chunk_set_sha256: str
    provider: str
    model: str
    content: str


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


def _clean_optional_id(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def validate_retrieval_top_k(value: int | None, *, default: int | None = None) -> int:
    top_k = settings.default_retrieval_top_k if value is None else value
    if value is None and default is not None:
        top_k = default
    if top_k < 1:
        raise _bad_request("top_k must be greater than 0.")
    if top_k > settings.max_retrieval_top_k:
        raise _bad_request("top_k exceeds MAX_RETRIEVAL_TOP_K.")
    return top_k


def _validate_retrieval_config() -> None:
    if settings.default_retrieval_top_k < 1:
        raise _bad_request("DEFAULT_RETRIEVAL_TOP_K must be greater than 0.")
    if settings.max_retrieval_top_k < 1:
        raise _bad_request("MAX_RETRIEVAL_TOP_K must be greater than 0.")
    if settings.default_retrieval_top_k > settings.max_retrieval_top_k:
        raise _bad_request("DEFAULT_RETRIEVAL_TOP_K must not exceed MAX_RETRIEVAL_TOP_K.")


def _metadata_filter(project_id: str | None, document_id: str | None) -> dict[str, Any] | None:
    filters: list[dict[str, str]] = []
    if document_id:
        filters.append({"document_id": document_id})
    if project_id:
        filters.append({"project_id": project_id})
    if not filters:
        return None
    if len(filters) == 1:
        return filters[0]
    return {"$and": filters}


def _metadata_string(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
    clean = str(value).strip()
    return clean or None


def _score(distance: float) -> float:
    return 1 / (1 + max(distance, 0))


def _validate_requested_entities(
    db: Session,
    *,
    project_id: str | None,
    document_id: str | None,
) -> bool:
    if project_id is not None and db.get(Project, project_id) is None:
        raise _bad_request("project_id does not exist.")

    if document_id is None:
        return True

    document = db.get(Document, document_id)
    if document is None:
        raise _bad_request("document_id does not exist.")
    return document.status == "uploaded"


def _validated_context_hit(
    db: Session,
    hit: VectorQueryHit,
    *,
    requested_project_id: str | None,
    requested_document_id: str | None,
) -> RetrievalContextHit | None:
    metadata = hit.metadata
    document_id = _metadata_string(metadata, "document_id")
    chunk_id = _metadata_string(metadata, "chunk_id")
    hit_chunk_set_sha256 = _metadata_string(metadata, "chunk_set_sha256")
    if document_id is None or chunk_id is None or hit_chunk_set_sha256 is None:
        return None

    if requested_document_id is not None and document_id != requested_document_id:
        return None

    document = db.get(Document, document_id)
    if document is None or document.status != "uploaded":
        return None
    if requested_project_id is not None and document.project_id != requested_project_id:
        return None

    chunk = db.get(DocumentChunk, chunk_id)
    if chunk is None or chunk.document_id != document.id:
        return None

    embedding_result = db.get(DocumentEmbeddingResult, document.id)
    if (
        embedding_result is None
        or embedding_result.status != "indexed"
        or embedding_result.chunk_set_sha256 != hit_chunk_set_sha256
    ):
        return None

    parse_result = db.get(DocumentParseResult, document.id)
    if parse_result is None or parse_result.content_sha256 is None:
        return None

    distance = float(hit.distance)
    return RetrievalContextHit(
        rank=0,
        document_id=document.id,
        chunk_id=chunk.id,
        chunk_index=chunk.chunk_index,
        score=_score(distance),
        distance=distance,
        source_filename=document.original_filename,
        project_id=document.project_id,
        uploaded_at=document.created_at,
        char_start=chunk.char_start,
        char_end=chunk.char_end,
        content_sha256=chunk.content_sha256,
        parse_content_sha256=parse_result.content_sha256,
        chunk_set_sha256=embedding_result.chunk_set_sha256,
        provider=embedding_result.provider,
        model=embedding_result.model,
        content=chunk.content,
    )


def search_retrieval_context(db: Session, params: RetrievalSearchParams, *, default_top_k: int | None = None) -> list[RetrievalContextHit]:
    _validate_retrieval_config()
    query = params.query.strip()
    if not query:
        raise _bad_request("query is required.")

    top_k = validate_retrieval_top_k(params.top_k, default=default_top_k)
    project_id = _clean_optional_id(params.project_id)
    document_id = _clean_optional_id(params.document_id)
    document_can_be_searched = _validate_requested_entities(
        db,
        project_id=project_id,
        document_id=document_id,
    )
    if not document_can_be_searched:
        return []

    provider = get_embedding_provider()
    provider_info = provider.info
    if provider_info.provider == "openai" and not provider_info.configured:
        raise _bad_request("OPENAI_API_KEY must be configured when EMBEDDING_PROVIDER=openai.")

    store = ChromaVectorStore(settings.chroma_collection_name)
    if store.count() == 0:
        return []

    try:
        embeddings = provider.embed_texts([query])
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Retrieval embedding failed.")
        raise _bad_request("Retrieval embedding failed.") from error
    if len(embeddings) != 1 or not embeddings[0]:
        raise _bad_request("Embedding provider returned an invalid query vector.")

    query_embedding = embeddings[0]
    collection_dimension = store.collection_dimension()
    if collection_dimension is not None and collection_dimension != len(query_embedding):
        raise _bad_request("Query embedding dimension does not match the Chroma collection.")

    overfetch = min(top_k * 3, settings.max_retrieval_top_k * 3)
    try:
        hits = store.query(
            embedding=query_embedding,
            n_results=overfetch,
            where=_metadata_filter(project_id, document_id),
        )
    except HTTPException:
        raise
    except Exception as error:
        logger.exception("Vector retrieval query failed.")
        raise _bad_request("Vector retrieval query failed.") from error

    items: list[RetrievalContextHit] = []
    for hit in hits:
        item = _validated_context_hit(
            db,
            hit,
            requested_project_id=project_id,
            requested_document_id=document_id,
        )
        if item is None:
            continue
        items.append(item)
        if len(items) >= top_k:
            break

    ranked_items = [
        replace(item, rank=rank)
        for rank, item in enumerate(items, start=1)
    ]
    return ranked_items


def search_retrieval(db: Session, params: RetrievalSearchParams) -> RetrievalSearchOut:
    query = params.query.strip()
    top_k = validate_retrieval_top_k(params.top_k)
    context_hits = search_retrieval_context(db, params)
    ranked_items = [
        RetrievalHitOut(
            rank=item.rank,
            document_id=item.document_id,
            chunk_id=item.chunk_id,
            chunk_index=item.chunk_index,
            score=item.score,
            distance=item.distance,
            source_filename=item.source_filename,
            project_id=item.project_id,
            char_start=item.char_start,
            char_end=item.char_end,
            content_sha256=item.content_sha256,
            parse_content_sha256=item.parse_content_sha256,
            chunk_set_sha256=item.chunk_set_sha256,
            provider=item.provider,
            model=item.model,
        )
        for item in context_hits
    ]
    return RetrievalSearchOut(query=query, top_k=top_k, items=ranked_items)
