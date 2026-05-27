from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentEmbeddingResult(Base):
    __tablename__ = "document_embedding_results"

    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_set_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    indexed_chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    vector_collection: Mapped[str] = mapped_column(String(100), nullable=False)
    vector_ids_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    indexed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
