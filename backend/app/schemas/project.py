from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
