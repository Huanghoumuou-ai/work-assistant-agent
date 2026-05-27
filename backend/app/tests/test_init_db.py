from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session

from backend.app.db import models  # noqa: F401
from backend.app.db.base import Base
from backend.app.db.init_db import init_db
from backend.app.db.migrations import alembic_config, migration_status, upgrade_head
from backend.app.db.models.project import Project


def test_init_db_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "workmemory_test.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    init_db(engine)
    init_db(engine)

    inspector = inspect(engine)
    assert "projects" in inspector.get_table_names()
    assert "alembic_version" in inspector.get_table_names()
    assert migration_status(engine)["up_to_date"] is True

    engine.dispose()


def test_init_db_creates_empty_database_with_alembic_version(tmp_path) -> None:
    db_path = tmp_path / "empty_workmemory.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    init_db(engine)

    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    assert "projects" in table_names
    assert "documents" in table_names
    assert "document_pipeline_jobs" in table_names
    assert "document_pipeline_job_events" in table_names
    assert "alembic_version" in table_names
    pipeline_columns = {column["name"] for column in inspector.get_columns("document_pipeline_jobs")}
    assert {"priority", "attempt_count", "locked_by", "lock_expires_at", "last_error_code"} <= pipeline_columns
    assert migration_status(engine)["up_to_date"] is True

    engine.dispose()


def test_alembic_migrates_phase_17_schema_to_phase_18(tmp_path) -> None:
    db_path = tmp_path / "phase17_to_phase18.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    config = alembic_config()
    config.attributes["configure_logger"] = False
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "20260507_0001")

    inspector = inspect(engine)
    assert "document_pipeline_job_events" not in inspector.get_table_names()

    upgrade_head(engine)

    inspector = inspect(engine)
    assert "document_pipeline_job_events" in inspector.get_table_names()
    pipeline_columns = {column["name"] for column in inspector.get_columns("document_pipeline_jobs")}
    assert {"priority", "attempt_count", "next_run_at", "locked_by", "heartbeat_at", "last_error_code"} <= pipeline_columns
    assert migration_status(engine)["up_to_date"] is True

    engine.dispose()


def test_init_db_stamps_existing_current_schema_without_deleting_data(tmp_path) -> None:
    db_path = tmp_path / "existing_current_schema.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(bind=engine)

    with Session(engine) as session:
        project = Project(name="Existing Project", description="keep me")
        session.add(project)
        session.commit()
        project_id = project.id

    assert "alembic_version" not in inspect(engine).get_table_names()

    init_db(engine)

    inspector = inspect(engine)
    assert "alembic_version" in inspector.get_table_names()
    assert migration_status(engine)["up_to_date"] is True
    with Session(engine) as session:
        kept = session.get(Project, project_id)
        assert kept is not None
        assert kept.name == "Existing Project"

    engine.dispose()


def test_init_db_stamps_existing_schema_with_empty_alembic_version_table(tmp_path) -> None:
    db_path = tmp_path / "empty_version_table.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    Base.metadata.create_all(bind=engine)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))

    assert migration_status(engine)["current_revision"] is None

    init_db(engine)

    assert migration_status(engine)["up_to_date"] is True

    engine.dispose()


def test_init_db_rejects_incompatible_existing_schema(tmp_path) -> None:
    db_path = tmp_path / "old_schema.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    with engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE document_pipeline_jobs (
                    id VARCHAR(36) PRIMARY KEY,
                    document_id VARCHAR(36) NOT NULL,
                    status VARCHAR(20) NOT NULL,
                    current_step VARCHAR(20),
                    steps_json TEXT NOT NULL,
                    step_results_json TEXT NOT NULL,
                    error_message TEXT,
                    created_at DATETIME NOT NULL,
                    started_at DATETIME,
                    finished_at DATETIME,
                    updated_at DATETIME NOT NULL
                )
                """
            )
        )

    try:
        init_db(engine)
    except RuntimeError as error:
        message = str(error)
        assert "incompatible" in message
        assert "cancel_requested" in message
        assert "progress_percent" in message
        assert "priority" in message
    else:
        raise AssertionError("init_db should reject incompatible existing schema")
    finally:
        engine.dispose()


def test_alembic_upgrade_head_is_idempotent(tmp_path) -> None:
    db_path = tmp_path / "upgrade_head.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")

    upgrade_head(engine)
    upgrade_head(engine)

    assert migration_status(engine)["up_to_date"] is True
    assert "alembic_version" in inspect(engine).get_table_names()

    engine.dispose()


def test_check_migrations_script_reports_up_to_date(tmp_path) -> None:
    db_path = tmp_path / "script_check.db"
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    init_db(engine)
    engine.dispose()

    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{db_path.as_posix()}",
        "SQLITE_DB_PATH": str(db_path),
        "DATA_DIR": str(tmp_path),
        "FILES_DIR": str(tmp_path / "files"),
        "PARSED_DIR": str(tmp_path / "parsed"),
        "CHROMA_PERSIST_DIR": str(tmp_path / "vector_db"),
    }
    result = subprocess.run(
        [sys.executable, "backend/scripts/check_migrations.py"],
        check=True,
        capture_output=True,
        cwd=Path(__file__).resolve().parents[3],
        env=env,
        text=True,
    )

    assert "up_to_date=True" in result.stdout
