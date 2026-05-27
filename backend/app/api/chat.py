from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from backend.app.dependencies import get_db
from backend.app.schemas.chat import ChatRequest, ConversationRegenerateRequest, ConversationUpdateRequest
from backend.app.services.conversation_summary_service import generate_conversation_summary, get_conversation_summary
from backend.app.services.chat_service import (
    delete_conversation,
    get_conversation,
    get_conversation_messages,
    list_conversations,
    post_chat,
    regenerate_latest_assistant,
    stream_chat_events,
    update_conversation_title,
)


router = APIRouter()


@router.post("/chat")
async def post_chat_api(payload: ChatRequest, db: Session = Depends(get_db)) -> dict:
    result = post_chat(
        db,
        conversation_id=payload.conversation_id,
        query=payload.query,
        top_k=payload.top_k,
        project_id=payload.project_id,
        document_id=payload.document_id,
        include_memory=payload.include_memory,
        memory_limit=payload.memory_limit,
        auto_summary=payload.auto_summary,
    )
    return {
        "success": True,
        "code": "OK",
        "message": "Chat response generated.",
        "data": result.model_dump(mode="json"),
    }


@router.post("/chat/stream")
async def post_chat_stream_api(payload: ChatRequest, db: Session = Depends(get_db)) -> StreamingResponse:
    return StreamingResponse(
        stream_chat_events(
            db,
            conversation_id=payload.conversation_id,
            query=payload.query,
            top_k=payload.top_k,
            project_id=payload.project_id,
            document_id=payload.document_id,
            include_memory=payload.include_memory,
            memory_limit=payload.memory_limit,
            auto_summary=payload.auto_summary,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/conversations")
async def get_conversations_api(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    db: Session = Depends(get_db),
) -> dict:
    result = list_conversations(db, limit=limit, offset=offset)
    return {
        "success": True,
        "code": "OK",
        "message": "Conversations loaded.",
        "data": result.model_dump(mode="json"),
    }


@router.get("/conversations/{conversation_id}")
async def get_conversation_api(conversation_id: str, db: Session = Depends(get_db)) -> dict:
    result = get_conversation(db, conversation_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Conversation loaded.",
        "data": result.model_dump(mode="json"),
    }


@router.patch("/conversations/{conversation_id}")
async def patch_conversation_api(conversation_id: str, payload: ConversationUpdateRequest, db: Session = Depends(get_db)) -> dict:
    result = update_conversation_title(db, conversation_id, payload.title)
    return {
        "success": True,
        "code": "OK",
        "message": "Conversation updated.",
        "data": result.model_dump(mode="json"),
    }


@router.delete("/conversations/{conversation_id}")
async def delete_conversation_api(conversation_id: str, db: Session = Depends(get_db)) -> dict:
    deleted_id = delete_conversation(db, conversation_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Conversation deleted.",
        "data": {"id": deleted_id},
    }


@router.post("/conversations/{conversation_id}/regenerate")
async def post_conversation_regenerate_api(conversation_id: str, payload: ConversationRegenerateRequest, db: Session = Depends(get_db)) -> dict:
    result = regenerate_latest_assistant(
        db,
        conversation_id=conversation_id,
        top_k=payload.top_k,
        project_id=payload.project_id,
        document_id=payload.document_id,
        include_memory=payload.include_memory,
        memory_limit=payload.memory_limit,
        auto_summary=payload.auto_summary,
    )
    return {
        "success": True,
        "code": "OK",
        "message": "Chat response regenerated.",
        "data": result.model_dump(mode="json"),
    }


@router.post("/conversations/{conversation_id}/summary")
async def post_conversation_summary_api(conversation_id: str, db: Session = Depends(get_db)) -> dict:
    result = generate_conversation_summary(db, conversation_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Conversation summary generated.",
        "data": result.model_dump(mode="json"),
    }


@router.get("/conversations/{conversation_id}/summary")
async def get_conversation_summary_api(conversation_id: str, db: Session = Depends(get_db)) -> dict:
    result = get_conversation_summary(db, conversation_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Conversation summary loaded.",
        "data": result.model_dump(mode="json"),
    }


@router.get("/conversations/{conversation_id}/messages")
async def get_conversation_messages_api(conversation_id: str, db: Session = Depends(get_db)) -> dict:
    result = get_conversation_messages(db, conversation_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Messages loaded.",
        "data": result.model_dump(mode="json"),
    }
