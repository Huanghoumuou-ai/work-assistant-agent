from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import PureWindowsPath
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.runtime import ensure_runtime_dirs
from backend.app.db.models import (
    Document,
    DocumentChunk,
    DocumentChunkResult,
    DocumentEmbeddingResult,
    DocumentParseResult,
    DocumentPipelineJob,
    DocumentPipelineJobEvent,
    Project,
)
from backend.app.services.index_service import delete_vectors_for_document
from backend.app.services.parse_service import safe_parsed_file_path


ALLOWED_EXTENSIONS = {".txt", ".md", ".pdf", ".docx", ".xlsx", ".xls", ".csv"}
ALLOWED_DOCUMENT_STATUSES = {"uploaded", "archived"}
CHUNK_SIZE = 1024 * 1024
CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")
logger = logging.getLogger(__name__)


def _raise_bad_request(message: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "success": False,
            "code": "BAD_REQUEST",
            "message": message,
            "data": None,
        },
    )


def _raise_not_found(message: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={
            "success": False,
            "code": "NOT_FOUND",
            "message": message,
            "data": None,
        },
    )


def _sanitize_original_filename(filename: str | None) -> str:
    if not filename:
        _raise_bad_request("Filename is required.")

    assert filename is not None
    if CONTROL_CHARS.search(filename):
        _raise_bad_request("Filename contains unsupported control characters.")
    if "/" in filename or "\\" in filename:
        _raise_bad_request("Filename must not include path separators.")

    windows_path = PureWindowsPath(filename)
    if windows_path.is_absolute() or windows_path.drive or windows_path.root:
        _raise_bad_request("Filename must not be an absolute path.")
    if any(part == ".." for part in windows_path.parts):
        _raise_bad_request("Filename must not include parent path segments.")

    cleaned = filename.strip()
    if not cleaned or cleaned in {".", ".."}:
        _raise_bad_request("Filename is invalid.")
    return cleaned[:255]


def _get_extension(filename: str) -> str:
    suffix = PureWindowsPath(filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        _raise_bad_request("Unsupported file extension.")
    return suffix


def _ensure_project_exists(db: Session, project_id: str | None) -> None:
    if not project_id:
        return
    project = db.get(Project, project_id)
    if project is None:
        _raise_bad_request("project_id does not exist.")


def _display_filename_from_title(title: str | None) -> str:
    clean_title = (title or "Pasted note").strip()
    clean_title = CONTROL_CHARS.sub(" ", clean_title)
    clean_title = clean_title.replace("/", " ").replace("\\", " ")
    clean_title = re.sub(r"\s+", " ", clean_title).strip(" .")
    if not clean_title:
        clean_title = "Pasted note"
    if not clean_title.lower().endswith((".md", ".txt")):
        clean_title = f"{clean_title}.md"
    return clean_title[:255]


async def save_uploaded_document(db: Session, upload: UploadFile, project_id: str | None = None) -> Document:
    ensure_runtime_dirs()
    _ensure_project_exists(db, project_id)

    original_filename = _sanitize_original_filename(upload.filename)
    extension = _get_extension(original_filename)

    document_id = str(uuid4())
    now = datetime.now(timezone.utc)
    relative_dir = f"files/{now:%Y/%m}"
    stored_filename = f"{document_id}{extension}"
    relative_path = f"{relative_dir}/{stored_filename}"
    target_dir = settings.data_path / relative_dir
    target_path = target_dir / stored_filename
    temp_path = target_dir / f"{stored_filename}.tmp"

    target_dir.mkdir(parents=True, exist_ok=True)
    sha256 = hashlib.sha256()
    size_bytes = 0

    try:
        with temp_path.open("wb") as output:
            while True:
                chunk = await upload.read(CHUNK_SIZE)
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > settings.max_upload_size_bytes:
                    _raise_bad_request("File exceeds maximum upload size.")
                sha256.update(chunk)
                output.write(chunk)

        if size_bytes == 0:
            _raise_bad_request("File is empty.")

        temp_path.replace(target_path)

        document = Document(
            id=document_id,
            project_id=project_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            relative_path=relative_path,
            extension=extension,
            mime_type=upload.content_type,
            size_bytes=size_bytes,
            sha256=sha256.hexdigest(),
            status="uploaded",
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        return document
    except HTTPException:
        db.rollback()
        temp_path.unlink(missing_ok=True)
        target_path.unlink(missing_ok=True)
        raise
    except Exception:
        db.rollback()
        temp_path.unlink(missing_ok=True)
        target_path.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def save_text_document(db: Session, *, content: str, title: str | None = None, project_id: str | None = None) -> Document:
    ensure_runtime_dirs()
    _ensure_project_exists(db, project_id)

    clean_content = content.strip()
    if not clean_content:
        _raise_bad_request("Text content is required.")

    raw_bytes = clean_content.encode("utf-8")
    size_bytes = len(raw_bytes)
    if size_bytes > settings.max_upload_size_bytes:
        _raise_bad_request("Text content exceeds maximum upload size.")

    document_id = str(uuid4())
    now = datetime.now(timezone.utc)
    extension = ".md"
    original_filename = _display_filename_from_title(title)
    stored_filename = f"{document_id}{extension}"
    relative_dir = f"files/{now:%Y/%m}"
    relative_path = f"{relative_dir}/{stored_filename}"
    target_dir = settings.data_path / relative_dir
    target_path = target_dir / stored_filename
    temp_path = target_dir / f"{stored_filename}.tmp"

    target_dir.mkdir(parents=True, exist_ok=True)
    try:
        with temp_path.open("wb") as output:
            output.write(raw_bytes)
        temp_path.replace(target_path)

        document = Document(
            id=document_id,
            project_id=project_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            relative_path=relative_path,
            extension=extension,
            mime_type="text/markdown",
            size_bytes=size_bytes,
            sha256=hashlib.sha256(raw_bytes).hexdigest(),
            status="uploaded",
        )
        db.add(document)
        db.commit()
        db.refresh(document)
        return document
    except HTTPException:
        db.rollback()
        temp_path.unlink(missing_ok=True)
        target_path.unlink(missing_ok=True)
        raise
    except Exception:
        db.rollback()
        temp_path.unlink(missing_ok=True)
        target_path.unlink(missing_ok=True)
        raise


def list_documents(
    db: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    project_id: str | None = None,
    status_filter: str | None = None,
) -> tuple[list[Document], int]:
    if status_filter and status_filter not in ALLOWED_DOCUMENT_STATUSES:
        _raise_bad_request("Invalid document status.")

    query = select(Document)
    count_query = select(func.count()).select_from(Document)

    if project_id:
        query = query.where(Document.project_id == project_id)
        count_query = count_query.where(Document.project_id == project_id)
    if status_filter:
        query = query.where(Document.status == status_filter)
        count_query = count_query.where(Document.status == status_filter)

    total = db.execute(count_query).scalar_one()
    items = db.execute(
        query.order_by(Document.created_at.desc()).limit(limit).offset(offset)
    ).scalars().all()
    return list(items), total


def update_document_status(db: Session, document_id: str, new_status: str) -> Document:
    if new_status not in ALLOWED_DOCUMENT_STATUSES:
        _raise_bad_request("Invalid document status.")

    document = db.get(Document, document_id)
    if document is None:
        _raise_not_found("Document not found.")

    document.status = new_status
    db.commit()
    db.refresh(document)
    return document


def _safe_document_file_path(document: Document):
    files_root = (settings.data_path / "files").resolve()
    target_path = (settings.data_path / document.relative_path).resolve()
    if not target_path.is_relative_to(files_root):
        logger.error(
            "Refusing to delete document file outside data/files: document_id=%s relative_path=%s resolved_path=%s",
            document.id,
            document.relative_path,
            target_path,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={
                "success": False,
                "code": "UNSAFE_FILE_PATH",
                "message": "Document file path is outside the files directory.",
                "data": None,
            },
        )
    return target_path


def delete_document(db: Session, document_id: str) -> str:
    document = db.get(Document, document_id)
    if document is None:
        _raise_not_found("Document not found.")

    target_path = _safe_document_file_path(document)
    parse_result = db.get(DocumentParseResult, document_id)
    parsed_path = safe_parsed_file_path(parse_result) if parse_result is not None else None
    staged_path = None
    staged_parsed_path = None

    try:
        delete_vectors_for_document(db, document_id)

        if target_path.exists():
            staged_path = target_path.with_name(f"{target_path.name}.deleting-{uuid4().hex}")
            target_path.replace(staged_path)
        if parsed_path is not None and parsed_path.exists():
            staged_parsed_path = parsed_path.with_name(f"{parsed_path.name}.deleting-{uuid4().hex}")
            parsed_path.replace(staged_parsed_path)

        db.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
        db.execute(delete(DocumentPipelineJobEvent).where(DocumentPipelineJobEvent.document_id == document_id))
        db.execute(delete(DocumentPipelineJob).where(DocumentPipelineJob.document_id == document_id))
        embedding_result = db.get(DocumentEmbeddingResult, document_id)
        if embedding_result is not None:
            db.delete(embedding_result)
        chunk_result = db.get(DocumentChunkResult, document_id)
        if chunk_result is not None:
            db.delete(chunk_result)
        if parse_result is not None:
            db.delete(parse_result)
        db.delete(document)
        db.commit()

        if staged_path is not None:
            staged_path.unlink(missing_ok=True)
        if staged_parsed_path is not None:
            staged_parsed_path.unlink(missing_ok=True)
        return document_id
    except Exception:
        db.rollback()
        if staged_path is not None and staged_path.exists() and not target_path.exists():
            staged_path.replace(target_path)
        if staged_parsed_path is not None and parsed_path is not None and staged_parsed_path.exists() and not parsed_path.exists():
            staged_parsed_path.replace(parsed_path)
        raise
