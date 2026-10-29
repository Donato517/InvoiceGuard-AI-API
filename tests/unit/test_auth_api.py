"""
模組名稱：tests.unit.test_auth_api
功能說明：測試前台呼叫之認證 API（POST /auth/login、POST /auth/logout、GET /auth/me）。
注意事項：以 repository 替身取代 v1.3 資料表，不連正式 DB。
"""

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.core import deps
from app.core.security import (
    hash_password,
    new_session_token,
    session_token_digest,
    verify_password,
)
from app.db.repositories import session_repository, user_repository
from app.db.repositories.session_repository import ActiveSession, NewSession
from app.db.repositories.user_repository import DepartmentRow, LoginAccount
from app.main import app

client = TestClient(app)

PASSWORD = "synthetic-password-for-tests"
USER_ID = UUID("11111111-1111-4111-8111-111111111111")
PRIMARY = DepartmentRow(uuid4(), "technology_d", "資訊部", True)
SECONDARY = DepartmentRow(uuid4(), "purchasing_d", "採購部", False)
EXPIRES_AT = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


@dataclass
class FakeIdentityStore:
    """記錄 repository 呼叫的替身；accounts 以 email 為鍵。"""

    accounts: dict[str, LoginAccount] = field(default_factory=dict)
    departments: list[DepartmentRow] = field(default_factory=lambda: [PRIMARY, SECONDARY])
    sessions: dict[bytes, ActiveSession] = field(default_factory=dict)
    lookups: list[str] = field(default_factory=list)
    created: list[dict[str, Any]] = field(default_factory=list)
    successes: list[UUID] = field(default_factory=list)
    failures: list[UUID] = field(default_factory=list)
    touched: list[UUID] = field(default_factory=list)
    revoked: list[bytes] = field(default_factory=list)


def make_account(**changes: Any) -> LoginAccount:
    values: dict[str, Any] = {
        "user_id": USER_ID,
        "email": "user@example.com",
        "password_hash": hash_password(PASSWORD),
        "account_status": "active",
        "credential_version": 3,
        "is_locked": False,
        "display_name": "測試使用者",
        "profile_active": True,
    }
    return LoginAccount(**(values | changes))


@pytest.fixture
def fake_db() -> Iterator[MagicMock]:
    db = MagicMock()

    def override() -> Iterator[MagicMock]:
        yield db

    app.dependency_overrides[deps.get_optional_db] = override
    yield db
    app.dependency_overrides.clear()


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch, fake_db: MagicMock) -> FakeIdentityStore:
    data = FakeIdentityStore(accounts={"user@example.com": make_account()})

    def get_login_account(db: Any, email: str) -> LoginAccount | None:
        data.lookups.append(email)
        return data.accounts.get(email)

    def create(db: Any, **values: Any) -> NewSession:
        data.created.append(values)
        data.sessions[values["digest"]] = ActiveSession(
            session_id=uuid4(),
            user_id=values["user_id"],
            selected_department_id=values["department_id"],
            expires_at=EXPIRES_AT,
            email="user@example.com",
            display_name="測試使用者",
        )
        return NewSession(session_id=uuid4(), expires_at=EXPIRES_AT)

    def revoke(db: Any, digest: bytes) -> bool:
        data.revoked.append(digest)
        return data.sessions.pop(digest, None) is not None

    monkeypatch.setattr(user_repository, "get_login_account", get_login_account)
    monkeypatch.setattr(user_repository, "list_departments", lambda db, uid: data.departments)
    monkeypatch.setattr(
        user_repository, "record_login_success", lambda db, uid: data.successes.append(uid)
    )
    monkeypatch.setattr(
        user_repository, "record_login_failure", lambda db, uid: data.failures.append(uid)
    )
    monkeypatch.setattr(session_repository, "create", create)
    monkeypatch.setattr(session_repository, "get_active", lambda db, d: data.sessions.get(d))
    monkeypatch.setattr(session_repository, "touch", lambda db, sid: data.touched.append(sid))
    monkeypatch.setattr(session_repository, "revoke", revoke)
    return data


def login(email: str = "user@example.com", password: str = PASSWORD) -> Any:
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ---- security ----
def test_password_hash_is_argon2id_phc_and_verifies() -> None:
    hashed = hash_password("secret_pass_123")
    assert hashed.startswith("$argon2id$v=19$")
    assert verify_password("secret_pass_123", hashed)
    assert not verify_password("wrong_pass", hashed)


def test_session_token_is_random_and_digest_matches_schema() -> None:
    token = new_session_token()
    assert token != new_session_token()
    assert len(token) >= 43  # 32 bytes 的 URL-safe Base64
    digest = session_token_digest(token)
    assert len(digest) == 32
    assert digest == hashlib.sha256(token.encode()).digest()


# ---- POST /auth/login ----
def test_login_creates_session_with_primary_department(
    store: FakeIdentityStore, fake_db: MagicMock
) -> None:
    response = login(email="  USER@Example.com ")

    assert response.status_code == 200
    data = response.json()
    assert store.lookups == ["user@example.com"]
    assert data["user_id"] == str(USER_ID)
    assert data["email"] == "user@example.com"
    assert data["display_name"] == "測試使用者"
    assert data["department"]["department_code"] == "technology_d"
    assert [row["department_code"] for row in data["departments"]] == [
        "technology_d",
        "purchasing_d",
    ]
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 3600
    assert "password_hash" not in response.text

    (created,) = store.created
    assert created["digest"] == session_token_digest(data["session_token"])
    assert created["user_id"] == USER_ID
    assert created["department_id"] == PRIMARY.department_id
    assert created["credential_version"] == 3
    assert created["expire_minutes"] == 60
    assert store.successes == [USER_ID]
    fake_db.commit.assert_called_once()


def test_login_wrong_password_records_failure_without_session(store: FakeIdentityStore) -> None:
    response = login(password="wrong-password")

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "帳號或密碼錯誤"
    assert store.failures == [USER_ID]
    assert store.created == []
    assert store.successes == []


def test_login_unknown_account_returns_same_message(store: FakeIdentityStore) -> None:
    response = login(email="unknown@example.com")

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "帳號或密碼錯誤"
    assert store.failures == []
    assert store.created == []


@pytest.mark.parametrize(
    "changes",
    [
        {"account_status": "disabled"},
        {"account_status": "pending"},
        {"is_locked": True},
        {"profile_active": False},
    ],
)
def test_ineligible_account_cannot_login(store: FakeIdentityStore, changes: dict[str, Any]) -> None:
    store.accounts["user@example.com"] = make_account(**changes)

    response = login()

    assert response.status_code == 401
    assert response.json()["error"]["message"] == "帳號或密碼錯誤"
    assert store.created == []


def test_login_requires_primary_department(store: FakeIdentityStore) -> None:
    store.departments = [SECONDARY]

    response = login()

    assert response.status_code == 401
    assert store.created == []


def test_login_without_database_returns_503() -> None:
    def no_db() -> Iterator[None]:
        yield None

    app.dependency_overrides[deps.get_optional_db] = no_db
    try:
        response = login()
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SERVICE_UNAVAILABLE"


def test_login_rejects_extra_fields(store: FakeIdentityStore) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": PASSWORD, "user_id": str(uuid4())},
    )
    assert response.status_code == 422
    assert PASSWORD not in response.text


# ---- GET /auth/me ----
def test_me_returns_user_and_selected_department(store: FakeIdentityStore) -> None:
    token = login().json()["session_token"]

    response = client.get("/api/v1/auth/me", headers=bearer(token))

    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == str(USER_ID)
    assert data["email"] == "user@example.com"
    assert data["department"]["department_id"] == str(PRIMARY.department_id)
    assert len(data["departments"]) == 2
    assert "session_token" not in data
    assert len(store.touched) == 1


def test_me_rejects_unknown_token(store: FakeIdentityStore) -> None:
    response = client.get("/api/v1/auth/me", headers=bearer("not-a-session"))
    assert response.status_code == 401
    assert store.touched == []


def test_me_rejects_when_selected_department_no_longer_valid(store: FakeIdentityStore) -> None:
    token = login().json()["session_token"]
    store.departments = [SECONDARY]

    response = client.get("/api/v1/auth/me", headers=bearer(token))

    assert response.status_code == 401
    assert store.touched == []


@pytest.mark.parametrize("header", [None, "Basic abc", "Bearer ", "token-only"])
def test_me_requires_bearer_token(store: FakeIdentityStore, header: str | None) -> None:
    headers = {"Authorization": header} if header is not None else {}
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 401


# ---- POST /auth/logout ----
def test_logout_revokes_session(store: FakeIdentityStore) -> None:
    token = login().json()["session_token"]

    response = client.post("/api/v1/auth/logout", headers=bearer(token))

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert store.revoked == [session_token_digest(token)]
    assert client.get("/api/v1/auth/me", headers=bearer(token)).status_code == 401


def test_logout_requires_bearer_token(store: FakeIdentityStore) -> None:
    response = client.post("/api/v1/auth/logout")
    assert response.status_code == 401
    assert store.revoked == []


def test_session_expiry_follows_setting(
    store: FakeIdentityStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "SESSION_EXPIRE_MINUTES", 30)
    data = login().json()
    assert data["expires_in"] == 1800
    assert store.created[0]["expire_minutes"] == 30
    assert datetime.fromisoformat(data["expires_at"]) - EXPIRES_AT == timedelta(0)
