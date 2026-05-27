from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class RagSearchRequest(BaseModel):
    query: str
    top_k: int | None = None
    project_id: str | None = None
    document_id: str | None = None
    include_memory: bool = False
    memory_limit: int | None = None


class RagSourceOut(BaseModel):
    source_id: str
    rank: int
    document_id: str
    chunk_id: str
    chunk_index: int
    source_filename: str
    project_id: str | None
    uploaded_at: datetime
    char_start: int
    char_end: int
    score: float
    distance: float
    excerpt: str


class MemorySourceOut(BaseModel):
    source_id: str
    rank: int
    memory_id: str
    project_id: str | None
    project_name: str | None
    type: str
    title: str
    content: str
    occurred_at: datetime | None
    score: float


class RagSearchOut(BaseModel):
    answer: str
    sources: list[RagSourceOut]
    memory_sources: list[MemorySourceOut] = Field(default_factory=list)
    model: str
    provider: str
    usage: dict[str, Any] | None = None
