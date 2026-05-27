from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.db.models import Memory, Project
from backend.app.schemas.memory import (
    MemoryCreate,
    MemoryListOut,
    MemoryOut,
    MemorySearchItemOut,
    MemorySearchOut,
    MemoryUpdate,
)


ALLOWED_MEMORY_TYPES = {"note", "requirement", "decision", "rule"}
ALLOWED_MEMORY_STATUSES = {"active", "archived"}
DEFAULT_MEMORY_SEARCH_LIMIT = 5
MAX_MEMORY_SEARCH_LIMIT = 20


@dataclass(frozen=True)
class MemorySearchParams:
    query: str
    limit: int | None = None
    project_id: str | None = None
    types: list[str] | None = None
    include_archived: bool = False
    include_global_project: bool = False


@dataclass(frozen=True)
class MemorySearchHit:
    rank: int
    score: float
    matched_fields: list[str]
    memory: Memory


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


def _clean_optional_id(value: str | None) -> str | None:
    if value is None:
        return None
    clean = value.strip()
    return clean or None


def _require_trimmed(value: str, *, field: str, max_length: int) -> str:
    clean = value.strip()
    if not clean:
        raise _bad_request(f"{field} is required.")
    if len(clean) > max_length:
        raise _bad_request(f"{field} is too long.")
    return clean


def _validate_type(value: str) -> str:
    clean = value.strip()
    if clean not in ALLOWED_MEMORY_TYPES:
        raise _bad_request("Invalid memory type.")
    return clean


def _validate_types(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    clean_types: list[str] = []
    for value in values:
        clean_types.append(_validate_type(value))
    return clean_types


def _validate_status(value: str) -> str:
    clean = value.strip()
    if clean not in ALLOWED_MEMORY_STATUSES:
        raise _bad_request("Invalid memory status.")
    return clean


def _normalize_occurred_at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _ensure_project(db: Session, project_id: str | None) -> Project | None:
    clean_project_id = _clean_optional_id(project_id)
    if clean_project_id is None:
        return None
    project = db.get(Project, clean_project_id)
    if project is None:
        raise _bad_request("project_id does not exist.")
    return project


def memory_payload(db: Session, memory: Memory) -> MemoryOut:
    project = db.get(Project, memory.project_id) if memory.project_id else None
    return MemoryOut(
        id=memory.id,
        project_id=memory.project_id,
        project_name=project.name if project is not None else None,
        type=memory.type,
        title=memory.title,
        content=memory.content,
        status=memory.status,
        source_type=memory.source_type,
        source_ref=memory.source_ref,
        occurred_at=memory.occurred_at,
        created_at=memory.created_at,
        updated_at=memory.updated_at,
    )


def _validate_memory_search_limit(value: int | None) -> int:
    limit = DEFAULT_MEMORY_SEARCH_LIMIT if value is None else value
    if limit < 1:
        raise _bad_request("limit must be greater than 0.")
    if limit > MAX_MEMORY_SEARCH_LIMIT:
        raise _bad_request("limit exceeds maximum memory search limit.")
    return limit


def _search_terms(query: str) -> list[str]:
    tokens = [token for token in query.split() if token]
    use_full_query = len(tokens) <= 1 or any(ord(char) > 127 for char in query)
    if use_full_query and query not in tokens:
        tokens.append(query)
    return tokens


def _escape_like(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _memory_match_score(memory: Memory, terms: list[str]) -> tuple[float, list[str]]:
    title = memory.title.casefold()
    content = memory.content.casefold()
    matched_fields: list[str] = []
    score = 0.0

    for term in terms:
        clean_term = term.casefold()
        if clean_term in title:
            score += 10
            if "title" not in matched_fields:
                matched_fields.append("title")
        if clean_term in content:
            score += 3
            if "content" not in matched_fields:
                matched_fields.append("content")

    return score, matched_fields


def _memory_sort_time(memory: Memory) -> datetime:
    return memory.occurred_at or memory.created_at


def search_memory_hits(db: Session, params: MemorySearchParams) -> list[MemorySearchHit]:
    query = params.query.strip()
    if not query:
        raise _bad_request("query is required.")
    limit = _validate_memory_search_limit(params.limit)
    terms = _search_terms(query)
    memory_types = _validate_types(params.types)
    clean_project_id = _clean_optional_id(params.project_id)
    if clean_project_id is not None:
        _ensure_project(db, clean_project_id)

    statement = select(Memory)
    if params.include_archived:
        statement = statement.where(Memory.status.in_(["active", "archived"]))
    else:
        statement = statement.where(Memory.status == "active")

    if clean_project_id is not None:
        if params.include_global_project:
            statement = statement.where(or_(Memory.project_id == clean_project_id, Memory.project_id.is_(None)))
        else:
            statement = statement.where(Memory.project_id == clean_project_id)

    if memory_types:
        statement = statement.where(Memory.type.in_(memory_types))

    like_clauses = []
    for term in terms:
        pattern = f"%{_escape_like(term.casefold())}%"
        like_clauses.append(func.lower(Memory.title).like(pattern, escape="\\"))
        like_clauses.append(func.lower(Memory.content).like(pattern, escape="\\"))
    statement = statement.where(or_(*like_clauses))

    candidates = db.execute(statement).scalars().all()
    hits: list[MemorySearchHit] = []
    for memory in candidates:
        score, matched_fields = _memory_match_score(memory, terms)
        if score <= 0:
            continue
        hits.append(MemorySearchHit(rank=0, score=score, matched_fields=matched_fields, memory=memory))

    hits.sort(
        key=lambda hit: (
            hit.score,
            _memory_sort_time(hit.memory),
            hit.memory.created_at,
        ),
        reverse=True,
    )
    return [replace(hit, rank=rank) for rank, hit in enumerate(hits[:limit], start=1)]


def search_memories(db: Session, params: MemorySearchParams) -> MemorySearchOut:
    clean_query = params.query.strip()
    hits = search_memory_hits(db, params)
    return MemorySearchOut(
        query=clean_query,
        items=[
            MemorySearchItemOut(
                rank=hit.rank,
                score=hit.score,
                matched_fields=hit.matched_fields,
                memory=memory_payload(db, hit.memory),
            )
            for hit in hits
        ],
    )


def create_memory(db: Session, payload: MemoryCreate) -> Memory:
    project = _ensure_project(db, payload.project_id)
    memory = Memory(
        project_id=project.id if project is not None else None,
        type=_validate_type(payload.type),
        title=_require_trimmed(payload.title, field="title", max_length=120),
        content=_require_trimmed(payload.content, field="content", max_length=5000),
        status="active",
        source_type="manual",
        source_ref=None,
        occurred_at=_normalize_occurred_at(payload.occurred_at),
    )
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


def get_memory(db: Session, memory_id: str) -> Memory:
    memory = db.get(Memory, memory_id)
    if memory is None:
        raise _not_found("Memory not found.")
    return memory


def update_memory(db: Session, memory_id: str, payload: MemoryUpdate) -> Memory:
    memory = get_memory(db, memory_id)
    fields = payload.model_fields_set

    if "project_id" in fields:
        project = _ensure_project(db, payload.project_id)
        memory.project_id = project.id if project is not None else None
    if "type" in fields:
        if payload.type is None:
            raise _bad_request("type is required.")
        memory.type = _validate_type(payload.type)
    if "title" in fields:
        if payload.title is None:
            raise _bad_request("title is required.")
        memory.title = _require_trimmed(payload.title, field="title", max_length=120)
    if "content" in fields:
        if payload.content is None:
            raise _bad_request("content is required.")
        memory.content = _require_trimmed(payload.content, field="content", max_length=5000)
    if "occurred_at" in fields:
        memory.occurred_at = _normalize_occurred_at(payload.occurred_at)

    db.commit()
    db.refresh(memory)
    return memory


def update_memory_status(db: Session, memory_id: str, new_status: str) -> Memory:
    memory = get_memory(db, memory_id)
    memory.status = _validate_status(new_status)
    db.commit()
    db.refresh(memory)
    return memory


def list_memories(
    db: Session,
    *,
    limit: int,
    offset: int,
    project_id: str | None = None,
    type_filter: str | None = None,
    status_filter: str | None = None,
) -> MemoryListOut:
    query = select(Memory)
    count_query = select(func.count()).select_from(Memory)

    clean_project_id = _clean_optional_id(project_id)
    if clean_project_id is not None:
        _ensure_project(db, clean_project_id)
        query = query.where(Memory.project_id == clean_project_id)
        count_query = count_query.where(Memory.project_id == clean_project_id)

    if type_filter:
        memory_type = _validate_type(type_filter)
        query = query.where(Memory.type == memory_type)
        count_query = count_query.where(Memory.type == memory_type)

    clean_status = status_filter.strip() if status_filter else "active"
    if clean_status == "all":
        pass
    elif clean_status in ALLOWED_MEMORY_STATUSES:
        query = query.where(Memory.status == clean_status)
        count_query = count_query.where(Memory.status == clean_status)
    else:
        raise _bad_request("Invalid memory status filter.")

    total = db.execute(count_query).scalar_one()
    sort_time = func.coalesce(Memory.occurred_at, Memory.created_at)
    items = db.execute(
        query.order_by(sort_time.desc(), Memory.created_at.desc()).limit(limit).offset(offset)
    ).scalars().all()
    return MemoryListOut(
        items=[memory_payload(db, item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )
