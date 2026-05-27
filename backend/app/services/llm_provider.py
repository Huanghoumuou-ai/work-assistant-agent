from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable, Protocol

import httpx
from fastapi import HTTPException, status

from backend.app.core.config import settings


@dataclass(frozen=True)
class ChatProviderInfo:
    provider: str
    model: str
    configured: bool


@dataclass(frozen=True)
class ChatCompletionResult:
    content: str
    model: str
    provider: str
    usage: dict[str, Any] | None = None


class ChatProvider(Protocol):
    @property
    def info(self) -> ChatProviderInfo:
        ...

    def complete(self, messages: list[dict[str, str]]) -> ChatCompletionResult:
        ...

    def stream_complete(self, messages: list[dict[str, str]]) -> Iterable[str]:
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


class OpenAIChatProvider:
    @property
    def info(self) -> ChatProviderInfo:
        return ChatProviderInfo(
            provider="openai",
            model=settings.openai_model,
            configured=bool(settings.openai_api_key),
        )

    def complete(self, messages: list[dict[str, str]]) -> ChatCompletionResult:
        if not settings.openai_api_key:
            raise _bad_request("OPENAI_API_KEY must be configured when LLM_PROVIDER=openai.")

        base_url = settings.openai_base_url.rstrip("/")
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.openai_model,
            "messages": messages,
            "temperature": 0.2,
        }
        try:
            response = httpx.post(
                url,
                headers=headers,
                json=payload,
                timeout=settings.llm_timeout_seconds,
            )
            response.raise_for_status()
            body = response.json()
            content = body["choices"][0]["message"]["content"]
        except HTTPException:
            raise
        except Exception as error:
            raise _bad_request("LLM request failed.") from error

        if not isinstance(content, str) or not content.strip():
            raise _bad_request("LLM response content is empty.")
        usage = body.get("usage")
        return ChatCompletionResult(
            content=content.strip(),
            model=str(body.get("model") or settings.openai_model),
            provider="openai",
            usage=usage if isinstance(usage, dict) else None,
        )

    def stream_complete(self, messages: list[dict[str, str]]) -> Iterable[str]:
        if not settings.openai_api_key:
            raise _bad_request("OPENAI_API_KEY must be configured when LLM_PROVIDER=openai.")

        base_url = settings.openai_base_url.rstrip("/")
        url = f"{base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.openai_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": settings.openai_model,
            "messages": messages,
            "temperature": 0.2,
            "stream": True,
        }
        try:
            with httpx.stream(
                "POST",
                url,
                headers=headers,
                json=payload,
                timeout=settings.llm_timeout_seconds,
            ) as response:
                response.raise_for_status()
                for line in response.iter_lines():
                    if not line:
                        continue
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    try:
                        body = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    choices = body.get("choices")
                    if not isinstance(choices, list) or not choices:
                        continue
                    delta = choices[0].get("delta")
                    if not isinstance(delta, dict):
                        continue
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        yield content
        except HTTPException:
            raise
        except Exception as error:
            raise _bad_request("LLM streaming request failed.") from error


class FakeChatProvider:
    @property
    def info(self) -> ChatProviderInfo:
        return ChatProviderInfo(
            provider="fake",
            model=settings.openai_model,
            configured=True,
        )

    def complete(self, messages: list[dict[str, str]]) -> ChatCompletionResult:
        prompt = "\n".join(message.get("content", "") for message in messages)
        if "long-term memory candidates" in prompt:
            return ChatCompletionResult(
                content='[{"type":"note","title":"Fake memory suggestion","content":"Fake reviewed memory candidate.","rationale":"Generated by fake provider for local testing."}]',
                model=settings.openai_model,
                provider="fake",
                usage=None,
            )
        if "Create a concise conversation summary" in prompt:
            return ChatCompletionResult(
                content="Fake conversation summary.",
                model=settings.openai_model,
                provider="fake",
                usage=None,
            )
        citations = []
        if "【1】" in prompt:
            citations.append("【1】")
        if "【M1】" in prompt:
            citations.append("【M1】")
        answer = f"Fake RAG answer based on indexed sources {' '.join(citations)}.".strip()
        return ChatCompletionResult(
            content=answer,
            model=settings.openai_model,
            provider="fake",
            usage=None,
        )

    def stream_complete(self, messages: list[dict[str, str]]) -> Iterable[str]:
        result = self.complete(messages)
        words = result.content.split(" ")
        for index, word in enumerate(words):
            yield word if index == len(words) - 1 else f"{word} "


def get_chat_provider() -> ChatProvider:
    provider = settings.llm_provider.strip().lower()
    if provider == "openai":
        return OpenAIChatProvider()
    if provider == "fake":
        return FakeChatProvider()
    raise _bad_request("Unsupported LLM_PROVIDER.")
