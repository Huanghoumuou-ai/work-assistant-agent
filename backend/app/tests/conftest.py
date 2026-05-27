from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

import pytest


TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="workmemory_test_data_"))
TEST_DB_PATH = TEST_DATA_DIR / "sqlite" / "test_workmemory.db"
os.environ["DATA_DIR"] = str(TEST_DATA_DIR)
os.environ["FILES_DIR"] = str(TEST_DATA_DIR / "files")
os.environ["PARSED_DIR"] = str(TEST_DATA_DIR / "parsed")
os.environ["CHROMA_PERSIST_DIR"] = str(TEST_DATA_DIR / "vector_db")
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH.as_posix()}"
os.environ["SQLITE_DB_PATH"] = str(TEST_DB_PATH)
os.environ["MAX_UPLOAD_SIZE_MB"] = "50"


@pytest.fixture(autouse=True)
def cleanup_active_pipeline_jobs():
    yield
    try:
        from backend.app.db.models import DocumentPipelineJob
        from backend.app.db.session import SessionLocal

        with SessionLocal() as db:
            jobs = db.query(DocumentPipelineJob).filter(DocumentPipelineJob.status.in_({"queued", "running"})).all()
            for job in jobs:
                job.status = "failed"
                job.error_message = "Test cleanup marked unfinished pipeline job failed."
                job.locked_by = None
                job.lock_expires_at = None
            db.commit()
    except Exception:
        pass


def pytest_sessionfinish(session, exitstatus) -> None:
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
