from __future__ import annotations

from fastapi import APIRouter

from backend.app.api.chat import router as chat_router
from backend.app.api.documents import router as documents_router
from backend.app.api.health import health_check
from backend.app.api.memory import router as memory_router
from backend.app.api.placeholders import router as placeholder_router
from backend.app.api.projects import router as projects_router
from backend.app.api.rag import router as rag_router
from backend.app.api.retrieval import router as retrieval_router
from backend.app.api.settings import router as settings_router


api_router = APIRouter()
api_router.add_api_route("/health", health_check, methods=["GET"])
api_router.include_router(settings_router, prefix="/settings")
api_router.include_router(documents_router)
api_router.include_router(projects_router)
api_router.include_router(retrieval_router)
api_router.include_router(rag_router)
api_router.include_router(chat_router)
api_router.include_router(memory_router)
api_router.include_router(placeholder_router)
