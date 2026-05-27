from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.dependencies import get_db
from backend.app.db.models import Project
from backend.app.schemas.project import ProjectOut
from backend.app.schemas.requests import ProjectCreate
from backend.app.services.project_service import create_project


router = APIRouter()


@router.post("/projects")
async def post_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> dict:
    project = create_project(db, name=payload.name, description=payload.description)
    return {
        "success": True,
        "code": "OK",
        "message": "Project created.",
        "data": ProjectOut.model_validate(project).model_dump(mode="json"),
    }


@router.get("/projects")
async def get_projects(db: Session = Depends(get_db)) -> dict:
    projects = db.execute(select(Project).order_by(Project.created_at.desc())).scalars().all()
    return {
        "success": True,
        "code": "OK",
        "message": "Projects loaded.",
        "data": [ProjectOut.model_validate(project).model_dump(mode="json") for project in projects],
    }
