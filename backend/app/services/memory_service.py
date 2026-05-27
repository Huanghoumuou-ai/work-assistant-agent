from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from json import JSONDecodeError

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from backend.app.db.models import Conversation, Document, DocumentParseResult, Memory, MemorySuggestion, Message, Project
from backend.app.schemas.memory import (
    MemoryCreate,
    MemoryListOut,
    MemoryOut,
    MemorySearchItemOut,
    MemorySearchOut,
    MemorySuggestionAcceptOut,
    MemorySuggestionBatchOut,
    MemorySuggestionListOut,
    MemorySuggestionOut,
    MemoryUpdate,
)
from backend.app.services.llm_provider import get_chat_provider
from backend.app.services.parse_service import safe_parsed_file_path


ALLOWED_MEMORY_TYPES = {"note", "requirement", "decision", "rule"}
ALLOWED_MEMORY_STATUSES = {"active", "archived"}
ALLOWED_SUGGESTION_STATUSES = {"pending", "accepted", "rejected"}
DEFAULT_MEMORY_SEARCH_LIMIT = 5
MAX_MEMORY_SEARCH_LIMIT = 20
DEFAULT_SUGGESTION_LIMIT = 5
MAX_SUGGESTION_LIMIT = 10


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


def suggestion_payload(db: Session, suggestion: MemorySuggestion) -> MemorySuggestionOut:
    project = db.get(Project, suggestion.project_id) if suggestion.project_id else None
    return MemorySuggestionOut(
        id=suggestion.id,
        conversation_id=suggestion.conversation_id,
        project_id=suggestion.project_id,
        project_name=project.name if project is not None else None,
        type=suggestion.type,
        title=suggestion.title,
        content=suggestion.content,
        rationale=suggestion.rationale,
        status=suggestion.status,
        source_type=suggestion.source_type,
        source_ref=suggestion.source_ref,
        memory_id=suggestion.memory_id,
        created_at=suggestion.created_at,
        reviewed_at=suggestion.reviewed_at,
        updated_at=suggestion.updated_at,
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


def _conversation_or_error(db: Session, conversation_id: str) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise _not_found("Conversation not found.")
    return conversation


def _conversation_lines(db: Session, conversation_id: str) -> list[str]:
    messages = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    ).scalars().all()
    return [f"{message.role}: {' '.join(message.content.split())}" for message in messages]


def _suggestion_limit(value: int | None) -> int:
    limit = DEFAULT_SUGGESTION_LIMIT if value is None else value
    if limit < 1:
        raise _bad_request("limit must be greater than 0.")
    if limit > MAX_SUGGESTION_LIMIT:
        raise _bad_request("limit exceeds maximum memory suggestion limit.")
    return limit


def _build_suggestion_messages(lines: list[str], limit: int, *, source_label: str = "conversation", memory_context: str = "") -> list[dict[str, str]]:
    transcript = "\n".join(lines[-80:])
    return [
        {
            "role": "system",
            "content": (
                "Suggest practical work-helping long-term memory candidates from the provided local knowledge context. "
                "Useful candidates include durable requirements, decisions, rules, constraints, recurring risks, and important project facts. "
                "Return only a JSON array. Each item must include type, title, content, and rationale. "
                "type must be one of note, requirement, decision, rule. "
                f"Return at most {limit} items. Do not include secrets, credentials, API keys, or transient chatter. "
                "Do not invent facts not supported by the provided context."
            ),
        },
        {"role": "user", "content": f"Source: {source_label}\n\nExisting active memory context:\n{memory_context}\n\nContent:\n{transcript}"},
    ]


def _parse_suggestion_items(raw: str, limit: int) -> list[dict[str, str]]:
    try:
        parsed = json.loads(raw)
    except (JSONDecodeError, TypeError):
        raise _bad_request("Memory suggestion response was not valid JSON.")
    if not isinstance(parsed, list):
        raise _bad_request("Memory suggestion response must be a JSON array.")
    items: list[dict[str, str]] = []
    for item in parsed[:limit]:
        if not isinstance(item, dict):
            continue
        memory_type = str(item.get("type") or "").strip()
        title = str(item.get("title") or "").strip()
        content = str(item.get("content") or "").strip()
        rationale = str(item.get("rationale") or "").strip()
        if memory_type not in ALLOWED_MEMORY_TYPES or not title or not content:
            continue
        items.append(
            {
                "type": memory_type,
                "title": title[:120],
                "content": content[:5000],
                "rationale": rationale[:500] if rationale else "",
            }
        )
    return items


def _ensure_suggestion_provider():
    provider = get_chat_provider()
    provider_info = provider.info
    if provider_info.provider == "openai" and not provider_info.configured:
        raise _bad_request("OPENAI_API_KEY must be configured when LLM_PROVIDER=openai.")
    return provider


def generate_memory_suggestions_from_conversation(db: Session, conversation_id: str, limit: int | None = None) -> MemorySuggestionBatchOut:
    conversation = _conversation_or_error(db, conversation_id)
    suggestion_limit = _suggestion_limit(limit)
    lines = _conversation_lines(db, conversation_id)
    if not lines:
        raise _bad_request("Conversation has no messages.")

    provider = _ensure_suggestion_provider()

    try:
        memory_context = _active_memory_context(db, conversation.project_id)
        completion = provider.complete(_build_suggestion_messages(lines, suggestion_limit, source_label="conversation", memory_context=memory_context))
        items = _parse_suggestion_items(completion.content, suggestion_limit)
    except HTTPException:
        raise
    except Exception as error:
        raise _bad_request("Memory suggestion generation failed.") from error

    now = datetime.now(timezone.utc)
    suggestions: list[MemorySuggestion] = []
    for item in items:
        suggestion = MemorySuggestion(
            conversation_id=conversation.id,
            project_id=conversation.project_id,
            type=item["type"],
            title=item["title"],
            content=item["content"],
            rationale=item["rationale"] or None,
            status="pending",
            source_type="chat_suggestion",
            source_ref=conversation.id,
            created_at=now,
            updated_at=now,
        )
        db.add(suggestion)
        suggestions.append(suggestion)
    db.commit()
    for suggestion in suggestions:
        db.refresh(suggestion)
    return MemorySuggestionBatchOut(items=[suggestion_payload(db, item) for item in suggestions], total=len(suggestions))


def _active_memory_context(db: Session, project_id: str | None) -> str:
    statement = select(Memory).where(Memory.status == "active")
    if project_id:
        statement = statement.where(or_(Memory.project_id == project_id, Memory.project_id.is_(None)))
    else:
        statement = statement.where(Memory.project_id.is_(None))
    memories = db.execute(statement.order_by(Memory.updated_at.desc()).limit(20)).scalars().all()
    lines = []
    remaining = 4000
    for memory in memories:
        line = f"- [{memory.type}] {memory.title}: {' '.join(memory.content.split())}"
        if len(line) > remaining:
            break
        lines.append(line)
        remaining -= len(line)
    return "\n".join(lines)


def _document_text_for_suggestions(document: Document, parse_result: DocumentParseResult) -> str:
    parsed_path = safe_parsed_file_path(parse_result)
    if parsed_path is None:
        raise _bad_request("Parsed file path is missing.")
    if not parsed_path.exists():
        raise _bad_request("Parsed file is missing.")
    text = parsed_path.read_text(encoding="utf-8")
    content_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if content_sha256 != parse_result.content_sha256:
        raise _bad_request("Parsed document checksum does not match parse result.")
    if not text.strip():
        raise _bad_request("Parsed document text is empty.")
    return text[:12000]


def generate_memory_suggestions_from_document(
    db: Session,
    document_id: str,
    *,
    limit: int | None = None,
    include_memory: bool = True,
) -> MemorySuggestionBatchOut:
    document = db.get(Document, document_id)
    if document is None:
        raise _not_found("Document not found.")
    if document.status != "uploaded":
        raise _bad_request("Archived documents cannot generate memory suggestions.")
    parse_result = db.get(DocumentParseResult, document_id)
    if parse_result is None or parse_result.status != "parsed":
        raise _bad_request("Document must be parsed before generating memory suggestions.")

    suggestion_limit = _suggestion_limit(limit)
    provider = _ensure_suggestion_provider()

    document_text = _document_text_for_suggestions(document, parse_result)
    memory_context = _active_memory_context(db, document.project_id) if include_memory else ""
    try:
        completion = provider.complete(
            _build_suggestion_messages(
                [document_text],
                suggestion_limit,
                source_label=f"document:{document.original_filename}",
                memory_context=memory_context,
            )
        )
        items = _parse_suggestion_items(completion.content, suggestion_limit)
    except HTTPException:
        raise
    except Exception as error:
        raise _bad_request("Memory suggestion generation failed.") from error

    now = datetime.now(timezone.utc)
    suggestions: list[MemorySuggestion] = []
    for item in items:
        suggestion = MemorySuggestion(
            conversation_id=None,
            project_id=document.project_id,
            type=item["type"],
            title=item["title"],
            content=item["content"],
            rationale=item["rationale"] or None,
            status="pending",
            source_type="document_suggestion",
            source_ref=document.id,
            created_at=now,
            updated_at=now,
        )
        db.add(suggestion)
        suggestions.append(suggestion)
    db.commit()
    for suggestion in suggestions:
        db.refresh(suggestion)
    return MemorySuggestionBatchOut(items=[suggestion_payload(db, item) for item in suggestions], total=len(suggestions))


def generate_memory_suggestions_from_text(
    db: Session,
    *,
    content: str,
    title: str | None = None,
    project_id: str | None = None,
    limit: int | None = None,
    include_memory: bool = True,
) -> MemorySuggestionBatchOut:
    clean_content = _require_trimmed(content, field="content", max_length=12000)
    clean_title = title.strip() if title else ""
    if len(clean_title) > 120:
        raise _bad_request("title is too long.")
    project = _ensure_project(db, project_id)
    clean_project_id = project.id if project is not None else None
    suggestion_limit = _suggestion_limit(limit)
    provider = _ensure_suggestion_provider()
    memory_context = _active_memory_context(db, clean_project_id) if include_memory else ""

    try:
        completion = provider.complete(
            _build_suggestion_messages(
                [clean_content],
                suggestion_limit,
                source_label=f"text:{clean_title or 'untitled'}",
                memory_context=memory_context,
            )
        )
        items = _parse_suggestion_items(completion.content, suggestion_limit)
    except HTTPException:
        raise
    except Exception as error:
        raise _bad_request("Memory suggestion generation failed.") from error

    now = datetime.now(timezone.utc)
    source_ref = clean_title[:100] if clean_title else None
    suggestions: list[MemorySuggestion] = []
    for item in items:
        suggestion = MemorySuggestion(
            conversation_id=None,
            project_id=clean_project_id,
            type=item["type"],
            title=item["title"],
            content=item["content"],
            rationale=item["rationale"] or None,
            status="pending",
            source_type="text_suggestion",
            source_ref=source_ref,
            created_at=now,
            updated_at=now,
        )
        db.add(suggestion)
        suggestions.append(suggestion)
    db.commit()
    for suggestion in suggestions:
        db.refresh(suggestion)
    return MemorySuggestionBatchOut(items=[suggestion_payload(db, item) for item in suggestions], total=len(suggestions))


def list_memory_suggestions(
    db: Session,
    *,
    limit: int,
    offset: int,
    status_filter: str | None = "pending",
) -> MemorySuggestionListOut:
    if status_filter and status_filter not in ALLOWED_SUGGESTION_STATUSES | {"all"}:
        raise _bad_request("Invalid memory suggestion status.")
    query = select(MemorySuggestion)
    count_query = select(func.count()).select_from(MemorySuggestion)
    if status_filter and status_filter != "all":
        query = query.where(MemorySuggestion.status == status_filter)
        count_query = count_query.where(MemorySuggestion.status == status_filter)
    total = db.execute(count_query).scalar_one()
    items = db.execute(query.order_by(MemorySuggestion.created_at.desc()).limit(limit).offset(offset)).scalars().all()
    return MemorySuggestionListOut(
        items=[suggestion_payload(db, item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def accept_memory_suggestion(db: Session, suggestion_id: str) -> MemorySuggestionAcceptOut:
    suggestion = db.get(MemorySuggestion, suggestion_id)
    if suggestion is None:
        raise _not_found("Memory suggestion not found.")
    if suggestion.status != "pending":
        raise _bad_request("Only pending memory suggestions can be accepted.")
    now = datetime.now(timezone.utc)
    memory = Memory(
        project_id=suggestion.project_id,
        type=_validate_type(suggestion.type),
        title=_require_trimmed(suggestion.title, field="title", max_length=120),
        content=_require_trimmed(suggestion.content, field="content", max_length=5000),
        status="active",
        source_type="suggestion",
        source_ref=suggestion.id,
        occurred_at=None,
    )
    db.add(memory)
    db.flush()
    suggestion.status = "accepted"
    suggestion.memory_id = memory.id
    suggestion.reviewed_at = now
    suggestion.updated_at = now
    db.commit()
    db.refresh(memory)
    db.refresh(suggestion)
    return MemorySuggestionAcceptOut(suggestion=suggestion_payload(db, suggestion), memory=memory_payload(db, memory))


def reject_memory_suggestion(db: Session, suggestion_id: str) -> MemorySuggestionOut:
    suggestion = db.get(MemorySuggestion, suggestion_id)
    if suggestion is None:
        raise _not_found("Memory suggestion not found.")
    if suggestion.status != "pending":
        raise _bad_request("Only pending memory suggestions can be rejected.")
    suggestion.status = "rejected"
    suggestion.reviewed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(suggestion)
    return suggestion_payload(db, suggestion)


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
