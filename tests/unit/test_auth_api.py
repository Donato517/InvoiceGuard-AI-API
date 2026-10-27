"""
模組名稱：tests.unit.test_auth_api
功能說明：測試前台呼叫之認證 API（POST /auth/login、POST /logout、GET /me）。
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core import deps
from app.core.deps import get_db
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.repositories import user_repository
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_db_users(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_db = MagicMock()

    def fake_get_db():
        yield fake_db

    app.dependency_overrides[get_db] = fake_get_db
    app.dependency_overrides[deps.get_optional_db] = fake_get_db

    test_users = {
        "user@example.com": SimpleNamespace(
            id=1,
            email="user@example.com",
            password_hash=hash_password("password"),
            display_name="測試使用者",
            role="user",
            is_active=True,
            last_login_at=None,
        ),
        "admin@example.com": SimpleNamespace(
            id=2,
            email="admin@example.com",
            password_hash=hash_password("password"),
            display_name="測試管理者",
            role="admin",
            is_active=True,
            last_login_at=None,
        ),
    }

    monkeypatch.setattr(
        user_repository,
        "get_by_email",
        lambda db, email: test_users.get(email.strip().lower()),
    )
    monkeypatch.setattr(
        user_repository,
        "get_by_id",
        lambda db, user_id: next((u for u in test_users.values() if u.id == user_id), None),
    )
    monkeypatch.setattr(user_repository, "update_last_login", lambda db, user: None)

    yield
    app.dependency_overrides.clear()


def test_password_hash_and_verify() -> None:
    hashed = hash_password("secret_pass_123")
    assert verify_password("secret_pass_123", hashed)
    assert not verify_password("wrong_pass", hashed)


def test_jwt_token_round_trip() -> None:
    token, expires_in = create_access_token("99", {"email": "test@example.com", "role": "user"})
    assert isinstance(token, str)
    assert expires_in > 0

    payload = decode_access_token(token)
    assert payload["sub"] == "99"
    assert payload["email"] == "test@example.com"
    assert payload["role"] == "user"


def test_login_success_with_db_user() -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "password"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0


def test_login_success_with_db_admin() -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "password"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data


def test_login_wrong_password_returns_401() -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "wrong_password"},
    )
    assert response.status_code == 401
    assert "error" in response.json()


def test_login_nonexistent_account_returns_401() -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "unknown@example.com", "password": "password"},
    )
    assert response.status_code == 401


def test_get_me_success() -> None:
    login_resp = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "password"},
    )
    token = login_resp.json()["access_token"]

    me_resp = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_resp.status_code == 200
    data = me_resp.json()
    assert data["id"] == 1
    assert data["email"] == "user@example.com"
    assert data["display_name"] == "測試使用者"
    assert data["role"] == "user"
    assert data["is_active"] is True
    assert "password_hash" not in data


def test_get_me_unauthorized_without_header() -> None:
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 401


def test_logout_endpoint() -> None:
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
