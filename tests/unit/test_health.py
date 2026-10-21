"""測試目標：app.routers.health"""

from fastapi.testclient import TestClient


def test_health_returns_ok(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_unknown_route_uses_unified_error_format(client: TestClient) -> None:
    response = client.get("/not-exists")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
