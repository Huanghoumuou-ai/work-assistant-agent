from __future__ import annotations

from sqlalchemy.engine import Engine

from backend.app.core.runtime import ensure_runtime_dirs
from backend.app.db.migrations import initialize_database_with_migrations
from backend.app.db.session import engine


def init_db(bind: Engine | None = None) -> None:
    ensure_runtime_dirs()
    initialize_database_with_migrations(bind or engine)
