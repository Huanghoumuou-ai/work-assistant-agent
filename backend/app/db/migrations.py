from __future__ import annotations

from typing import Any

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from backend.app.core.config import PROJECT_ROOT, settings
from backend.app.db.base import Base
from backend.app.db import models  # noqa: F401
from backend.app.db.session import engine


ALEMBIC_INI_PATH = PROJECT_ROOT / "backend" / "alembic.ini"
ALEMBIC_VERSION_TABLE = "alembic_version"


def alembic_config() -> Config:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("sqlalchemy.url", settings.sqlalchemy_database_url)
    return config


def head_revision() -> str:
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def current_revision(bind: Engine | None = None) -> str | None:
    target = bind or engine
    with target.connect() as connection:
        context = MigrationContext.configure(connection)
        return context.get_current_revision()


def migration_status(bind: Engine | None = None) -> dict[str, Any]:
    current = current_revision(bind)
    head = head_revision()
    return {
        "current_revision": current,
        "head_revision": head,
        "up_to_date": current == head,
    }


def upgrade_head(bind: Engine | None = None) -> None:
    config = alembic_config()
    config.attributes["configure_logger"] = False
    target = bind or engine
    with target.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")


def stamp_head(bind: Engine | None = None) -> None:
    config = alembic_config()
    config.attributes["configure_logger"] = False
    target = bind or engine
    with target.begin() as connection:
        config.attributes["connection"] = connection
        command.stamp(config, "head")


def has_alembic_version_table(bind: Engine) -> bool:
    return inspect(bind).has_table(ALEMBIC_VERSION_TABLE)


def database_has_application_tables(bind: Engine) -> bool:
    inspector = inspect(bind)
    existing = set(inspector.get_table_names())
    application_tables = {table.name for table in Base.metadata.sorted_tables}
    return bool(existing & application_tables)


def validate_current_schema(bind: Engine) -> None:
    inspector = inspect(bind)
    errors: list[str] = []
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            errors.append(f"missing table {table.name}")
            continue
        actual_columns = {column["name"] for column in inspector.get_columns(table.name)}
        expected_columns = {column.name for column in table.columns}
        missing_columns = sorted(expected_columns - actual_columns)
        if missing_columns:
            errors.append(f"{table.name} missing columns: {', '.join(missing_columns)}")

    if errors:
        raise RuntimeError(
            "Existing database schema is incompatible with the current ORM models. "
            "This project now uses Alembic migrations and will not silently modify or delete existing data. "
            "Back up the SQLite database, then reset the development DB, add a manual migration, or repair the schema. "
            f"Details: {'; '.join(errors)}"
        )


def initialize_database_with_migrations(bind: Engine | None = None) -> None:
    target = bind or engine
    current = current_revision(target) if has_alembic_version_table(target) else None
    if current is not None:
        upgrade_head(target)
        return

    if database_has_application_tables(target):
        validate_current_schema(target)
        stamp_head(target)
        return

    upgrade_head(target)
