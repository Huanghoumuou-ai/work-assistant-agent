from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.app.dependencies import get_db
from backend.app.schemas.retrieval import RetrievalSearchRequest
from backend.app.services.retrieval_service import RetrievalSearchParams, search_retrieval


router = APIRouter()


@router.post("/retrieval/search")
async def post_retrieval_search(payload: RetrievalSearchRequest, db: Session = Depends(get_db)) -> dict:
    result = search_retrieval(
        db,
        RetrievalSearchParams(
            query=payload.query,
            top_k=payload.top_k,
            project_id=payload.project_id,
            document_id=payload.document_id,
        ),
    )
    return {
        "success": True,
        "code": "OK",
        "message": "Retrieval results loaded.",
        "data": result.model_dump(mode="json"),
    }
