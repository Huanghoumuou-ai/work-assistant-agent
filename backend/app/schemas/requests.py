from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator
from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


class DocumentStatusUpdate(BaseModel):
    status: str


class TextDocumentCreate(BaseModel):
    title: str | None = None
    content: str
    project_id: str | None = None


class IndexResetRequest(BaseModel):
    confirm: str
    collection_name: str
    clear_embedding_results: bool = True


class PipelinePriorityUpdate(BaseModel):
    priority: int


class PipelineBatchActionRequest(BaseModel):
    job_ids: list[str] | None = Field(default=None, max_length=100)
    status: Literal["queued", "running", "failed", "canceled"] | None = None
    project_id: str | None = None

    @model_validator(mode="after")
    def require_selector(self) -> "PipelineBatchActionRequest":
        if not self.job_ids and not self.status:
            raise ValueError("Provide job_ids or status.")
        return self
