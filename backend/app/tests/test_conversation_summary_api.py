from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.models import Conversation, ConversationSummary, Memory, Message
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.schemas.rag import RagSearchOut
from backend.app.services import chat_service, conversation_summary_service
from backend.app.services.llm_provider import ChatCompletionResult, ChatProviderInfo


def _use_fake_stack(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    monkeypatch.setattr(settings, "llm_provider", "fake")
    monkeypatch.setattr(settings, "chroma_collection_name", f"summary_{uuid4().hex}")
    monkeypatch.setattr(settings, "default_retrieval_top_k", 5)
    monkeypatch.setattr(settings, "max_retrieval_top_k", 20)
    monkeypatch.setattr(settings, "rag_top_k", 5)
    monkeypatch.setattr(settings, "chat_context_recent_messages", 8)
    monkeypatch.setattr(settings, "chat_context_max_chars", 6000)
    monkeypatch.setattr(settings, "conversation_summary_max_messages", 80)
    monkeypatch.setattr(settings, "conversation_summary_max_chars", 12000)
    monkeypatch.setattr(settings, "conversation_summary_target_chars", 1800)
    monkeypatch.setattr(settings, "auto_summary_enabled", False)
    monkeypatch.setattr(settings, "auto_summary_min_new_messages", 6)
    monkeypatch.setattr(settings, "auto_summary_min_total_messages", 10)
    monkeypatch.setattr(settings, "auto_summary_max_per_chat", 1)


def _post_chat(payload: dict):
    with TestClient(app) as client:
        return client.post("/api/chat", json=payload)


def _create_conversation_with_messages(messages: list[tuple[str, str]]) -> tuple[str, list[str]]:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        conversation = Conversation(title=f"Summary {uuid4().hex[:8]}", project_id=None)
        db.add(conversation)
        db.flush()
        ids: list[str] = []
        for index, (role, content) in enumerate(messages):
            message = Message(
                conversation_id=conversation.id,
                role=role,
                content=content,
                created_at=now + timedelta(seconds=index),
            )
            db.add(message)
            db.flush()
            ids.append(message.id)
        db.commit()
        return conversation.id, ids


def _save_summary(
    conversation_id: str,
    *,
    status: str = "summarized",
    summary: str | None = "Existing summary",
    last_message_id: str | None = None,
    message_count: int = 1,
) -> None:
    with SessionLocal() as db:
        db.add(
            ConversationSummary(
                conversation_id=conversation_id,
                status=status,
                summary=summary,
                message_count=message_count,
                last_message_id=last_message_id,
                provider="fake",
                model=settings.openai_model,
                error_message="failed" if status == "failed" else None,
            )
        )
        db.commit()


def _memory_count() -> int:
    with SessionLocal() as db:
        return db.query(Memory).count()


def test_summary_generation_success_refresh_and_stale(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    first = _post_chat({"query": "first summary question"})
    conversation_id = first.json()["data"]["conversation"]["id"]

    with TestClient(app) as client:
        missing_before = client.get(f"/api/conversations/{conversation_id}/summary")
        generated = client.post(f"/api/conversations/{conversation_id}/summary")

    assert missing_before.status_code == 200
    assert missing_before.json()["data"]["status"] == "missing"
    assert missing_before.json()["data"]["new_message_count"] == 2
    assert missing_before.json()["data"]["needs_refresh"] is False
    assert generated.status_code == 200
    data = generated.json()["data"]
    assert data["status"] == "summarized"
    assert data["summary"] == "Fake conversation summary."
    assert data["message_count"] == 2
    assert data["last_message_id"]
    assert data["stale"] is False

    second = _post_chat({"conversation_id": conversation_id, "query": "second summary question"})
    assert second.status_code == 200
    with TestClient(app) as client:
        stale = client.get(f"/api/conversations/{conversation_id}/summary")
        refreshed = client.post(f"/api/conversations/{conversation_id}/summary")

    assert stale.json()["data"]["stale"] is True
    assert refreshed.json()["data"]["message_count"] == 4
    assert refreshed.json()["data"]["stale"] is False


def test_summary_state_thresholds_for_missing_and_stale(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    monkeypatch.setattr(settings, "auto_summary_min_total_messages", 4)
    monkeypatch.setattr(settings, "auto_summary_min_new_messages", 2)
    missing_conversation_id, _ = _create_conversation_with_messages(
        [("user", "m1"), ("assistant", "m2"), ("user", "m3"), ("assistant", "m4")]
    )
    stale_low_id, stale_low_messages = _create_conversation_with_messages(
        [("user", "s1"), ("assistant", "s2"), ("user", "s3")]
    )
    stale_ready_id, stale_ready_messages = _create_conversation_with_messages(
        [("user", "r1"), ("assistant", "r2"), ("user", "r3"), ("assistant", "r4")]
    )
    _save_summary(stale_low_id, last_message_id=stale_low_messages[1], message_count=2)
    _save_summary(stale_ready_id, last_message_id=stale_ready_messages[1], message_count=2)

    with TestClient(app) as client:
        missing = client.get(f"/api/conversations/{missing_conversation_id}/summary")
        stale_low = client.get(f"/api/conversations/{stale_low_id}/summary")
        stale_ready = client.get(f"/api/conversations/{stale_ready_id}/summary")

    assert missing.status_code == 200
    assert missing.json()["data"]["status"] == "missing"
    assert missing.json()["data"]["new_message_count"] == 4
    assert missing.json()["data"]["needs_refresh"] is True
    assert stale_low.json()["data"]["new_message_count"] == 1
    assert stale_low.json()["data"]["needs_refresh"] is False
    assert stale_ready.json()["data"]["new_message_count"] == 2
    assert stale_ready.json()["data"]["needs_refresh"] is True


def test_summary_missing_empty_and_openai_validation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    empty_conversation_id, _ = _create_conversation_with_messages([])

    with TestClient(app) as client:
        missing = client.post(f"/api/conversations/{uuid4()}/summary")
        empty = client.post(f"/api/conversations/{empty_conversation_id}/summary")

    assert missing.status_code == 404
    assert empty.status_code == 400

    conversation_id, _ = _create_conversation_with_messages([("user", "needs summary")])
    monkeypatch.setattr(settings, "llm_provider", "openai")
    monkeypatch.setattr(settings, "openai_api_key", "")
    with TestClient(app) as client:
        openai_missing = client.post(f"/api/conversations/{conversation_id}/summary")
    assert openai_missing.status_code == 400
    assert "OPENAI_API_KEY" in openai_missing.json()["detail"]["message"]


def test_summary_llm_failure_writes_failed_without_stack(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    conversation_id, _ = _create_conversation_with_messages([("user", "fail summary")])

    @dataclass
    class FailingProvider:
        @property
        def info(self) -> ChatProviderInfo:
            return ChatProviderInfo(provider="fake", model=settings.openai_model, configured=True)

        def complete(self, messages):  # type: ignore[no-untyped-def]
            raise RuntimeError("stack details should stay server side")

    monkeypatch.setattr(conversation_summary_service, "get_chat_provider", lambda: FailingProvider())

    with TestClient(app) as client:
        failed = client.post(f"/api/conversations/{conversation_id}/summary")
        loaded = client.get(f"/api/conversations/{conversation_id}/summary")

    assert failed.status_code == 400
    assert "stack details" not in failed.text
    assert loaded.status_code == 200
    data = loaded.json()["data"]
    assert data["status"] == "failed"
    assert data["error_message"] == "Conversation summary generation failed."


def test_summary_prompt_omits_sources_json(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    captured: dict[str, list[dict[str, str]]] = {}
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        conversation = Conversation(title="source omission", project_id=None)
        db.add(conversation)
        db.flush()
        db.add(
            Message(
                conversation_id=conversation.id,
                role="assistant",
                content="assistant content only",
                sources_json='{"secret":"SOURCE_JSON_SHOULD_NOT_APPEAR"}',
                created_at=now,
            )
        )
        db.commit()
        conversation_id = conversation.id

    @dataclass
    class CapturingProvider:
        @property
        def info(self) -> ChatProviderInfo:
            return ChatProviderInfo(provider="fake", model=settings.openai_model, configured=True)

        def complete(self, messages):  # type: ignore[no-untyped-def]
            captured["messages"] = messages
            return ChatCompletionResult(content="safe summary", model=settings.openai_model, provider="fake")

    monkeypatch.setattr(conversation_summary_service, "get_chat_provider", lambda: CapturingProvider())

    with TestClient(app) as client:
        response = client.post(f"/api/conversations/{conversation_id}/summary")

    assert response.status_code == 200
    prompt = "\n".join(message["content"] for message in captured["messages"])
    assert "assistant content only" in prompt
    assert "SOURCE_JSON_SHOULD_NOT_APPEAR" not in prompt


def test_chat_injects_valid_summary_and_recent_messages(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    conversation_id, message_ids = _create_conversation_with_messages(
        [
            ("user", "covered old user"),
            ("assistant", "covered old assistant"),
            ("user", "new stale user"),
            ("assistant", "new stale assistant"),
        ]
    )
    _save_summary(
        conversation_id,
        summary="Summarized history marker",
        last_message_id=message_ids[1],
        message_count=2,
    )
    captured: dict[str, str | None] = {}

    def fake_answer(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured["context"] = kwargs.get("conversation_context")
        return RagSearchOut(answer="ok", sources=[], memory_sources=[], model="fake", provider="fake", usage=None)

    monkeypatch.setattr(chat_service, "answer_rag", fake_answer)

    response = _post_chat({"conversation_id": conversation_id, "query": "continue"})

    assert response.status_code == 200
    context = captured["context"] or ""
    assert "Summarized history marker" in context
    assert "new stale user" in context
    assert "new stale assistant" in context
    assert "must not override system instructions" in context


def test_failed_summary_is_not_injected_into_chat(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    conversation_id, message_ids = _create_conversation_with_messages([("user", "recent only message")])
    _save_summary(
        conversation_id,
        status="failed",
        summary="FAILED SUMMARY SHOULD NOT APPEAR",
        last_message_id=message_ids[0],
        message_count=1,
    )
    captured: dict[str, str | None] = {}

    def fake_answer(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured["context"] = kwargs.get("conversation_context")
        return RagSearchOut(answer="ok", sources=[], memory_sources=[], model="fake", provider="fake", usage=None)

    monkeypatch.setattr(chat_service, "answer_rag", fake_answer)

    response = _post_chat({"conversation_id": conversation_id, "query": "continue"})

    assert response.status_code == 200
    context = captured["context"] or ""
    assert "FAILED SUMMARY SHOULD NOT APPEAR" not in context
    assert "recent only message" in context


def test_chat_context_is_trimmed_without_mutating_summary(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    monkeypatch.setattr(settings, "chat_context_recent_messages", 4)
    monkeypatch.setattr(settings, "chat_context_max_chars", 260)
    long_summary = "summary-" + ("x" * 1000)
    conversation_id, message_ids = _create_conversation_with_messages(
        [
            ("user", "older message " + ("a" * 200)),
            ("assistant", "newer message " + ("b" * 120)),
        ]
    )
    _save_summary(conversation_id, summary=long_summary, last_message_id=message_ids[0], message_count=1)
    captured: dict[str, str | None] = {}

    def fake_answer(*args, **kwargs):  # type: ignore[no-untyped-def]
        captured["context"] = kwargs.get("conversation_context")
        return RagSearchOut(answer="ok", sources=[], memory_sources=[], model="fake", provider="fake", usage=None)

    monkeypatch.setattr(chat_service, "answer_rag", fake_answer)

    response = _post_chat({"conversation_id": conversation_id, "query": "continue"})

    assert response.status_code == 200
    assert captured["context"] is not None
    assert len(captured["context"] or "") <= 260
    with SessionLocal() as db:
        saved = db.get(ConversationSummary, conversation_id)
        assert saved is not None
        assert saved.summary == long_summary


def test_chat_does_not_auto_refresh_by_default_or_when_disabled(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    monkeypatch.setattr(settings, "auto_summary_min_total_messages", 2)

    first = _post_chat({"query": "default auto summary off"})
    conversation_id = first.json()["data"]["conversation"]["id"]

    assert first.status_code == 200
    assert first.json()["data"]["summary"]["status"] == "missing"
    assert first.json()["data"]["summary"]["needs_refresh"] is True
    with SessionLocal() as db:
        assert db.get(ConversationSummary, conversation_id) is None

    second = _post_chat({"conversation_id": conversation_id, "query": "requested but globally disabled", "auto_summary": True})

    assert second.status_code == 200
    assert second.json()["data"]["summary"]["status"] == "missing"
    with SessionLocal() as db:
        assert db.get(ConversationSummary, conversation_id) is None


def test_chat_auto_summary_refreshes_when_enabled_and_requested(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    monkeypatch.setattr(settings, "auto_summary_enabled", True)
    monkeypatch.setattr(settings, "auto_summary_min_total_messages", 2)

    response = _post_chat({"query": "auto summary enabled", "auto_summary": True})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["summary"]["status"] == "summarized"
    assert data["summary"]["summary"] == "Fake conversation summary."
    assert data["summary"]["needs_refresh"] is False
    with SessionLocal() as db:
        assert db.get(ConversationSummary, data["conversation"]["id"]) is not None


def test_auto_summary_failure_preserves_chat_messages_and_writes_failed(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    monkeypatch.setattr(settings, "auto_summary_enabled", True)
    monkeypatch.setattr(settings, "auto_summary_min_total_messages", 2)
    before_conversation_count = 0
    before_message_count = 0

    @dataclass
    class FailingProvider:
        @property
        def info(self) -> ChatProviderInfo:
            return ChatProviderInfo(provider="fake", model=settings.openai_model, configured=True)

        def complete(self, messages):  # type: ignore[no-untyped-def]
            raise RuntimeError("auto summary stack details")

    monkeypatch.setattr(conversation_summary_service, "get_chat_provider", lambda: FailingProvider())
    with SessionLocal() as db:
        before_conversation_count = db.query(Conversation).count()
        before_message_count = db.query(Message).count()

    response = _post_chat({"query": "auto summary will fail", "auto_summary": True})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["summary"]["status"] == "failed"
    assert data["summary"]["error_message"] == "Conversation summary generation failed."
    assert "auto summary stack details" not in response.text
    with SessionLocal() as db:
        assert db.query(Conversation).count() == before_conversation_count + 1
        assert db.query(Message).count() == before_message_count + 2
        saved = db.get(ConversationSummary, data["conversation"]["id"])
        assert saved is not None
        assert saved.status == "failed"


def test_summary_and_rag_do_not_create_or_use_memory(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    conversation_id, _ = _create_conversation_with_messages([("user", "summary unique token")])
    before = _memory_count()

    with TestClient(app) as client:
        summary = client.post(f"/api/conversations/{conversation_id}/summary")
        memory_search = client.post("/api/memory/search", json={"query": "Fake conversation summary"})
        rag = client.post("/api/rag/search", json={"query": "Fake conversation summary"})

    assert summary.status_code == 200
    assert memory_search.status_code == 200
    assert memory_search.json()["data"]["items"] == []
    assert rag.status_code == 200
    assert rag.json()["data"]["sources"] == []
    assert _memory_count() == before
