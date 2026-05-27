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
