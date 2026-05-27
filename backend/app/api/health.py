from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text

from backend.app.core.config import settings
from backend.app.db.session import SessionLocal


def _database_ok() -> bool:
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def health_check() -> dict:
    return {
        "success": True,
        "code": "OK",
        "message": "Service is healthy.",
        "data": {
            "app_name": settings.app_name,
            "version": settings.app_version,
            "environment": settings.app_env,
            "database": {"ok": _database_ok()},
            "timestamp": datetime.now(timezone.utc).isoformat(),
        },
    }
