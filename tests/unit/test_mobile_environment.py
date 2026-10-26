"""手機專用設定不能讓雲端降級，也不能將本機 API 改成遠端服務。"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import SecretStr

from app.core.environment import environment_report

CODE = "synthetic-mobile-code-for-unit-tests-only"


def configuration(**values: Any) -> SimpleNamespace:
    defaults = {
        "VERCEL": "",
        "VERCEL_ENV": "",
        "APP_ENV": "local",
        "DEBUG": False,
        "API_BASE_URL": "http://127.0.0.1:8100/api/v1",
        "LOCAL_HTTPS_ORIGIN": "https://mobile-test.trycloudflare.com",
        "LOCAL_MOBILE_ACCESS_CODE": SecretStr(CODE),
        "LOCAL_MOBILE_ORIGIN_FILE": "",
    }
    return SimpleNamespace(**(defaults | values))


def test_local_mobile_configuration_is_valid() -> None:
    assert environment_report(configuration(), "frontend")["configuration_valid"]


def test_pending_mobile_origin_uses_public_file_only(tmp_path: Path) -> None:
    settings = configuration(
        LOCAL_HTTPS_ORIGIN="", LOCAL_MOBILE_ORIGIN_FILE=str(tmp_path / "origin.json")
    )
    assert environment_report(settings, "frontend")["configuration_valid"]


@pytest.mark.parametrize(
    "values",
    [
        {"VERCEL": "1", "VERCEL_ENV": "production", "APP_ENV": "production"},
        {"LOCAL_HTTPS_ORIGIN": "http://mobile-test.trycloudflare.com"},
        {"LOCAL_HTTPS_ORIGIN": "https://mobile-test.trycloudflare.com/path"},
        {"LOCAL_HTTPS_ORIGIN": "https://user:synthetic-password@mobile-test.trycloudflare.com"},
        {"LOCAL_HTTPS_ORIGIN": "", "LOCAL_MOBILE_ORIGIN_FILE": ""},
        {"LOCAL_MOBILE_ACCESS_CODE": SecretStr("short")},
        {"API_BASE_URL": "https://api.example.invalid/api/v1"},
        {"API_BASE_URL": "http://127.0.0.1:8100/wrong-prefix"},
        {"API_BASE_URL": "http://["},
        {"LOCAL_MOBILE_ORIGIN_FILE": "../origin.json"},
    ],
)
def test_mobile_configuration_rejects_unsafe_values(values: dict[str, Any]) -> None:
    report = environment_report(configuration(**values), "frontend")
    assert not report["configuration_valid"]
    assert CODE not in repr(report)
