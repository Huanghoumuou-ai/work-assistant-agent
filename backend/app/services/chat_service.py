from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from json import JSONDecodeError
from typing import Iterator

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from backend.app.db.models import Conversation, ConversationSummary, Message
from backend.app.schemas.chat import ChatResponseOut, ConversationListOut, ConversationMessagesOut, ConversationOut, MessageOut
from backend.app.schemas.rag import RagSearchOut
from backend.app.schemas.rag import MemorySourceOut, RagSourceOut
from backend.app.services.conversation_summary_service import build_conversation_context, maybe_auto_refresh_summary
from backend.app.services.rag_service import answer_rag, prepare_rag_generation


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


def _clean_optional_id(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _title_from_query(query: str) -> str:
    title = " ".join(query.split())
    if len(title) <= 60:
        return title
    return title[:60].rstrip()


def _validate_conversation_title(title: str) -> str:
    clean = " ".join(title.split())
    if not clean:
        raise _bad_request("title is required.")
    if len(clean) > 120:
        raise _bad_request("title is too long.")
    return clean


def _safe_rag_source(value: object) -> RagSourceOut | None:
    if not isinstance(value, dict):
        return None
    try:
        return RagSourceOut.model_validate(value)
    except Exception:
        return None


def _safe_memory_source(value: object) -> MemorySourceOut | None:
    if not isinstance(value, dict):
        return None
    try:
        return MemorySourceOut.model_validate(value)
    except Exception:
        return None


def _parse_sources_json(value: str | None) -> tuple[list[RagSourceOut], list[MemorySourceOut]]:
    if not value:
        return [], []
    try:
        raw_sources = json.loads(value)
    except (JSONDecodeError, TypeError):
        return [], []

    if isinstance(raw_sources, list):
        document_sources = [
            source
            for source in (_safe_rag_source(item) for item in raw_sources)
            if source is not None
        ]
        return document_sources, []

    if isinstance(raw_sources, dict) and raw_sources.get("version") == 2:
        raw_documents = raw_sources.get("documents", [])
        raw_memories = raw_sources.get("memories", [])
        if not isinstance(raw_documents, list) or not isinstance(raw_memories, list):
            return [], []
        document_sources = [
            source
            for source in (_safe_rag_source(item) for item in raw_documents)
            if source is not None
        ]
        memory_sources = [
            source
            for source in (_safe_memory_source(item) for item in raw_memories)
            if source is not None
        ]
        return document_sources, memory_sources

    return [], []


def _message_out(message: Message) -> MessageOut:
    sources, memory_sources = _parse_sources_json(message.sources_json)

    return MessageOut(
        id=message.id,
        conversation_id=message.conversation_id,
        role=message.role,
        content=message.content,
        sources=sources,
        memory_sources=memory_sources,
        provider=message.provider,
        model=message.model,
        created_at=message.created_at,
    )


def post_chat(
    db: Session,
    *,
    conversation_id: str | None,
    query: str,
    top_k: int | None = None,
    project_id: str | None = None,
    document_id: str | None = None,
    include_memory: bool = False,
    memory_limit: int | None = None,
    auto_summary: bool = False,
) -> ChatResponseOut:
    clean_query = query.strip()
    if not clean_query:
        raise _bad_request("query is required.")

    clean_conversation_id = _clean_optional_id(conversation_id)
    clean_project_id = _clean_optional_id(project_id)
    clean_document_id = _clean_optional_id(document_id)
    conversation = db.get(Conversation, clean_conversation_id) if clean_conversation_id else None
    if clean_conversation_id and conversation is None:
        raise _not_found("Conversation not found.")
    conversation_context = build_conversation_context(db, conversation.id) if conversation is not None else None

    try:
        rag_result = answer_rag(
            db,
            query=clean_query,
            top_k=top_k,
            project_id=clean_project_id,
            document_id=clean_document_id,
            include_memory=include_memory,
            memory_limit=memory_limit,
            conversation_context=conversation_context,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as error:
        db.rollback()
        logger.exception("Chat answer generation failed.")
        raise _bad_request("Chat answer generation failed.") from error

    return save_chat_turn(
        db,
        conversation=conversation,
        query=clean_query,
        project_id=clean_project_id,
        rag_result=rag_result,
        auto_summary=auto_summary,
    )


def _sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _stream_no_evidence_answer(answer: str) -> Iterator[str]:
    chunk_size = 12
    for index in range(0, len(answer), chunk_size):
        yield answer[index : index + chunk_size]


def stream_chat_events(
    db: Session,
    *,
    conversation_id: str | None,
    query: str,
    top_k: int | None = None,
    project_id: str | None = None,
    document_id: str | None = None,
    include_memory: bool = False,
    memory_limit: int | None = None,
    auto_summary: bool = False,
) -> Iterator[str]:
    clean_query = query.strip()
    if not clean_query:
        yield _sse_event("error", {"code": "BAD_REQUEST", "message": "query is required."})
        return

    clean_conversation_id = _clean_optional_id(conversation_id)
    clean_project_id = _clean_optional_id(project_id)
    clean_document_id = _clean_optional_id(document_id)
    conversation = db.get(Conversation, clean_conversation_id) if clean_conversation_id else None
    if clean_conversation_id and conversation is None:
        yield _sse_event("error", {"code": "NOT_FOUND", "message": "Conversation not found."})
        return

    conversation_context = build_conversation_context(db, conversation.id) if conversation is not None else None

    try:
        context = prepare_rag_generation(
            db,
            query=clean_query,
            top_k=top_k,
            project_id=clean_project_id,
            document_id=clean_document_id,
            include_memory=include_memory,
            memory_limit=memory_limit,
            conversation_context=conversation_context,
        )
        yield _sse_event(
            "sources",
            {
                "sources": [source.model_dump(mode="json") for source in context.sources],
                "memory_sources": [source.model_dump(mode="json") for source in context.memory_sources],
                "provider": context.provider_info.provider,
                "model": context.provider_info.model,
            },
        )

        answer_parts: list[str] = []
        if context.no_evidence_answer is not None:
            for delta in _stream_no_evidence_answer(context.no_evidence_answer):
                answer_parts.append(delta)
                yield _sse_event("token", {"delta": delta})
        else:
            for delta in context.provider.stream_complete(context.messages):
                answer_parts.append(delta)
                yield _sse_event("token", {"delta": delta})

        answer = "".join(answer_parts).strip()
        if not answer:
            raise _bad_request("LLM response content is empty.")

        rag_result = RagSearchOut(
            answer=answer,
            sources=context.sources,
            memory_sources=context.memory_sources,
            model=context.provider_info.model,
            provider=context.provider_info.provider,
            query_used=context.retrieval_query,
            query_rewritten=context.query_rewritten,
            usage=None,
        )
        saved = save_chat_turn(
            db,
            conversation=conversation,
            query=clean_query,
            project_id=clean_project_id,
            rag_result=rag_result,
            auto_summary=auto_summary,
        )
        yield _sse_event("done", saved.model_dump(mode="json"))
    except HTTPException as error:
        db.rollback()
        detail = error.detail if isinstance(error.detail, dict) else {}
        yield _sse_event(
            "error",
            {
                "code": detail.get("code", "BAD_REQUEST"),
                "message": detail.get("message", "Chat request failed."),
            },
        )
    except Exception as error:
        db.rollback()
        logger.exception("Streaming chat generation failed.")
        yield _sse_event("error", {"code": "BAD_REQUEST", "message": "Streaming chat generation failed."})


def save_chat_turn(
    db: Session,
    *,
    conversation: Conversation | None,
    query: str,
    project_id: str | None,
    rag_result: RagSearchOut,
    auto_summary: bool,
) -> ChatResponseOut:
    now = datetime.now(timezone.utc)
    assistant_created_at = now + timedelta(microseconds=1)
    try:
        if conversation is None:
            conversation = Conversation(
                title=_title_from_query(query),
                project_id=project_id,
                created_at=now,
                updated_at=assistant_created_at,
            )
            db.add(conversation)
            db.flush()
        else:
            conversation.updated_at = assistant_created_at

        user_message = Message(
            conversation_id=conversation.id,
            role="user",
            content=query,
            sources_json=None,
            provider=None,
            model=None,
            created_at=now,
        )
        assistant_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=rag_result.answer,
            sources_json=json.dumps(
                {
                    "version": 2,
                    "documents": [source.model_dump(mode="json") for source in rag_result.sources],
                    "memories": [source.model_dump(mode="json") for source in rag_result.memory_sources],
                },
                ensure_ascii=False,
            ),
            provider=rag_result.provider,
            model=rag_result.model,
            created_at=assistant_created_at,
        )
        db.add_all([user_message, assistant_message])
        db.commit()
        db.refresh(conversation)
        db.refresh(user_message)
        db.refresh(assistant_message)
    except Exception:
        db.rollback()
        raise

    summary = maybe_auto_refresh_summary(db, conversation.id, requested=auto_summary)

    return ChatResponseOut(
        conversation=ConversationOut.model_validate(conversation),
        user_message=_message_out(user_message),
        assistant_message=_message_out(assistant_message),
        summary=summary,
    )


def save_regenerated_assistant_turn(
    db: Session,
    *,
    conversation: Conversation,
    user_message: Message,
    rag_result: RagSearchOut,
    auto_summary: bool,
) -> ChatResponseOut:
    now = datetime.now(timezone.utc)
    try:
        conversation.updated_at = now
        assistant_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            content=rag_result.answer,
            sources_json=json.dumps(
                {
                    "version": 2,
                    "documents": [source.model_dump(mode="json") for source in rag_result.sources],
                    "memories": [source.model_dump(mode="json") for source in rag_result.memory_sources],
                },
                ensure_ascii=False,
            ),
            provider=rag_result.provider,
            model=rag_result.model,
            created_at=now,
        )
        db.add(assistant_message)
        db.commit()
        db.refresh(conversation)
        db.refresh(user_message)
        db.refresh(assistant_message)
    except Exception:
        db.rollback()
        raise

    summary = maybe_auto_refresh_summary(db, conversation.id, requested=auto_summary)

    return ChatResponseOut(
        conversation=ConversationOut.model_validate(conversation),
        user_message=_message_out(user_message),
        assistant_message=_message_out(assistant_message),
        summary=summary,
    )


def list_conversations(db: Session, *, limit: int, offset: int) -> ConversationListOut:
    total = db.execute(select(func.count()).select_from(Conversation)).scalar_one()
    items = db.execute(
        select(Conversation)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    ).scalars().all()
    return ConversationListOut(
        items=[ConversationOut.model_validate(item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_conversation(db: Session, conversation_id: str) -> ConversationOut:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise _not_found("Conversation not found.")
    return ConversationOut.model_validate(conversation)


def update_conversation_title(db: Session, conversation_id: str, title: str) -> ConversationOut:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise _not_found("Conversation not found.")
    conversation.title = _validate_conversation_title(title)
    conversation.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(conversation)
    return ConversationOut.model_validate(conversation)


def delete_conversation(db: Session, conversation_id: str) -> str:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise _not_found("Conversation not found.")
    try:
        db.execute(delete(ConversationSummary).where(ConversationSummary.conversation_id == conversation_id))
        db.execute(delete(Message).where(Message.conversation_id == conversation_id))
        db.delete(conversation)
        db.commit()
    except Exception:
        db.rollback()
        raise
    return conversation_id


def regenerate_latest_assistant(
    db: Session,
    *,
    conversation_id: str,
    top_k: int | None = None,
    project_id: str | None = None,
    document_id: str | None = None,
    include_memory: bool = False,
    memory_limit: int | None = None,
    auto_summary: bool = False,
) -> ChatResponseOut:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise _not_found("Conversation not found.")

    messages = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    ).scalars().all()
    if not messages:
        raise _bad_request("Conversation has no messages.")

    last_user_index = next((index for index in range(len(messages) - 1, -1, -1) if messages[index].role == "user"), None)
    if last_user_index is None:
        raise _bad_request("Conversation has no user message to regenerate.")
    user_message = messages[last_user_index]

    trailing_messages = messages[last_user_index + 1 :]
    if trailing_messages and any(message.role != "assistant" for message in trailing_messages):
        raise _bad_request("Only the latest assistant response can be regenerated.")

    try:
        for message in trailing_messages:
            db.delete(message)
        if trailing_messages:
            db.commit()
    except Exception:
        db.rollback()
        raise

    conversation_context = build_conversation_context(db, conversation.id)
    clean_project_id = _clean_optional_id(project_id) or conversation.project_id
    clean_document_id = _clean_optional_id(document_id)
    try:
        rag_result = answer_rag(
            db,
            query=user_message.content,
            top_k=top_k,
            project_id=clean_project_id,
            document_id=clean_document_id,
            include_memory=include_memory,
            memory_limit=memory_limit,
            conversation_context=conversation_context,
        )
    except HTTPException:
        db.rollback()
        raise
    except Exception as error:
        db.rollback()
        logger.exception("Chat answer regeneration failed.")
        raise _bad_request("Chat answer regeneration failed.") from error

    return save_regenerated_assistant_turn(
        db,
        conversation=conversation,
        user_message=user_message,
        rag_result=rag_result,
        auto_summary=auto_summary,
    )


def get_conversation_messages(db: Session, conversation_id: str) -> ConversationMessagesOut:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise _not_found("Conversation not found.")
    messages = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    ).scalars().all()
    return ConversationMessagesOut(
        conversation=ConversationOut.model_validate(conversation),
        messages=[_message_out(message) for message in messages],
    )
