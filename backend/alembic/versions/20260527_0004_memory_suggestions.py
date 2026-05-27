"""Add memory suggestions.

Revision ID: 20260527_0004
Revises: 20260518_0003
Create Date: 2026-05-27
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260527_0004"
down_revision = "20260518_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_suggestions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("conversation_id", sa.String(length=36), nullable=True),
        sa.Column("project_id", sa.String(length=36), nullable=True),
        sa.Column("type", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=120), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("rationale", sa.String(length=500), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_ref", sa.String(length=100), nullable=True),
        sa.Column("memory_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"]),
        sa.ForeignKeyConstraint(["memory_id"], ["memories.id"]),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_memory_suggestions_conversation_id", "memory_suggestions", ["conversation_id"])
    op.create_index("ix_memory_suggestions_created_at", "memory_suggestions", ["created_at"])
    op.create_index("ix_memory_suggestions_project_id", "memory_suggestions", ["project_id"])
    op.create_index("ix_memory_suggestions_status", "memory_suggestions", ["status"])
    op.create_index("ix_memory_suggestions_type", "memory_suggestions", ["type"])


def downgrade() -> None:
    op.drop_index("ix_memory_suggestions_type", table_name="memory_suggestions")
    op.drop_index("ix_memory_suggestions_status", table_name="memory_suggestions")
    op.drop_index("ix_memory_suggestions_project_id", table_name="memory_suggestions")
    op.drop_index("ix_memory_suggestions_created_at", table_name="memory_suggestions")
    op.drop_index("ix_memory_suggestions_conversation_id", table_name="memory_suggestions")
    op.drop_table("memory_suggestions")
