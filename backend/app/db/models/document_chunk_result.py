from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class DocumentChunkResult(Base):
    __tablename__ = "document_chunk_results"

    document_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("documents.id"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    parse_content_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    cleaner_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cleaner_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chunker_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    chunker_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_chunk_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    overlap_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )
