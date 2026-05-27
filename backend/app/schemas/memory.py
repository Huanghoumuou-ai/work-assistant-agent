from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class MemoryCreate(BaseModel):
    project_id: str | None = None
    type: str
    title: str
    content: str
    occurred_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class MemoryUpdate(BaseModel):
    project_id: str | None = None
    type: str | None = None
    title: str | None = None
    content: str | None = None
    occurred_at: datetime | None = None

    model_config = ConfigDict(extra="forbid")


class MemoryStatusUpdate(BaseModel):
    status: str

    model_config = ConfigDict(extra="forbid")


class MemoryOut(BaseModel):
    id: str
    project_id: str | None
    project_name: str | None
    type: str
    title: str
    content: str
    status: str
    source_type: str
    source_ref: str | None
    occurred_at: datetime | None
    created_at: datetime
    updated_at: datetime


class MemoryListOut(BaseModel):
    items: list[MemoryOut]
    total: int
    limit: int
    offset: int


class MemorySearchRequest(BaseModel):
    query: str
    limit: int | None = None
    project_id: str | None = None
    types: list[str] | None = None
    include_archived: bool = False

    model_config = ConfigDict(extra="forbid")


class MemorySearchItemOut(BaseModel):
    rank: int
    score: float
    matched_fields: list[str]
    memory: MemoryOut


class MemorySearchOut(BaseModel):
    query: str
    items: list[MemorySearchItemOut]


class MemorySuggestionCreateFromConversation(BaseModel):
    conversation_id: str
    limit: int | None = None

    model_config = ConfigDict(extra="forbid")


class MemorySuggestionCreateFromDocument(BaseModel):
    document_id: str
    limit: int | None = None
    include_memory: bool = True

    model_config = ConfigDict(extra="forbid")


class MemorySuggestionCreateFromText(BaseModel):
    content: str
    title: str | None = None
    project_id: str | None = None
    limit: int | None = None
    include_memory: bool = True

    model_config = ConfigDict(extra="forbid")


class MemorySuggestionOut(BaseModel):
    id: str
    conversation_id: str | None
    project_id: str | None
    project_name: str | None
    type: str
    title: str
    content: str
    rationale: str | None
    status: str
    source_type: str
    source_ref: str | None
    memory_id: str | None
    created_at: datetime
    reviewed_at: datetime | None
    updated_at: datetime


class MemorySuggestionListOut(BaseModel):
    items: list[MemorySuggestionOut]
    total: int
    limit: int
    offset: int


class MemorySuggestionBatchOut(BaseModel):
    items: list[MemorySuggestionOut]
    total: int


class MemorySuggestionAcceptOut(BaseModel):
    suggestion: MemorySuggestionOut
    memory: MemoryOut
