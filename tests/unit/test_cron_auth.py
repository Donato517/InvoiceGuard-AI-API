"""測試目標：app.core.security.verify_cron_secret 對排程端點的保護"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings


@pytest.fixture
def cron_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = "test-cron-secret-123456"
    monkeypatch.setattr(settings, "CRON_SECRET", secret)
    return secret


def test_cron_rejects_missing_secret(client: TestClient, cron_secret: str) -> None:
    response = client.get("/api/cron/sync-einvoice")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"


def test_cron_rejects_wrong_secret(client: TestClient, cron_secret: str) -> None:
    response = client.get("/api/cron/sync-einvoice", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401


def test_cron_accepts_valid_secret(client: TestClient, cron_secret: str) -> None:
    response = client.get(
        "/api/cron/sync-einvoice", headers={"Authorization": f"Bearer {cron_secret}"}
    )

    assert response.status_code == 200
    assert response.json()["job"] == "sync_einvoice"


def test_cron_rejects_all_when_secret_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "CRON_SECRET", "")

    response = client.get("/api/cron/sync-einvoice", headers={"Authorization": "Bearer "})

    assert response.status_code == 401
