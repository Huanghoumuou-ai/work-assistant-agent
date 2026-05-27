from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from backend.app.core.config import settings
from backend.app.db.models import Memory, MemorySuggestion
from backend.app.db.session import SessionLocal
from backend.app.main import app


def _create_project(name: str | None = None) -> dict:
    with TestClient(app) as client:
        response = client.post(
            "/api/projects",
            json={"name": name or f"Memory Project {uuid4().hex[:8]}", "description": None},
        )
    assert response.status_code == 200
    return response.json()["data"]


def _create_memory(payload: dict) -> dict:
    with TestClient(app) as client:
        response = client.post("/api/memory", json=payload)
    assert response.status_code == 200
    return response.json()["data"]


def _memory_count() -> int:
    with SessionLocal() as db:
        return db.query(Memory).count()


def _suggestion_count() -> int:
    with SessionLocal() as db:
        return db.query(MemorySuggestion).count()


def _use_fake_stack(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(settings, "embedding_provider", "fake")
    monkeypatch.setattr(settings, "llm_provider", "fake")
    monkeypatch.setattr(settings, "chroma_collection_name", f"memory_{uuid4().hex}")


def test_create_manual_memory_success_and_backend_source_fields() -> None:
    project = _create_project()
    memory = _create_memory(
        {
            "project_id": project["id"],
            "type": "requirement",
            "title": "  Launch rule  ",
            "content": "  Keep sources visible.  ",
            "occurred_at": "2026-05-01T08:30:00+08:00",
        }
    )

    assert memory["project_id"] == project["id"]
    assert memory["project_name"] == project["name"]
    assert memory["title"] == "Launch rule"
    assert memory["content"] == "Keep sources visible."
    assert memory["status"] == "active"
    assert memory["source_type"] == "manual"
    assert memory["source_ref"] is None
    assert memory["occurred_at"].startswith("2026-05-01T00:30:00")


def test_create_memory_with_null_occurred_at_succeeds() -> None:
    memory = _create_memory(
        {
            "project_id": None,
            "type": "note",
            "title": "No occurred at",
            "content": "Created time is enough.",
            "occurred_at": None,
        }
    )

    assert memory["occurred_at"] is None


def test_create_memory_validation_errors() -> None:
    with TestClient(app) as client:
        empty_title = client.post("/api/memory", json={"type": "note", "title": " ", "content": "x"})
        empty_content = client.post("/api/memory", json={"type": "note", "title": "x", "content": " "})
        long_title = client.post("/api/memory", json={"type": "note", "title": "x" * 121, "content": "x"})
        long_content = client.post("/api/memory", json={"type": "note", "title": "x", "content": "x" * 5001})
        invalid_type = client.post("/api/memory", json={"type": "idea", "title": "x", "content": "x"})
        missing_project = client.post("/api/memory", json={"project_id": str(uuid4()), "type": "note", "title": "x", "content": "x"})

    assert empty_title.status_code == 400
    assert empty_content.status_code == 400
    assert long_title.status_code == 400
    assert long_content.status_code == 400
    assert invalid_type.status_code == 400
    assert missing_project.status_code == 400


def test_list_status_filters_project_type_pagination_and_sorting() -> None:
    project = _create_project()
    older = _create_memory(
        {
            "project_id": project["id"],
            "type": "decision",
            "title": "Older decision",
            "content": "older",
            "occurred_at": "2026-05-01T00:00:00Z",
        }
    )
    newer = _create_memory(
        {
            "project_id": project["id"],
            "type": "decision",
            "title": "Newer decision",
            "content": "newer",
            "occurred_at": "2026-05-03T00:00:00Z",
        }
    )
    archived = _create_memory(
        {
            "project_id": project["id"],
            "type": "rule",
            "title": "Archived rule",
            "content": "archived",
            "occurred_at": None,
        }
    )
    with TestClient(app) as client:
        archive_response = client.patch(f"/api/memory/{archived['id']}/status", json={"status": "archived"})
        default_response = client.get(f"/api/memory?project_id={project['id']}")
        archived_response = client.get(f"/api/memory?project_id={project['id']}&status=archived")
        all_response = client.get(f"/api/memory?project_id={project['id']}&status=all")
        type_response = client.get(f"/api/memory?project_id={project['id']}&type=decision&status=all")
        paged_response = client.get(f"/api/memory?project_id={project['id']}&status=all&limit=1&offset=1")

    assert archive_response.status_code == 200
    assert [item["id"] for item in default_response.json()["data"]["items"]] == [newer["id"], older["id"]]
    assert [item["id"] for item in archived_response.json()["data"]["items"]] == [archived["id"]]
    assert {item["id"] for item in all_response.json()["data"]["items"]} == {older["id"], newer["id"], archived["id"]}
    assert {item["id"] for item in type_response.json()["data"]["items"]} == {older["id"], newer["id"]}
    assert paged_response.json()["data"]["limit"] == 1
    assert paged_response.json()["data"]["offset"] == 1


def test_invalid_status_filter_and_missing_memory_return_errors() -> None:
    with TestClient(app) as client:
        invalid_status = client.get("/api/memory?status=deleted")
        missing = client.get(f"/api/memory/{uuid4()}")

    assert invalid_status.status_code == 400
    assert missing.status_code == 404


def test_memory_search_uses_lexical_rules_filters_and_escaping() -> None:
    token = f"alpha{uuid4().hex[:8]}"
    project = _create_project()
    title_hit = _create_memory(
        {
            "project_id": project["id"],
            "type": "note",
            "title": f"{token} title match",
            "content": "lower priority",
            "occurred_at": "2026-05-01T00:00:00Z",
        }
    )
    content_hit = _create_memory(
        {
            "project_id": project["id"],
            "type": "note",
            "title": "Content match only",
            "content": f"{token} appears here",
            "occurred_at": "2026-05-03T00:00:00Z",
        }
    )
    archived = _create_memory(
        {
            "project_id": project["id"],
            "type": "note",
            "title": f"{token} archived",
            "content": "archived",
        }
    )
    literal = _create_memory({"type": "rule", "title": "Budget 100%_literal", "content": "literal symbols"})
    _create_memory({"type": "rule", "title": "Budget 100 percent literal", "content": "decoy"})

    with TestClient(app) as client:
        assert client.patch(f"/api/memory/{archived['id']}/status", json={"status": "archived"}).status_code == 200
        active = client.post("/api/memory/search", json={"query": token, "project_id": project["id"], "limit": 10})
        all_statuses = client.post(
            "/api/memory/search",
            json={"query": token, "project_id": project["id"], "limit": 10, "include_archived": True},
        )
        typed = client.post("/api/memory/search", json={"query": token, "types": ["note"], "limit": 10})
        escaped = client.post("/api/memory/search", json={"query": "100%_literal", "types": ["rule"], "limit": 10})
        chinese = client.post("/api/memory/search", json={"query": "中文阶段"})
        empty = client.post("/api/memory/search", json={"query": "   "})

    assert active.status_code == 200
    active_ids = [item["memory"]["id"] for item in active.json()["data"]["items"]]
    assert active_ids[:2] == [title_hit["id"], content_hit["id"]]
    assert archived["id"] not in active_ids

    all_ids = {item["memory"]["id"] for item in all_statuses.json()["data"]["items"]}
    assert archived["id"] in all_ids
    typed_ids = {item["memory"]["id"] for item in typed.json()["data"]["items"]}
    assert title_hit["id"] in typed_ids
    escaped_ids = [item["memory"]["id"] for item in escaped.json()["data"]["items"]]
    assert escaped_ids == [literal["id"]]
    assert chinese.status_code == 200
    assert empty.status_code == 400


def test_patch_memory_edits_allowed_fields_and_rejects_reserved_fields() -> None:
    project = _create_project()
    memory = _create_memory({"type": "note", "title": "Before", "content": "Before content"})

    with TestClient(app) as client:
        updated = client.patch(
            f"/api/memory/{memory['id']}",
            json={
                "project_id": project["id"],
                "type": "rule",
                "title": "After",
                "content": "After content",
                "occurred_at": "2026-05-02T00:00:00Z",
            },
        )
        forbidden_source_type = client.patch(f"/api/memory/{memory['id']}", json={"source_type": "chat"})
        forbidden_source_ref = client.patch(f"/api/memory/{memory['id']}", json={"source_ref": "x"})
        forbidden_created_at = client.patch(f"/api/memory/{memory['id']}", json={"created_at": "2026-05-01T00:00:00Z"})
        null_title = client.patch(f"/api/memory/{memory['id']}", json={"title": None})

    assert updated.status_code == 200
    data = updated.json()["data"]
    assert data["project_id"] == project["id"]
    assert data["type"] == "rule"
    assert data["title"] == "After"
    assert data["content"] == "After content"
    assert data["source_type"] == "manual"
    assert data["source_ref"] is None
    assert forbidden_source_type.status_code == 422
    assert forbidden_source_ref.status_code == 422
    assert forbidden_created_at.status_code == 422
    assert null_title.status_code == 400


def test_patch_memory_status_archives_and_restores() -> None:
    memory = _create_memory({"type": "note", "title": "Status memory", "content": "status"})

    with TestClient(app) as client:
        archived = client.patch(f"/api/memory/{memory['id']}/status", json={"status": "archived"})
        restored = client.patch(f"/api/memory/{memory['id']}/status", json={"status": "active"})
        invalid = client.patch(f"/api/memory/{memory['id']}/status", json={"status": "deleted"})

    assert archived.status_code == 200
    assert archived.json()["data"]["status"] == "archived"
    assert restored.status_code == 200
    assert restored.json()["data"]["status"] == "active"
    assert invalid.status_code == 400


def test_chat_and_rag_do_not_create_memories(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    _create_memory({"type": "note", "title": "No write check", "content": "manual memory context"})
    before = _memory_count()

    with TestClient(app) as client:
        chat = client.post("/api/chat", json={"query": "manual memory", "include_memory": True})
        rag = client.post("/api/rag/search", json={"query": "manual memory", "include_memory": True})

    assert chat.status_code == 200
    assert rag.status_code == 200
    assert _memory_count() == before


def test_generate_accept_and_reject_memory_suggestions_from_conversation(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    before_memory = _memory_count()
    before_suggestion = _suggestion_count()
    with TestClient(app) as client:
        chat = client.post("/api/chat", json={"query": "Remember that release notes need review."})
    assert chat.status_code == 200
    conversation_id = chat.json()["data"]["conversation"]["id"]

    with TestClient(app) as client:
        generated = client.post("/api/memory/suggestions/from-conversation", json={"conversation_id": conversation_id, "limit": 2})
        listing = client.get("/api/memory/suggestions?status=pending")

    assert generated.status_code == 202
    suggestions = generated.json()["data"]["items"]
    assert suggestions
    assert suggestions[0]["status"] == "pending"
    assert suggestions[0]["source_type"] == "chat_suggestion"
    assert suggestions[0]["conversation_id"] == conversation_id
    assert listing.status_code == 200
    assert _memory_count() == before_memory
    assert _suggestion_count() == before_suggestion + len(suggestions)

    suggestion_id = suggestions[0]["id"]
    with TestClient(app) as client:
        accepted = client.post(f"/api/memory/suggestions/{suggestion_id}/accept")

    assert accepted.status_code == 200
    assert accepted.json()["data"]["suggestion"]["status"] == "accepted"
    assert accepted.json()["data"]["memory"]["source_type"] == "suggestion"
    assert _memory_count() == before_memory + 1

    with TestClient(app) as client:
        second = client.post("/api/memory/suggestions/from-conversation", json={"conversation_id": conversation_id, "limit": 1}).json()["data"]["items"][0]
        rejected = client.post(f"/api/memory/suggestions/{second['id']}/reject")

    assert rejected.status_code == 200
    assert rejected.json()["data"]["status"] == "rejected"


def test_generate_memory_suggestions_from_document_uses_parsed_text_and_existing_memory(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    _create_memory({"type": "rule", "title": "Existing rule", "content": "Keep citations attached to recommendations."})
    with TestClient(app) as client:
        upload = client.post("/api/upload", files={"file": ("suggestions.md", b"# Release\nReview launch risks.", "text/markdown")})
    assert upload.status_code == 200
    document_id = upload.json()["data"]["id"]
    with TestClient(app) as client:
        assert client.post(f"/api/documents/{document_id}/parse").status_code == 200
        generated = client.post("/api/memory/suggestions/from-document", json={"document_id": document_id, "limit": 3, "include_memory": True})

    assert generated.status_code == 202
    suggestions = generated.json()["data"]["items"]
    assert suggestions
    assert suggestions[0]["source_type"] == "document_suggestion"
    assert suggestions[0]["source_ref"] == document_id
    assert suggestions[0]["status"] == "pending"


def test_generate_memory_suggestions_from_text_uses_project_and_does_not_write_memory(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    with TestClient(app) as client:
        project = client.post("/api/projects", json={"name": "Suggestion Text Project"}).json()["data"]
    _create_memory({"project_id": project["id"], "type": "note", "title": "Existing context", "content": "Use the launch checklist."})
    before_memory = _memory_count()

    with TestClient(app) as client:
        generated = client.post(
            "/api/memory/suggestions/from-text",
            json={
                "title": "Launch notes",
                "content": "Launch notes say support needs a rollback checklist and owner.",
                "project_id": project["id"],
                "limit": 2,
                "include_memory": True,
            },
        )

    assert generated.status_code == 202
    suggestions = generated.json()["data"]["items"]
    assert suggestions
    assert suggestions[0]["source_type"] == "text_suggestion"
    assert suggestions[0]["source_ref"] == "Launch notes"
    assert suggestions[0]["project_id"] == project["id"]
    assert suggestions[0]["status"] == "pending"
    assert _memory_count() == before_memory


def test_generate_memory_suggestions_from_text_validates_content_and_project(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    with TestClient(app) as client:
        empty = client.post("/api/memory/suggestions/from-text", json={"content": "   "})
        missing_project = client.post("/api/memory/suggestions/from-text", json={"content": "useful text", "project_id": "missing"})

    assert empty.status_code == 400
    assert missing_project.status_code == 400


def test_memory_suggestion_generation_requires_parsed_uploaded_document(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    _use_fake_stack(monkeypatch)
    with TestClient(app) as client:
        upload = client.post("/api/upload", files={"file": ("unparsed.md", b"unparsed", "text/markdown")})
    document_id = upload.json()["data"]["id"]

    with TestClient(app) as client:
        unparsed = client.post("/api/memory/suggestions/from-document", json={"document_id": document_id})
        client.patch(f"/api/documents/{document_id}/status", json={"status": "archived"})
        archived = client.post("/api/memory/suggestions/from-document", json={"document_id": document_id})

    assert unparsed.status_code == 400
    assert archived.status_code == 400
