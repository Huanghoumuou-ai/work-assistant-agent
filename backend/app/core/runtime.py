from __future__ import annotations

from pathlib import Path

from backend.app.core.config import settings


def ensure_runtime_dirs() -> list[Path]:
    created_or_existing: list[Path] = []
    for directory in settings.runtime_dirs():
        directory.mkdir(parents=True, exist_ok=True)
        created_or_existing.append(directory)
    return created_or_existing
