from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


def test_create_project_trims_name_and_returns_fixed_fields() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/projects",
            json={"name": "  Stage 3 Project  ", "description": "  docs  "},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["code"] == "OK"
    assert set(body["data"].keys()) == {"id", "name", "description", "created_at", "updated_at"}
    assert body["data"]["name"] == "Stage 3 Project"
    assert body["data"]["description"] == "docs"


def test_create_project_rejects_empty_trimmed_name() -> None:
    with TestClient(app) as client:
        response = client.post("/api/projects", json={"name": "   ", "description": None})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "BAD_REQUEST"


def test_create_project_rejects_overlong_fields() -> None:
    with TestClient(app) as client:
        long_name = client.post("/api/projects", json={"name": "x" * 101})
        long_description = client.post(
            "/api/projects",
            json={"name": "Long Description Project", "description": "d" * 1001},
        )

    assert long_name.status_code == 400
    assert long_description.status_code == 400


def test_create_project_rejects_duplicate_name() -> None:
    with TestClient(app) as client:
        first = client.post("/api/projects", json={"name": "Duplicate Project"})
        second = client.post("/api/projects", json={"name": "  Duplicate Project  "})

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "CONFLICT"


def test_project_edit_and_delete_routes_are_not_implemented() -> None:
    with TestClient(app) as client:
        delete_collection = client.delete("/api/projects")
        patch_item = client.patch("/api/projects/does-not-exist", json={"name": "Nope"})

    assert delete_collection.status_code == 405
    assert patch_item.status_code == 404
