from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.dependencies import get_db
from backend.app.schemas.memory import MemoryCreate, MemorySearchRequest, MemoryStatusUpdate, MemoryUpdate
from backend.app.services.memory_service import (
    MemorySearchParams,
    create_memory,
    get_memory,
    list_memories,
    memory_payload,
    search_memories,
    update_memory,
    update_memory_status,
)


router = APIRouter()


@router.post("/memory")
async def post_memory(payload: MemoryCreate, db: Session = Depends(get_db)) -> dict:
    memory = create_memory(db, payload)
    return {
        "success": True,
        "code": "OK",
        "message": "Memory created.",
        "data": memory_payload(db, memory).model_dump(mode="json"),
    }


@router.get("/memory")
async def get_memories(
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
    project_id: str | None = None,
    type: str | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    result = list_memories(
        db,
        limit=limit,
        offset=offset,
        project_id=project_id,
        type_filter=type,
        status_filter=status,
    )
    return {
        "success": True,
        "code": "OK",
        "message": "Memories loaded.",
        "data": result.model_dump(mode="json"),
    }


@router.post("/memory/search")
async def post_memory_search(payload: MemorySearchRequest, db: Session = Depends(get_db)) -> dict:
    result = search_memories(
        db,
        MemorySearchParams(
            query=payload.query,
            limit=payload.limit,
            project_id=payload.project_id,
            types=payload.types,
            include_archived=payload.include_archived,
        ),
    )
    return {
        "success": True,
        "code": "OK",
        "message": "Memory search completed.",
        "data": result.model_dump(mode="json"),
    }


@router.get("/memory/{memory_id}")
async def get_memory_api(memory_id: str, db: Session = Depends(get_db)) -> dict:
    memory = get_memory(db, memory_id)
    return {
        "success": True,
        "code": "OK",
        "message": "Memory loaded.",
        "data": memory_payload(db, memory).model_dump(mode="json"),
    }


@router.patch("/memory/{memory_id}")
async def patch_memory(memory_id: str, payload: MemoryUpdate, db: Session = Depends(get_db)) -> dict:
    memory = update_memory(db, memory_id, payload)
    return {
        "success": True,
        "code": "OK",
        "message": "Memory updated.",
        "data": memory_payload(db, memory).model_dump(mode="json"),
    }


@router.patch("/memory/{memory_id}/status")
async def patch_memory_status(memory_id: str, payload: MemoryStatusUpdate, db: Session = Depends(get_db)) -> dict:
    memory = update_memory_status(db, memory_id, payload.status)
    return {
        "success": True,
        "code": "OK",
        "message": "Memory status updated.",
        "data": memory_payload(db, memory).model_dump(mode="json"),
    }
