from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from backend.app.schemas.rag import MemorySourceOut, RagSourceOut


class ChatRequest(BaseModel):
    conversation_id: str | None = None
    query: str
    top_k: int | None = None
    project_id: str | None = None
    document_id: str | None = None
    include_memory: bool = False
    memory_limit: int | None = None
    auto_summary: bool = False


class ConversationUpdateRequest(BaseModel):
    title: str


class ConversationRegenerateRequest(BaseModel):
    top_k: int | None = None
    project_id: str | None = None
    document_id: str | None = None
    include_memory: bool = False
    memory_limit: int | None = None
    auto_summary: bool = False


class ConversationOut(BaseModel):
    id: str
    title: str
    project_id: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConversationListOut(BaseModel):
    items: list[ConversationOut]
    total: int
    limit: int
    offset: int


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str
    sources: list[RagSourceOut]
    memory_sources: list[MemorySourceOut] = Field(default_factory=list)
    provider: str | None
    model: str | None
    created_at: datetime


class ConversationMessagesOut(BaseModel):
    conversation: ConversationOut
    messages: list[MessageOut]


class ConversationSummaryOut(BaseModel):
    conversation_id: str
    status: str
    summary: str | None
    message_count: int
    last_message_id: str | None
    provider: str | None
    model: str | None
    error_message: str | None
    generated_at: datetime | None
    created_at: datetime | None
    updated_at: datetime | None
    stale: bool
    new_message_count: int
    needs_refresh: bool


class ChatResponseOut(BaseModel):
    conversation: ConversationOut
    user_message: MessageOut
    assistant_message: MessageOut
    summary: ConversationSummaryOut | None = None
