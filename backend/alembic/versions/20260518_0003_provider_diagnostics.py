"""Add provider diagnostic history.

Revision ID: 20260518_0003
Revises: 20260509_0002
Create Date: 2026-05-18
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260518_0003"
down_revision = "20260509_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "provider_diagnostic_runs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider_kind", sa.String(length=20), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("configured", sa.Boolean(), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("dimension", sa.Integer(), nullable=True),
        sa.Column("response_preview", sa.String(length=200), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provider_diagnostic_runs_created_at", "provider_diagnostic_runs", ["created_at"])
    op.create_index("ix_provider_diagnostic_runs_ok", "provider_diagnostic_runs", ["ok"])
    op.create_index("ix_provider_diagnostic_runs_provider_kind", "provider_diagnostic_runs", ["provider_kind"])


def downgrade() -> None:
    op.drop_index("ix_provider_diagnostic_runs_provider_kind", table_name="provider_diagnostic_runs")
    op.drop_index("ix_provider_diagnostic_runs_ok", table_name="provider_diagnostic_runs")
    op.drop_index("ix_provider_diagnostic_runs_created_at", table_name="provider_diagnostic_runs")
    op.drop_table("provider_diagnostic_runs")
