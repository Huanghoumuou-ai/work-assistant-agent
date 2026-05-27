from __future__ import annotations

import sys
from pathlib import Path
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.app.db.init_db import init_db
from backend.app.db.models import Project
from backend.app.db.session import SessionLocal


def main() -> int:
    init_db()

    project = Project(
        name=f"DB Check {uuid4().hex[:8]}",
        description="Created by backend/scripts/check_db.py",
    )

    with SessionLocal() as session:
        session.add(project)
        session.commit()
        session.refresh(project)
        count = session.query(Project).count()

    print("SQLite initialized successfully.")
    print(f"Inserted project: {project.id} {project.name}")
    print(f"Project count: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
