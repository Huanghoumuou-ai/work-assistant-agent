from __future__ import annotations

from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.health import health_check
from backend.app.api.router import api_router
from backend.app.core.config import settings
from backend.app.db.init_db import init_db
from backend.app.services.pipeline_service import recover_stale_pipeline_jobs, start_pipeline_worker


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    try:
        recover_stale_pipeline_jobs()
    except Exception:
        logger.exception("Pipeline startup recovery failed.")
    start_pipeline_worker()
    yield


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.get("/health")(health_check)
app.include_router(api_router, prefix="/api")
