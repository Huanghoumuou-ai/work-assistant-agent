from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol

import httpx
from fastapi import HTTPException, status

from backend.app.core.config import settings


@dataclass(frozen=True)
class EmbeddingProviderInfo:
    provider: str
    model: str
    configured: bool


class EmbeddingProvider(Protocol):
    @property
    def info(self) -> EmbeddingProviderInfo:
        ...

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        ...


def _bad_request(message: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "success": False,
            "code": "BAD_REQUEST",
            "message": message,
            "data": None,
        },
    )


def _response_error_message(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        text = response.text.strip()
        return text[:300] if text else response.reason_phrase

    if isinstance(body, dict):
        for key in ("message", "error_description", "code"):
            value = body.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:300]
        error = body.get("error")
        if isinstance(error, dict):
            for key in ("message", "code", "type"):
                value = error.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()[:300]
        if isinstance(error, str) and error.strip():
            return error.strip()[:300]

    return response.reason_phrase


class OpenAIEmbeddingProvider:
    @property
    def info(self) -> EmbeddingProviderInfo:
        return EmbeddingProviderInfo(
            provider="openai",
            model=settings.embedding_model,
            configured=bool(settings.openai_api_key),
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not settings.openai_api_key:
            raise _bad_request("OPENAI_API_KEY must be configured when EMBEDDING_PROVIDER=openai.")
        if not texts:
            return []

        base_url = settings.openai_base_url.rstrip("/")
        url = f"{base_url}/embeddings"
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.embedding_model,
            "input": texts,
        }
        try:
            response = httpx.post(
                url,
                headers=headers,
                json=payload,
                timeout=settings.embedding_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            rows = sorted(body.get("data", []), key=lambda item: item.get("index", 0))
            embeddings = [row.get("embedding") for row in rows]
        except HTTPException:
            raise
        except httpx.HTTPStatusError as error:
            detail = _response_error_message(error.response)
            raise _bad_request(f"Embedding request failed: {detail}") from error
        except Exception as error:
            raise _bad_request("Embedding request failed.") from error

        if len(embeddings) != len(texts) or any(not isinstance(item, list) for item in embeddings):
            raise _bad_request("Embedding response shape is invalid.")
        return embeddings


class FakeEmbeddingProvider:
    def __init__(self, dimension: int = 8) -> None:
        self.dimension = dimension

    @property
    def info(self) -> EmbeddingProviderInfo:
        return EmbeddingProviderInfo(
            provider="fake",
            model=settings.embedding_model,
            configured=True,
        )

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        embeddings: list[list[float]] = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            values = []
            for index in range(self.dimension):
                value = digest[index] / 255.0
                values.append(value)
            embeddings.append(values)
        return embeddings


def get_embedding_provider() -> EmbeddingProvider:
    provider = settings.embedding_provider.strip().lower()
    if provider == "openai":
        return OpenAIEmbeddingProvider()
    if provider == "fake":
        return FakeEmbeddingProvider()
    raise _bad_request("Unsupported EMBEDDING_PROVIDER.")
