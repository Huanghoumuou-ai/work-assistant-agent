from __future__ import annotations

from pydantic import BaseModel


class RetrievalSearchRequest(BaseModel):
    query: str
    top_k: int | None = None
    project_id: str | None = None
    document_id: str | None = None


class RetrievalHitOut(BaseModel):
    rank: int
    document_id: str
    chunk_id: str
    chunk_index: int
    score: float
    distance: float
    source_filename: str
    project_id: str | None
    char_start: int
    char_end: int
    content_sha256: str
    parse_content_sha256: str
    chunk_set_sha256: str
    provider: str
    model: str


class RetrievalSearchOut(BaseModel):
    query: str
    top_k: int
    items: list[RetrievalHitOut]
