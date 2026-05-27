from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.db.models import Project


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "success": False,
            "code": code,
            "message": message,
            "data": None,
        },
    )


def create_project(db: Session, *, name: str, description: str | None = None) -> Project:
    clean_name = name.strip()
    if not clean_name:
        raise _error(status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", "Project name is required.")
    if len(clean_name) > 100:
        raise _error(status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", "Project name is too long.")

    clean_description = description.strip() if description is not None else None
    if clean_description == "":
        clean_description = None
    if clean_description is not None and len(clean_description) > 1000:
        raise _error(status.HTTP_400_BAD_REQUEST, "BAD_REQUEST", "Project description is too long.")

    existing = db.execute(select(Project).where(Project.name == clean_name)).scalar_one_or_none()
    if existing is not None:
        raise _error(status.HTTP_409_CONFLICT, "CONFLICT", "Project name already exists.")

    project = Project(name=clean_name, description=clean_description)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project
