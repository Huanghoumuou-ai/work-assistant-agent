from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.models import Document, DocumentChunk, DocumentChunkResult, DocumentParseResult
from backend.app.services.parse_service import safe_parsed_file_path


logger = logging.getLogger(__name__)
CLEANER_NAME = "deterministic-text-cleaner"
CLEANER_VERSION = "1"
CHUNKER_NAME = "character-boundary-chunker"
CHUNKER_VERSION = "1"
CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
EXCESS_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class PreparedChunk:
    content: str
    char_start: int
    char_end: int


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


def _validate_chunk_config() -> tuple[int, int, int]:
    max_chunk_chars = settings.max_chunk_chars
    overlap_chars = settings.chunk_overlap_chars
    max_chunks = settings.max_chunks_per_document

    if max_chunk_chars <= 0:
        raise _bad_request("MAX_CHUNK_CHARS must be greater than 0.")
    if overlap_chars < 0:
        raise _bad_request("CHUNK_OVERLAP_CHARS must be greater than or equal to 0.")
    if overlap_chars >= max_chunk_chars:
        raise _bad_request("CHUNK_OVERLAP_CHARS must be less than MAX_CHUNK_CHARS.")
    if max_chunks <= 0:
        raise _bad_request("MAX_CHUNKS_PER_DOCUMENT must be greater than 0.")
    return max_chunk_chars, overlap_chars, max_chunks


def clean_text(text: str) -> str:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = CONTROL_CHARS.sub("", normalized)
    normalized = "\n".join(line.rstrip() for line in normalized.split("\n"))
    normalized = EXCESS_BLANK_LINES.sub("\n\n", normalized)
    return normalized.strip()


def _trim_chunk_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _find_chunk_end(text: str, start: int, hard_end: int, max_chunk_chars: int) -> int:
    if hard_end >= len(text):
        return len(text)

    min_end = start + max(1, int(max_chunk_chars * 0.6))
    separators = ("\n\n", "\n", ".", "!", "?", ";")
    best_position = -1
    best_length = 1
    for separator in separators:
        position = text.rfind(separator, min_end, hard_end)
        if position > best_position:
            best_position = position
            best_length = len(separator)

    if best_position >= min_end:
        return best_position + best_length
    return hard_end


def split_text_into_chunks(text: str, max_chunk_chars: int, overlap_chars: int, max_chunks: int) -> tuple[list[PreparedChunk], bool]:
    chunks: list[PreparedChunk] = []
    start = 0
    truncated = False

    while start < len(text):
        hard_end = min(len(text), start + max_chunk_chars)
        end = _find_chunk_end(text, start, hard_end, max_chunk_chars)
        if end <= start:
            end = hard_end

        content_start, content_end = _trim_chunk_bounds(text, start, end)
        if content_start < content_end:
            chunks.append(
                PreparedChunk(
                    content=text[content_start:content_end],
                    char_start=content_start,
                    char_end=content_end,
                )
            )
            if len(chunks) >= max_chunks and end < len(text):
                truncated = True
                break

        if end >= len(text):
            break

        next_start = max(0, end - overlap_chars)
        if next_start <= start:
            next_start = end
        start = next_start

    return chunks, truncated


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _read_parsed_text(path) -> str:
    with path.open("r", encoding="utf-8", newline="") as file:
        return file.read()


def _short_error(error: Exception) -> str:
    if isinstance(error, HTTPException):
        detail = error.detail
        if isinstance(detail, dict) and isinstance(detail.get("message"), str):
            return detail["message"][:500]
    return "Document chunking failed."


def _get_document_and_parse_result(db: Session, document_id: str) -> tuple[Document, DocumentParseResult]:
    document = db.get(Document, document_id)
    if document is None:
        raise _not_found("Document not found.")
    if document.status != "uploaded":
        raise _bad_request("Archived documents cannot be chunked.")

    parse_result = db.get(DocumentParseResult, document_id)
    if parse_result is None or parse_result.status != "parsed":
        raise _bad_request("Document must be parsed before chunking.")
    if not parse_result.content_sha256:
        raise _bad_request("Parsed content hash is missing.")
    return document, parse_result


def _upsert_failed_result(
    db: Session,
    document_id: str,
    parse_content_sha256: str,
    max_chunk_chars: int,
    overlap_chars: int,
    error_message: str,
) -> DocumentChunkResult:
    now = datetime.now(timezone.utc)
    result = db.get(DocumentChunkResult, document_id)
    if result is None:
        result = DocumentChunkResult(
            document_id=document_id,
            status="failed",
            parse_content_sha256=parse_content_sha256,
            max_chunk_chars=max_chunk_chars,
            overlap_chars=overlap_chars,
        )
        db.add(result)

    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
    result.status = "failed"
    result.parse_content_sha256 = parse_content_sha256
    result.cleaner_name = None
    result.cleaner_version = None
    result.chunker_name = None
    result.chunker_version = None
    result.chunk_count = 0
    result.max_chunk_chars = max_chunk_chars
    result.overlap_chars = overlap_chars
    result.truncated = False
    result.error_message = error_message[:500]
    result.chunked_at = now
    db.commit()
    db.refresh(result)
    return result


def _write_chunk_result(
    db: Session,
    document_id: str,
    parse_content_sha256: str,
    prepared_chunks: list[PreparedChunk],
    max_chunk_chars: int,
    overlap_chars: int,
    truncated: bool,
) -> DocumentChunkResult:
    now = datetime.now(timezone.utc)
    result = db.get(DocumentChunkResult, document_id)
    if result is None:
        result = DocumentChunkResult(
            document_id=document_id,
            status="chunked",
            parse_content_sha256=parse_content_sha256,
            max_chunk_chars=max_chunk_chars,
            overlap_chars=overlap_chars,
        )
        db.add(result)

    db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))

    metadata = json.dumps(
        {
            "source": "parsed_text",
            "cleaner_name": CLEANER_NAME,
            "cleaner_version": CLEANER_VERSION,
            "chunker_name": CHUNKER_NAME,
            "chunker_version": CHUNKER_VERSION,
        },
        ensure_ascii=False,
    )
    for index, prepared in enumerate(prepared_chunks):
        db.add(
            DocumentChunk(
                document_id=document_id,
                chunk_index=index,
                content=prepared.content,
                content_sha256=_sha256_text(prepared.content),
                char_start=prepared.char_start,
                char_end=prepared.char_end,
                char_count=len(prepared.content),
                metadata_json=metadata,
            )
        )

    result.status = "chunked"
    result.parse_content_sha256 = parse_content_sha256
    result.cleaner_name = CLEANER_NAME
    result.cleaner_version = CLEANER_VERSION
    result.chunker_name = CHUNKER_NAME
    result.chunker_version = CHUNKER_VERSION
    result.chunk_count = len(prepared_chunks)
    result.max_chunk_chars = max_chunk_chars
    result.overlap_chars = overlap_chars
    result.truncated = truncated
    result.error_message = None
    result.chunked_at = now

    db.commit()
    db.refresh(result)
    return result


def chunk_document(db: Session, document_id: str) -> DocumentChunkResult:
    document, parse_result = _get_document_and_parse_result(db, document_id)
    existing = db.get(DocumentChunkResult, document_id)
    if (
        existing is not None
        and existing.status == "chunked"
        and existing.parse_content_sha256 == parse_result.content_sha256
    ):
        return existing

    max_chunk_chars, overlap_chars, max_chunks = _validate_chunk_config()

    parsed_path = safe_parsed_file_path(parse_result)
    if parsed_path is None:
        raise _bad_request("Parsed file path is missing.")

    try:
        if not parsed_path.exists():
            raise _bad_request("Parsed file is missing.")

        parsed_text = _read_parsed_text(parsed_path)
        if _sha256_text(parsed_text) != parse_result.content_sha256:
            raise _bad_request("Parsed content checksum does not match the parse result.")

        cleaned_text = clean_text(parsed_text)
        prepared_chunks, truncated = split_text_into_chunks(
            cleaned_text,
            max_chunk_chars=max_chunk_chars,
            overlap_chars=overlap_chars,
            max_chunks=max_chunks,
        )
        return _write_chunk_result(
            db,
            document_id=document.id,
            parse_content_sha256=parse_result.content_sha256,
            prepared_chunks=prepared_chunks,
            max_chunk_chars=max_chunk_chars,
            overlap_chars=overlap_chars,
            truncated=truncated,
        )
    except HTTPException as error:
        db.rollback()
        logger.exception("Document chunking failed: document_id=%s", document.id)
        failed = _upsert_failed_result(
            db,
            document_id=document.id,
            parse_content_sha256=parse_result.content_sha256,
            max_chunk_chars=max_chunk_chars,
            overlap_chars=overlap_chars,
            error_message=_short_error(error),
        )
        raise _bad_request(failed.error_message or "Document chunking failed.")
    except Exception as error:
        db.rollback()
        logger.exception("Document chunking failed: document_id=%s", document.id)
        failed = _upsert_failed_result(
            db,
            document_id=document.id,
            parse_content_sha256=parse_result.content_sha256,
            max_chunk_chars=max_chunk_chars,
            overlap_chars=overlap_chars,
            error_message=_short_error(error),
        )
        raise _bad_request(failed.error_message or "Document chunking failed.")


def get_document_chunks(db: Session, document_id: str) -> tuple[DocumentChunkResult, list[DocumentChunk]]:
    document = db.get(Document, document_id)
    if document is None:
        raise _not_found("Document not found.")

    result = db.get(DocumentChunkResult, document_id)
    if result is None:
        raise _not_found("Chunk result not found.")

    chunks = db.execute(
        select(DocumentChunk)
        .where(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index.asc())
    ).scalars().all()
    return result, list(chunks)


def get_chunk_content(db: Session, chunk_id: str) -> DocumentChunk:
    chunk = db.get(DocumentChunk, chunk_id)
    if chunk is None:
        raise _not_found("Chunk not found.")

    document = db.get(Document, chunk.document_id)
    if document is None:
        raise _not_found("Document not found.")
    if document.status != "uploaded":
        raise _bad_request("Archived document chunks cannot be viewed.")

    result = db.get(DocumentChunkResult, chunk.document_id)
    if result is None or result.status != "chunked":
        raise _bad_request("Document is not currently chunked.")
    return chunk


def list_chunks(
    db: Session,
    *,
    document_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[DocumentChunk], int]:
    query = select(DocumentChunk)
    count_query = select(func.count()).select_from(DocumentChunk)

    if document_id:
        query = query.where(DocumentChunk.document_id == document_id)
        count_query = count_query.where(DocumentChunk.document_id == document_id)

    total = db.execute(count_query).scalar_one()
    items = db.execute(
        query.order_by(DocumentChunk.document_id.asc(), DocumentChunk.chunk_index.asc()).limit(limit).offset(offset)
    ).scalars().all()
    return list(items), total
