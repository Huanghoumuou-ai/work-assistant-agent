from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.dependencies import get_db
from backend.app.schemas.rag import RagSearchRequest
from backend.app.services.rag_service import answer_rag


router = APIRouter()


@router.post("/rag/search")
async def post_rag_search(payload: RagSearchRequest, db: Session = Depends(get_db)) -> dict:
    result = answer_rag(
        db,
        query=payload.query,
        top_k=payload.top_k,
        project_id=payload.project_id,
        document_id=payload.document_id,
        include_memory=payload.include_memory,
        memory_limit=payload.memory_limit,
    )
    return {
        "success": True,
        "code": "OK",
        "message": "RAG answer generated.",
        "data": result.model_dump(mode="json"),
    }
