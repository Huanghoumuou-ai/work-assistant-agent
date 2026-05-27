from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.models import Conversation, Message
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.services import chat_service
from backend.app.services.rag_service import NO_EVIDENCE_ANSWER


def _use_fake_stack(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    monkeypatch.setattr(settings, "llm_provider", "fake")
    monkeypatch.setattr(settings, "chroma_collection_name", f"chat_{uuid4().hex}")
    monkeypatch.setattr(settings, "default_retrieval_top_k", 5)
    monkeypatch.setattr(settings, "max_retrieval_top_k", 20)
    monkeypatch.setattr(settings, "rag_top_k", 5)
    monkeypatch.setattr(settings, "rag_max_context_chars", 12000)
    monkeypatch.setattr(settings, "rag_source_excerpt_chars", 500)


def _upload(name: str, content: bytes) -> dict:
    with TestClient(app) as client:
        response = client.post(
            "/api/upload",
            files={"file": (name, content, "text/plain")},
        )
    assert response.status_code == 200
    return response.json()["data"]


def _ready_indexed_document(monkeypatch, content: bytes = b"chat source alpha") -> dict:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    document = _upload("chat-source.md", content)
    with TestClient(app) as client:
        assert client.post(f"/api/documents/{document['id']}/parse").status_code == 200
        assert client.post(f"/api/documents/{document['id']}/chunks").status_code == 200
        assert client.post(f"/api/documents/{document['id']}/index").status_code == 200
    return document


def _post_chat(payload: dict):
    with TestClient(app) as client:
        return client.post("/api/chat", json=payload)


def _counts() -> tuple[int, int]:
    with SessionLocal() as db:
        return db.query(Conversation).count(), db.query(Message).count()


def _source_payload() -> dict:
    return {
        "source_id": "S1",
        "rank": 1,
        "document_id": "doc",
        "chunk_id": "chunk",
        "chunk_index": 0,
        "source_filename": "source.md",
        "project_id": None,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "char_start": 0,
        "char_end": 10,
        "score": 1.0,
        "distance": 0.0,
        "excerpt": "excerpt",
    }


def _memory_source_payload() -> dict:
    return {
        "source_id": "M1",
        "rank": 1,
        "memory_id": "memory",
        "project_id": None,
        "project_name": None,
        "type": "note",
        "title": "Memory",
        "content": "memory preview",
        "occurred_at": None,
        "score": 10.0,
    }


def test_post_chat_creates_conversation_and_messages(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    document = _ready_indexed_document(monkeypatch)

    response = _post_chat({"query": "What mentions alpha?", "document_id": document["id"]})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["conversation"]["title"] == "What mentions alpha?"
    assert data["user_message"]["role"] == "user"
    assert data["assistant_message"]["role"] == "assistant"
    assert data["assistant_message"]["sources"]
    assert data["assistant_message"]["memory_sources"] == []
    assert "content" not in data["assistant_message"]["sources"][0]
    assert "embedding" not in data["assistant_message"]["sources"][0]
    assert _counts()[1] >= 2


def test_post_chat_appends_to_existing_conversation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    first = _post_chat({"query": "first question"})
    conversation_id = first.json()["data"]["conversation"]["id"]

    second = _post_chat({"conversation_id": conversation_id, "query": "second question"})

    assert first.status_code == 200
    assert second.status_code == 200
    with TestClient(app) as client:
        messages = client.get(f"/api/conversations/{conversation_id}/messages")
    assert messages.status_code == 200
    assert [item["role"] for item in messages.json()["data"]["messages"]] == ["user", "assistant", "user", "assistant"]


def test_missing_conversation_returns_404(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)

    response = _post_chat({"conversation_id": str(uuid4()), "query": "hello"})

    assert response.status_code == 404


def test_empty_query_returns_400_without_writes(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    before = _counts()

    response = _post_chat({"query": "   "})

    assert response.status_code == 400
    assert _counts() == before


def test_rag_failure_does_not_write_half_messages(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    before = _counts()

    def fail_answer(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("forced internal failure")

    monkeypatch.setattr(chat_service, "answer_rag", fail_answer)

    response = _post_chat({"query": "will fail"})

    assert response.status_code == 400
    assert response.json()["detail"]["message"] == "Chat answer generation failed."
    assert "forced internal failure" not in response.text
    assert _counts() == before


def test_no_hits_chat_saves_no_evidence_answer(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)

    response = _post_chat({"query": "nothing indexed"})

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["assistant_message"]["content"] == NO_EVIDENCE_ANSWER
    assert data["assistant_message"]["sources"] == []
    assert data["assistant_message"]["memory_sources"] == []


def test_stream_chat_emits_tokens_and_saves_messages(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    before = _counts()

    with TestClient(app) as client:
        with client.stream("POST", "/api/chat/stream", json={"query": "stream nothing indexed"}) as response:
            body = "".join(response.iter_text())

    assert response.status_code == 200
    assert "event: sources" in body
    assert "event: token" in body
    assert "event: done" in body
    assert NO_EVIDENCE_ANSWER in body
    after = _counts()
    assert after[0] == before[0] + 1
    assert after[1] == before[1] + 2


def test_conversation_list_and_detail_endpoints(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    first = _post_chat({"query": "older conversation"}).json()["data"]["conversation"]
    second = _post_chat({"query": "newer conversation"}).json()["data"]["conversation"]

    with TestClient(app) as client:
        listing = client.get("/api/conversations?limit=50&offset=0")
        detail = client.get(f"/api/conversations/{second['id']}")
        messages = client.get(f"/api/conversations/{second['id']}/messages")

    assert listing.status_code == 200
    ids = [item["id"] for item in listing.json()["data"]["items"]]
    assert ids.index(second["id"]) < ids.index(first["id"])
    assert detail.status_code == 200
    assert detail.json()["data"]["id"] == second["id"]
    assert messages.status_code == 200
    assert len(messages.json()["data"]["messages"]) == 2


def test_sources_json_v2_old_array_and_invalid_json_are_compatible() -> None:
    with SessionLocal() as db:
        conversation = Conversation(title="sources parse", project_id=None)
        db.add(conversation)
        db.flush()
        old_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            content="old",
            sources_json=json.dumps([_source_payload()]),
        )
        v2_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            content="v2",
            sources_json=json.dumps(
                {
                    "version": 2,
                    "documents": [_source_payload()],
                    "memories": [_memory_source_payload()],
                }
            ),
        )
        invalid_message = Message(
            conversation_id=conversation.id,
            role="assistant",
            content="invalid",
            sources_json="{not json",
        )
        db.add_all([old_message, v2_message, invalid_message])
        db.commit()
        conversation_id = conversation.id

    with TestClient(app) as client:
        response = client.get(f"/api/conversations/{conversation_id}/messages")

    assert response.status_code == 200
    messages = response.json()["data"]["messages"]
    old = next(item for item in messages if item["content"] == "old")
    v2 = next(item for item in messages if item["content"] == "v2")
    invalid = next(item for item in messages if item["content"] == "invalid")
    assert old["sources"][0]["source_id"] == "S1"
    assert old["memory_sources"] == []
    assert v2["sources"][0]["source_id"] == "S1"
    assert v2["memory_sources"][0]["source_id"] == "M1"
    assert invalid["sources"] == []
    assert invalid["memory_sources"] == []


def test_rag_search_remains_stateless(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    before = _counts()

    with TestClient(app) as client:
        response = client.post("/api/rag/search", json={"query": "stateless"})

    assert response.status_code == 200
    assert _counts() == before
