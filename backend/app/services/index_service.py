from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from json import JSONDecodeError

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import (
    Document,
    DocumentChunk,
    DocumentChunkResult,
    DocumentEmbeddingResult,
    DocumentParseResult,
)
from backend.app.services.embedding_provider import EmbeddingProvider, get_embedding_provider
from backend.app.services.vector_store import ChromaVectorStore, VectorRecord


logger = logging.getLogger(__name__)


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


def _not_found(message: str) -> HTTPException:
    return _api_error(status.HTTP_404_NOT_FOUND, "NOT_FOUND", message)


def _short_error(error: Exception) -> str:
    if isinstance(error, HTTPException):
        detail = error.detail
        if isinstance(detail, dict) and isinstance(detail.get("message"), str):
            return detail["message"][:500]
    return "Document indexing failed."


def _validate_batch_size() -> int:
    if settings.embedding_batch_size <= 0:
        raise _bad_request("EMBEDDING_BATCH_SIZE must be greater than 0.")
    return settings.embedding_batch_size


def compute_chunk_set_sha256(chunks: list[DocumentChunk]) -> str:
    digest = hashlib.sha256()
    for chunk in sorted(chunks, key=lambda item: item.chunk_index):
        parts = [
            chunk.id,
            chunk.content_sha256,
            str(chunk.chunk_index),
            str(chunk.char_start),
            str(chunk.char_end),
        ]
        digest.update("\x1f".join(parts).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def _get_index_inputs(db: Session, document_id: str) -> tuple[Document, DocumentParseResult, DocumentChunkResult, list[DocumentChunk]]:
    document = db.get(Document, document_id)
    if document is None:
        raise _not_found("Document not found.")
    if document.status != "uploaded":
        raise _bad_request("Archived documents cannot be indexed.")

    parse_result = db.get(DocumentParseResult, document_id)
    if parse_result is None or parse_result.status != "parsed" or not parse_result.content_sha256:
        raise _bad_request("Document must be parsed before indexing.")

    chunk_result = db.get(DocumentChunkResult, document_id)
    if chunk_result is None or chunk_result.status != "chunked":
        raise _bad_request("Document must be chunked before indexing.")

    chunks = db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
    ).scalars().all()
    return document, parse_result, chunk_result, list(chunks)


def _embedding_dimension(embeddings: list[list[float]]) -> int:
    if not embeddings:
        return 0
    dimension = len(embeddings[0])
    if dimension <= 0:
        raise _bad_request("Embedding dimension must be greater than 0.")
    if any(len(embedding) != dimension for embedding in embeddings):
        raise _bad_request("Embedding dimensions are inconsistent.")
    return dimension


def _existing_index_dimension(db: Session, vector_collection: str) -> int | None:
    dimensions = db.execute(
        select(DocumentEmbeddingResult.embedding_dimension)
        .where(DocumentEmbeddingResult.status == "indexed")
        .where(DocumentEmbeddingResult.vector_collection == vector_collection)
        .where(DocumentEmbeddingResult.embedding_dimension > 0)
        .distinct()
    ).scalars().all()
    unique = {int(item) for item in dimensions}
    if not unique:
        return None
    if len(unique) > 1:
        raise _bad_request("Existing embedding results contain mixed dimensions.")
    return next(iter(unique))


def _validate_collection_dimension(db: Session, store: ChromaVectorStore, embedding_dimension: int) -> None:
    if embedding_dimension <= 0:
        return
    collection_dimension = store.collection_dimension()
    if collection_dimension is not None and collection_dimension != embedding_dimension:
        raise _bad_request("Embedding dimension does not match the existing Chroma collection.")

    db_dimension = _existing_index_dimension(db, store.collection_name)
    if db_dimension is not None and db_dimension != embedding_dimension:
        raise _bad_request("Embedding dimension does not match existing indexed documents.")


def _parse_vector_ids(result: DocumentEmbeddingResult | None) -> list[str] | None:
    if result is None or not result.vector_ids_json:
        return None
    try:
        parsed = json.loads(result.vector_ids_json)
    except (JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        return None
    return parsed


def cleanup_vectors_for_result(store: ChromaVectorStore, result: DocumentEmbeddingResult | None, document_id: str) -> None:
    vector_ids = _parse_vector_ids(result)
    if vector_ids:
        store.delete_ids(vector_ids)
        return
    store.delete_document(document_id)


def delete_vectors_for_document(db: Session, document_id: str) -> None:
    result = db.get(DocumentEmbeddingResult, document_id)
    if result is None:
        return
    store = ChromaVectorStore(result.vector_collection or settings.chroma_collection_name)
    cleanup_vectors_for_result(store, result, document_id)


def _embed_all(provider: EmbeddingProvider, texts: list[str]) -> list[list[float]]:
    batch_size = _validate_batch_size()
    embeddings: list[list[float]] = []
    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        embeddings.extend(provider.embed_texts(batch))
    if len(embeddings) != len(texts):
        raise _bad_request("Embedding provider returned an unexpected number of vectors.")
    return embeddings


def _upsert_failed_result(
    db: Session,
    *,
    document_id: str,
    provider: str,
    model: str,
    chunk_set_sha256: str,
    vector_collection: str,
    error_message: str,
    embedding_dimension: int = 0,
) -> DocumentEmbeddingResult:
    now = datetime.now(timezone.utc)
    result = db.get(DocumentEmbeddingResult, document_id)
    if result is None:
        result = DocumentEmbeddingResult(
            document_id=document_id,
            status="failed",
            provider=provider,
            model=model,
            embedding_dimension=embedding_dimension,
            chunk_set_sha256=chunk_set_sha256,
            indexed_chunk_count=0,
            vector_collection=vector_collection,
        )
        db.add(result)

    result.status = "failed"
    result.provider = provider
    result.model = model
    result.embedding_dimension = embedding_dimension
    result.chunk_set_sha256 = chunk_set_sha256
    result.indexed_chunk_count = 0
    result.vector_collection = vector_collection
    result.vector_ids_json = None
    result.error_message = error_message[:500]
    result.indexed_at = now
    db.commit()
    db.refresh(result)
    return result


def _write_indexed_result(
    db: Session,
    *,
    document_id: str,
    provider: str,
    model: str,
    embedding_dimension: int,
    chunk_set_sha256: str,
    indexed_chunk_count: int,
    vector_collection: str,
    vector_ids: list[str],
) -> DocumentEmbeddingResult:
    now = datetime.now(timezone.utc)
    result = db.get(DocumentEmbeddingResult, document_id)
    if result is None:
        result = DocumentEmbeddingResult(
            document_id=document_id,
            status="indexed",
            provider=provider,
            model=model,
            embedding_dimension=embedding_dimension,
            chunk_set_sha256=chunk_set_sha256,
            indexed_chunk_count=indexed_chunk_count,
            vector_collection=vector_collection,
        )
        db.add(result)

    result.status = "indexed"
    result.provider = provider
    result.model = model
    result.embedding_dimension = embedding_dimension
    result.chunk_set_sha256 = chunk_set_sha256
    result.indexed_chunk_count = indexed_chunk_count
    result.vector_collection = vector_collection
    result.vector_ids_json = json.dumps(vector_ids)
    result.error_message = None
    result.indexed_at = now
    db.commit()
    db.refresh(result)
    return result


def _vector_records(
    *,
    document: Document,
    parse_result: DocumentParseResult,
    chunks: list[DocumentChunk],
    embeddings: list[list[float]],
    chunk_set_sha256: str,
    provider: str,
    model: str,
) -> list[VectorRecord]:
    records: list[VectorRecord] = []
    for chunk, embedding in zip(chunks, embeddings):
        vector_id = f"chunk:{chunk.id}"
        records.append(
            VectorRecord(
                id=vector_id,
                embedding=embedding,
                document=chunk.content,
                metadata={
                    "document_id": document.id,
                    "project_id": document.project_id,
                    "chunk_id": chunk.id,
                    "chunk_index": chunk.chunk_index,
                    "content_sha256": chunk.content_sha256,
                    "char_start": chunk.char_start,
                    "char_end": chunk.char_end,
                    "source_filename": document.original_filename,
                    "parse_content_sha256": parse_result.content_sha256,
                    "chunk_set_sha256": chunk_set_sha256,
                    "provider": provider,
                    "model": model,
                },
            )
        )
    return records


def index_document(db: Session, document_id: str) -> DocumentEmbeddingResult:
    document, parse_result, chunk_result, chunks = _get_index_inputs(db, document_id)
    provider = get_embedding_provider()
    provider_info = provider.info
    if provider_info.provider == "openai" and not provider_info.configured:
        raise _bad_request("OPENAI_API_KEY must be configured when EMBEDDING_PROVIDER=openai.")

    chunk_set_sha256 = compute_chunk_set_sha256(chunks)
    existing = db.get(DocumentEmbeddingResult, document_id)
    if (
        existing is not None
        and existing.status == "indexed"
        and existing.chunk_set_sha256 == chunk_set_sha256
        and existing.provider == provider_info.provider
        and existing.model == provider_info.model
    ):
        return existing

    vector_collection = settings.chroma_collection_name
    store = ChromaVectorStore(vector_collection)
    non_empty_chunks = [chunk for chunk in chunks if chunk.content]

    try:
        embeddings = _embed_all(provider, [chunk.content for chunk in non_empty_chunks])
        embedding_dimension = _embedding_dimension(embeddings)
        _validate_collection_dimension(db, store, embedding_dimension)
    except HTTPException as error:
        db.rollback()
        logger.exception("Document embedding failed before Chroma upsert: document_id=%s", document.id)
        failed = _upsert_failed_result(
            db,
            document_id=document.id,
            provider=provider_info.provider,
            model=provider_info.model,
            chunk_set_sha256=chunk_set_sha256,
            vector_collection=vector_collection,
            embedding_dimension=0,
            error_message=_short_error(error),
        )
        raise _bad_request(failed.error_message or "Document indexing failed.")
    except Exception as error:
        db.rollback()
        logger.exception("Document embedding failed before Chroma upsert: document_id=%s", document.id)
        failed = _upsert_failed_result(
            db,
            document_id=document.id,
            provider=provider_info.provider,
            model=provider_info.model,
            chunk_set_sha256=chunk_set_sha256,
            vector_collection=vector_collection,
            embedding_dimension=0,
            error_message=_short_error(error),
        )
        raise _bad_request(failed.error_message or "Document indexing failed.")

    records = _vector_records(
        document=document,
        parse_result=parse_result,
        chunks=non_empty_chunks,
        embeddings=embeddings,
        chunk_set_sha256=chunk_set_sha256,
        provider=provider_info.provider,
        model=provider_info.model,
    )
    vector_ids = [record.id for record in records]
    upserted = False

    try:
        cleanup_vectors_for_result(store, existing, document.id)
        store.upsert(records)
        upserted = bool(records)
    except Exception as error:
        db.rollback()
        logger.exception("Chroma indexing failed: document_id=%s", document.id)
        failed = _upsert_failed_result(
            db,
            document_id=document.id,
            provider=provider_info.provider,
            model=provider_info.model,
            chunk_set_sha256=chunk_set_sha256,
            vector_collection=vector_collection,
            embedding_dimension=embedding_dimension,
            error_message=_short_error(error),
        )
        raise _bad_request(failed.error_message or "Document indexing failed.")

    try:
        return _write_indexed_result(
            db,
            document_id=document.id,
            provider=provider_info.provider,
            model=provider_info.model,
            embedding_dimension=embedding_dimension,
            chunk_set_sha256=chunk_set_sha256,
            indexed_chunk_count=len(records),
            vector_collection=vector_collection,
            vector_ids=vector_ids,
        )
    except Exception as error:
        db.rollback()
        orphan_message = ""
        if upserted:
            try:
                store.delete_ids(vector_ids)
            except Exception:
                logger.exception("Failed to delete vectors after DB write failure: document_id=%s", document.id)
                orphan_message = " Possible orphan vectors may remain."
        error_message = f"{_short_error(error)}{orphan_message}"
        failed = _upsert_failed_result(
            db,
            document_id=document.id,
            provider=provider_info.provider,
            model=provider_info.model,
            chunk_set_sha256=chunk_set_sha256,
            vector_collection=vector_collection,
            embedding_dimension=embedding_dimension,
            error_message=error_message,
        )
        raise _bad_request(failed.error_message or "Document indexing failed.")


def get_index_result(db: Session, document_id: str) -> DocumentEmbeddingResult:
    document = db.get(Document, document_id)
    if document is None:
        raise _not_found("Document not found.")
    result = db.get(DocumentEmbeddingResult, document_id)
    if result is None:
        raise _not_found("Index result not found.")
    return result


def get_index_status(db: Session) -> dict:
    provider = get_embedding_provider()
    store = ChromaVectorStore(settings.chroma_collection_name)
    indexed_document_count = db.execute(
        select(func.count())
        .select_from(DocumentEmbeddingResult)
        .where(DocumentEmbeddingResult.status == "indexed")
    ).scalar_one()
    return {
        "provider_configured": provider.info.configured,
        "collection_name": settings.chroma_collection_name,
        "persist_path": str(settings.chroma_path),
        "indexed_document_count": indexed_document_count,
        "vector_count": store.count(),
    }
