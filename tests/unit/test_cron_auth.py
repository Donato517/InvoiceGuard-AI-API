"""測試目標：app.core.security.verify_cron_secret 對排程端點的保護"""

import logging
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.exceptions import UnauthorizedError
from app.core.security import verify_cron_secret
from app.jobs import sync_einvoice


@pytest.fixture(autouse=True)
def cron_job(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """只驗證排程授權，不執行真實工作。"""
    job = MagicMock(return_value={"stubbed": True})
    monkeypatch.setattr(sync_einvoice, "run", job)
    return job


@pytest.fixture
def cron_secret(monkeypatch: pytest.MonkeyPatch) -> str:
    secret = "test-cron-secret-123456"
    monkeypatch.setattr(settings, "CRON_SECRET", secret)
    return secret


def test_cron_rejects_missing_secret(
    client: TestClient, cron_secret: str, cron_job: MagicMock
) -> None:
    response = client.get("/api/cron/sync-einvoice")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "UNAUTHORIZED"
    cron_job.assert_not_called()


def test_cron_rejects_wrong_secret(
    client: TestClient, cron_secret: str, cron_job: MagicMock
) -> None:
    response = client.get("/api/cron/sync-einvoice", headers={"Authorization": "Bearer wrong"})

    assert response.status_code == 401
    cron_job.assert_not_called()


def test_cron_accepts_valid_secret(
    client: TestClient, cron_secret: str, cron_job: MagicMock
) -> None:
    response = client.get(
        "/api/cron/sync-einvoice", headers={"Authorization": f"Bearer {cron_secret}"}
    )

    assert response.status_code == 200
    assert response.json()["job"] == "sync_einvoice"
    assert response.json()["result"] == {"stubbed": True}
    cron_job.assert_called_once_with()


def test_cron_rejects_all_when_secret_not_configured(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "CRON_SECRET", "")

    response = client.get("/api/cron/sync-einvoice", headers={"Authorization": "Bearer "})

    assert response.status_code == 401


def test_masked_secret_representation_is_not_a_credential(
    client: TestClient, cron_secret: str, cron_job: MagicMock
) -> None:
    response = client.get("/api/cron/sync-einvoice", headers={"Authorization": "Bearer **********"})
    assert response.status_code == 401
    cron_job.assert_not_called()


def test_local_environment_does_not_bypass_cron_auth(
    monkeypatch: pytest.MonkeyPatch, cron_secret: str
) -> None:
    monkeypatch.setattr(settings, "APP_ENV", "local")
    with pytest.raises(UnauthorizedError):
        verify_cron_secret(None)


@pytest.mark.parametrize("secret", ["", "short"])
def test_cloud_invalid_cron_configuration_is_unauthorized(
    monkeypatch: pytest.MonkeyPatch, secret: str
) -> None:
    monkeypatch.setattr(settings, "VERCEL", "1")
    monkeypatch.setattr(settings, "APP_ENV", "preview")
    monkeypatch.setattr(settings, "CRON_SECRET", secret)
    with pytest.raises(UnauthorizedError):
        verify_cron_secret("Bearer " + secret)


def test_cloud_configuration_rejection_is_logged_without_values(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture, cron_secret: str
) -> None:
    # Vercel 不會自動設定 APP_ENV；保留預設 local 時，合法密鑰仍被拒並留下原因
    monkeypatch.setattr(settings, "VERCEL", "1")
    with (
        caplog.at_level(logging.WARNING, logger="app.core.security"),
        pytest.raises(UnauthorizedError),
    ):
        verify_cron_secret("Bearer " + cron_secret)
    assert "APP_ENV:cloud_environment_required" in caplog.text
    assert cron_secret not in caplog.text


def test_cloud_valid_cron_secret_still_requires_matching_header(
    monkeypatch: pytest.MonkeyPatch, cron_secret: str
) -> None:
    monkeypatch.setattr(settings, "VERCEL", "1")
    monkeypatch.setattr(settings, "APP_ENV", "preview")
    with pytest.raises(UnauthorizedError):
        verify_cron_secret("Bearer different-synthetic-secret")
    verify_cron_secret("Bearer " + cron_secret)
