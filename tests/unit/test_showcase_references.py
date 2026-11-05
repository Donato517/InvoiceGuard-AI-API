"""範例取用：有效 Session、只讀啟用版、來源撤回及資料白名單。"""

from uuid import uuid4

import pytest

from app.core.exceptions import AppError, NotFoundError
from app.services import showcase_reference_service as service


def test_candidates_are_projected_without_private_revisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """回傳不含來源物件鍵、確認人與草稿。"""
    row = {
        "sample_id": uuid4(),
        "revision": {
            "id": str(uuid4()),
            "title": "範例",
            "tax_id": "12345678",
            "truths": [],
            "source": {"key": "secret-key"},
            "confirmed_by": "private-actor",
        },
    }
    monkeypatch.setattr(service.repository, "candidates", lambda *args: [row])
    result = service.candidates(object(), "12345678", "")
    assert result[0]["title"] == "範例"
    assert "secret-key" not in str(result) and "private-actor" not in str(result)
    with pytest.raises(AppError):
        service.candidates(object(), "invalid", "")


def test_disabled_source_does_not_call_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """停用或被取代後，舊網址不能再次取得圖片。"""
    monkeypatch.setattr(service.repository, "source", lambda *args: None)
    monkeypatch.setattr(
        service.S3StorageClient, "from_settings", lambda **kwargs: pytest.fail("不應讀取 Storage")
    )
    with pytest.raises(NotFoundError):
        service.source(object(), uuid4(), uuid4())


def test_reference_routes_verify_session_before_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """前台取用使用既有 Session 驗證，不接受任意 UUID 身分。"""
    from fastapi.testclient import TestClient

    from app.core.exceptions import UnauthorizedError
    from app.main import app
    from app.routers.v1 import showcase_references as router

    def reject(*args: object) -> None:
        raise UnauthorizedError("請登入")

    monkeypatch.setattr(router.auth_service, "resolve_session", reject)
    monkeypatch.setattr(router.service, "candidates", lambda *args: pytest.fail("未登入不得搜尋"))
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/showcase-references?tax_id=12345678",
            headers={"Authorization": "Bearer synthetic"},
        )
        assert response.status_code == 401
