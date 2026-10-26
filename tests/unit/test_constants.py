"""三站共用常數 app.core.constants：網址、環境判斷、名稱、圖示與搜尋引擎設定；不連網、不讀機密。"""

import json

import pytest
from fastapi.testclient import TestClient

from app.core import config, constants


def test_production_urls_are_the_three_public_platforms() -> None:
    assert constants.PRODUCTION == {
        "FRONTEND_URL": "https://invoice-guard-ai.vercel.app",
        "API_URL": "https://invoice-guard-ai-api.vercel.app",
        "ADMIN_URL": "https://invoice-guard-ai-admin.vercel.app",
    }
    # 本機區塊與正式區塊使用相同名稱，程式不必依環境改寫欄位名稱。
    assert set(constants.LOCAL) == set(constants.PRODUCTION)


def test_current_uses_production_on_vercel_and_local_otherwise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.settings, "VERCEL", "")
    assert constants.current() == constants.LOCAL
    monkeypatch.setattr(config.settings, "VERCEL", "1")
    assert constants.current() == constants.PRODUCTION


def test_current_returns_a_copy_that_cannot_change_the_file_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config.settings, "VERCEL", "")
    before = dict(constants.LOCAL)
    urls = constants.current()
    urls["FRONTEND_URL"] = "http://changed.localhost"
    assert before == constants.LOCAL


def test_site_names_and_robots_policy_are_shared_values() -> None:
    assert set(constants.SITE_NAMES) == {"FRONTEND", "ADMIN", "API"}
    assert constants.ROBOTS_POLICY == "noindex, nofollow"
    # 不只拒絕 Disallow：空白或缺少 User-agent 的內容也不是核定的 robots.txt。
    assert constants.ROBOTS_TXT == "User-agent: *\nAllow: /\n"


def test_vercel_header_uses_the_shared_robots_policy() -> None:
    vercel = json.loads((config.BASE_DIR / "vercel.json").read_text(encoding="utf-8"))
    headers = {
        header["key"]: header["value"]
        for rule in vercel["headers"]
        if rule["source"] == "/(.*)"
        for header in rule["headers"]
    }
    assert headers["X-Robots-Tag"] == constants.ROBOTS_POLICY


def test_robots_txt_serves_the_shared_content(client: TestClient) -> None:
    response = client.get("/robots.txt")
    assert response.status_code == 200
    assert response.text == constants.ROBOTS_TXT
    assert response.headers["content-type"].split(";", 1)[0] == "text/plain"


def test_pages_carry_noindex_shared_icon_and_site_name(client: TestClient) -> None:
    platform = {
        "InvoiceGuard-AI": "FRONTEND",
        "InvoiceGuard-AI-ADMIN": "ADMIN",
        "InvoiceGuard-AI-API": "API",
    }[config.Settings.model_fields["APP_NAME"].default]
    if platform == "API":
        # API 只回 JSON、沒有網頁；不被收錄由 vercel.json 的 X-Robots-Tag 標頭負責。
        assert not (config.BASE_DIR / "app" / "templates").exists()
        assert not (config.BASE_DIR / "app" / "static").exists()
        return
    assert (config.BASE_DIR / "app" / "templates").is_dir()
    from app.constants import SITE_NAME

    page = client.get("/login")
    assert page.status_code == 200
    assert f'<meta name="robots" content="{constants.ROBOTS_POLICY}">' in page.text
    assert f"/static/{constants.SITE_ICON}" in page.text
    assert constants.SITE_NAMES[platform] == SITE_NAME
    assert SITE_NAME in page.text
    assert (config.BASE_DIR / "app" / "static" / constants.SITE_ICON).is_file()
