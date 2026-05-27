from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import app


EXPECTED_BODY = {
    "success": False,
    "code": "NOT_IMPLEMENTED",
    "message": "This API is reserved for later stages.",
    "data": None,
}


def test_reserved_routes_return_501() -> None:
    cases: list[tuple[str, str]] = []

    with TestClient(app) as client:
        for method, path in cases:
            response = client.request(method, path)
            assert response.status_code == 501
            assert response.json() == EXPECTED_BODY
