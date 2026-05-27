from __future__ import annotations

from pathlib import Path
from typing import Iterable

from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "WorkMemory Agent"
    app_env: str = "development"
    app_version: str = "0.1.0"
    app_timezone: str = "Asia/Shanghai"

    backend_host: str = "127.0.0.1"
    backend_port: int = 8000

    data_dir: str = "data"
    files_dir: str = "data/files"
    parsed_dir: str = "data/parsed"
    sqlite_db_path: str = "data/sqlite/workmemory.db"
    chroma_persist_dir: str = "data/vector_db"
    database_url: str = ""

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o-mini"
    llm_provider: str = "openai"
    llm_timeout_seconds: int = 60
    embedding_model: str = "text-embedding-3-small"
    embedding_provider: str = "openai"
    embedding_batch_size: int = 64
    embedding_timeout_seconds: int = 60
    chroma_collection_name: str = "workmemory_chunks"
    default_retrieval_top_k: int = 5
    max_retrieval_top_k: int = 20
    rag_top_k: int = 5
    rag_max_context_chars: int = 12_000
    rag_source_excerpt_chars: int = 500
    memory_context_max_chars_per_item: int = 1_200
    memory_context_max_total_chars: int = 5_000
    chat_context_recent_messages: int = 8
    chat_context_max_chars: int = 6_000
    conversation_summary_max_messages: int = 80
    conversation_summary_max_chars: int = 12_000
    conversation_summary_target_chars: int = 1_800
    auto_summary_enabled: bool = False
    auto_summary_min_new_messages: int = 6
    auto_summary_min_total_messages: int = 10
    auto_summary_max_per_chat: int = 1
    pipeline_worker_concurrency: int = 1
    pipeline_poll_interval_seconds: int = 1
    pipeline_lock_timeout_seconds: int = 3600
    max_upload_size_mb: int = 50
    max_parse_chars: int = 2_000_000
    max_parse_pages: int = 200
    max_parse_rows: int = 10_000
    max_parse_sheets: int = 20
    max_chunk_chars: int = 1_200
    chunk_overlap_chars: int = 150
    max_chunks_per_document: int = 5_000

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return PROJECT_ROOT / path

    @property
    def data_path(self) -> Path:
        return self.resolve_path(self.data_dir)

    @property
    def files_path(self) -> Path:
        return self.resolve_path(self.files_dir)

    @property
    def parsed_path(self) -> Path:
        return self.resolve_path(self.parsed_dir)

    @property
    def sqlite_path(self) -> Path:
        return self.resolve_path(self.sqlite_db_path)

    @property
    def chroma_path(self) -> Path:
        return self.resolve_path(self.chroma_persist_dir)

    @property
    def logs_path(self) -> Path:
        return self.data_path / "logs"

    @property
    def cache_path(self) -> Path:
        return self.data_path / "cache"

    @property
    def sqlalchemy_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.sqlite_path.as_posix()}"

    def runtime_dirs(self) -> Iterable[Path]:
        return (
            self.data_path,
            self.files_path,
            self.parsed_path,
            self.sqlite_path.parent,
            self.chroma_path,
            self.logs_path,
            self.cache_path,
        )

    @property
    def max_upload_size_bytes(self) -> int:
        return self.max_upload_size_mb * 1024 * 1024


settings = Settings()
