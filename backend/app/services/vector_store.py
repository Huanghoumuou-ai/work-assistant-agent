from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import chromadb

from backend.app.core.config import settings
from backend.app.core.runtime import ensure_runtime_dirs


@dataclass(frozen=True)
class VectorRecord:
    id: str
    embedding: list[float]
    metadata: dict[str, str | int | float | bool | None]
    document: str


@dataclass(frozen=True)
class VectorQueryHit:
    id: str
    distance: float
    metadata: dict[str, Any]


class ChromaVectorStore:
    def __init__(self, collection_name: str | None = None) -> None:
        ensure_runtime_dirs()
        self.collection_name = collection_name or settings.chroma_collection_name
        self.persist_path = settings.chroma_path
        self.client = chromadb.PersistentClient(path=str(self.persist_path))
        self.collection = self.client.get_or_create_collection(self.collection_name)

    @classmethod
    def list_collection_names(cls) -> list[str]:
        ensure_runtime_dirs()
        client = chromadb.PersistentClient(path=str(settings.chroma_path))
        names: list[str] = []
        for collection in client.list_collections():
            name = collection if isinstance(collection, str) else getattr(collection, "name", None)
            if name:
                names.append(str(name))
        return sorted(set(names))

    def count(self) -> int:
        return int(self.collection.count())

    def collection_dimension(self) -> int | None:
        if self.count() == 0:
            return None
        try:
            result = self.collection.get(limit=1, include=["embeddings"])
        except Exception:
            return None
        embeddings = result.get("embeddings")
        if embeddings is None:
            return None
        if hasattr(embeddings, "tolist"):
            embeddings = embeddings.tolist()
        if not embeddings:
            return None
        first = embeddings[0]
        if hasattr(first, "tolist"):
            first = first.tolist()
        return len(first)

    def upsert(self, records: list[VectorRecord]) -> None:
        if not records:
            return
        self.collection.upsert(
            ids=[record.id for record in records],
            embeddings=[record.embedding for record in records],
            metadatas=[_clean_metadata(record.metadata) for record in records],
            documents=[record.document for record in records],
        )

    def delete_ids(self, ids: list[str]) -> None:
        if not ids:
            return
        self.collection.delete(ids=ids)

    def delete_document(self, document_id: str) -> None:
        self.collection.delete(where={"document_id": document_id})

    def reset_collection(self) -> None:
        try:
            self.client.delete_collection(self.collection_name)
        except Exception as error:
            message = str(error).lower()
            if "not found" not in message and "does not exist" not in message:
                raise
        self.collection = self.client.get_or_create_collection(self.collection_name)

    def query(
        self,
        *,
        embedding: list[float],
        n_results: int,
        where: dict[str, Any] | None = None,
    ) -> list[VectorQueryHit]:
        if n_results <= 0:
            return []

        kwargs: dict[str, Any] = {
            "query_embeddings": [embedding],
            "n_results": n_results,
            "include": ["metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where

        result = self.collection.query(**kwargs)
        ids = (result.get("ids") or [[]])[0]
        distances = (result.get("distances") or [[]])[0]
        metadatas = (result.get("metadatas") or [[]])[0]

        hits: list[VectorQueryHit] = []
        for index, vector_id in enumerate(ids):
            distance = distances[index] if index < len(distances) else 0.0
            metadata = metadatas[index] if index < len(metadatas) and metadatas[index] else {}
            hits.append(
                VectorQueryHit(
                    id=str(vector_id),
                    distance=float(distance),
                    metadata=dict(metadata),
                )
            )
        return hits


def _clean_metadata(metadata: dict[str, Any]) -> dict[str, str | int | float | bool]:
    cleaned: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if value is None:
            cleaned[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        else:
            cleaned[key] = str(value)
    return cleaned
