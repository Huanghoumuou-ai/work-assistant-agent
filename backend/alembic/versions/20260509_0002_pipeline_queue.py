"""Add persistent pipeline queue fields and job events.

Revision ID: 20260509_0002
Revises: 20260507_0001
Create Date: 2026-05-09
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260509_0002"
down_revision = "20260507_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("document_pipeline_jobs", sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("document_pipeline_jobs", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("document_pipeline_jobs", sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("document_pipeline_jobs", sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("document_pipeline_jobs", sa.Column("locked_by", sa.String(length=100), nullable=True))
    op.add_column("document_pipeline_jobs", sa.Column("lock_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("document_pipeline_jobs", sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("document_pipeline_jobs", sa.Column("last_error_code", sa.String(length=80), nullable=True))
    op.execute("UPDATE document_pipeline_jobs SET next_run_at = created_at WHERE next_run_at IS NULL")

    op.create_index("ix_document_pipeline_jobs_priority", "document_pipeline_jobs", ["priority"])
    op.create_index("ix_document_pipeline_jobs_next_run_at", "document_pipeline_jobs", ["next_run_at"])
    op.create_index("ix_document_pipeline_jobs_locked_by", "document_pipeline_jobs", ["locked_by"])
    op.create_index("ix_document_pipeline_jobs_lock_expires_at", "document_pipeline_jobs", ["lock_expires_at"])

    op.create_table(
        "document_pipeline_job_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("job_id", sa.String(length=36), nullable=False),
        sa.Column("document_id", sa.String(length=36), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("step", sa.String(length=20), nullable=True),
        sa.Column("message", sa.String(length=500), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"]),
        sa.ForeignKeyConstraint(["job_id"], ["document_pipeline_jobs.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_document_pipeline_job_events_document_id", "document_pipeline_job_events", ["document_id"])
    op.create_index("ix_document_pipeline_job_events_event_type", "document_pipeline_job_events", ["event_type"])
    op.create_index("ix_document_pipeline_job_events_job_id", "document_pipeline_job_events", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_document_pipeline_job_events_job_id", table_name="document_pipeline_job_events")
    op.drop_index("ix_document_pipeline_job_events_event_type", table_name="document_pipeline_job_events")
    op.drop_index("ix_document_pipeline_job_events_document_id", table_name="document_pipeline_job_events")
    op.drop_table("document_pipeline_job_events")

    op.drop_index("ix_document_pipeline_jobs_lock_expires_at", table_name="document_pipeline_jobs")
    op.drop_index("ix_document_pipeline_jobs_locked_by", table_name="document_pipeline_jobs")
    op.drop_index("ix_document_pipeline_jobs_next_run_at", table_name="document_pipeline_jobs")
    op.drop_index("ix_document_pipeline_jobs_priority", table_name="document_pipeline_jobs")
    op.drop_column("document_pipeline_jobs", "last_error_code")
    op.drop_column("document_pipeline_jobs", "heartbeat_at")
    op.drop_column("document_pipeline_jobs", "lock_expires_at")
    op.drop_column("document_pipeline_jobs", "locked_by")
    op.drop_column("document_pipeline_jobs", "next_run_at")
    op.drop_column("document_pipeline_jobs", "max_attempts")
    op.drop_column("document_pipeline_jobs", "attempt_count")
    op.drop_column("document_pipeline_jobs", "priority")
