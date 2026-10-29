"""API 環境隔離：只使用假設定，不建立 DB、HTTP 或模型服務連線。"""

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from app.core import config
from app.core.config import Settings
from app.core.environment import EnvironmentConfigurationError


def make_settings(**values: Any) -> Settings:
    return Settings(_env_prefix="IG_UNIT_TEST_", **values)


def test_api_local_environment_can_start_without_company_keys() -> None:
    configuration = make_settings()
    assert configuration.check_environment()["configuration_valid"]
    configuration.require_environment()


@pytest.mark.parametrize("deployment", ["preview", "production"])
def test_api_cloud_runtime_check_needs_no_company_keys(deployment: str) -> None:
    configuration = make_settings(VERCEL="1", VERCEL_ENV=deployment, APP_ENV=deployment)
    assert configuration.check_environment()["configuration_valid"]
    assert not configuration.check_environment()["connectivity_checked"]


@pytest.mark.parametrize(
    "values",
    [
        {"VERCEL": "1", "VERCEL_ENV": "production", "APP_ENV": "local"},
        {"VERCEL": "1", "VERCEL_ENV": "production", "APP_ENV": "preview"},
        {"VERCEL": "1", "APP_ENV": "production"},
        {"VERCEL_ENV": "production", "APP_ENV": "production"},
        {"APP_ENV": "production"},
    ],
)
def test_api_inconsistent_runtime_is_rejected(values: dict[str, Any]) -> None:
    configuration = make_settings(**values)
    assert not configuration.check_environment()["configuration_valid"]
    with pytest.raises(EnvironmentConfigurationError):
        configuration.require_environment()


def test_api_database_capability_also_checks_runtime_consistency() -> None:
    configuration = make_settings(
        VERCEL="1",
        VERCEL_ENV="production",
        APP_ENV="preview",
        DATABASE_URL="postgresql://test:synthetic@db.example.invalid/test?sslmode=require",
    )
    report = configuration.check_configuration("database")
    assert not report.is_valid
    assert any(issue.field == "APP_ENV" for issue in report.issues)


def test_api_capability_report_does_not_duplicate_secret_issue() -> None:
    # DATABASE_URL 依核定可在本機使用，改以其他公司機密驗證不重複回報
    configuration = make_settings(JWT_SECRET_KEY="synthetic-secret")
    report = configuration.check_configuration("local")
    issues = [
        issue
        for issue in report.issues
        if issue.field == "JWT_SECRET_KEY" and issue.code == "cloud_secret_in_local"
    ]
    assert len(issues) == 1


def test_start_injected_google_ai_settings_are_allowed_locally() -> None:
    # 2026-10-28 使用者核定：START 注入本機 API 的 Google AI 設定不視為本機禁用機密
    configuration = make_settings(
        GEMINI_API_KEY="synthetic-gemini-key",
        GOOGLE_SERVICE_ACCOUNT_JSON='{"type": "service_account"}',
        GOOGLE_CLOUD_PROJECT_ID="synthetic-project",
        GOOGLE_CLOUD_LOCATION="us",
        DOCUMENT_AI_PROCESSOR_ID="0123456789abcdef",
    )
    report = configuration.check_environment()
    assert report["configuration_valid"]
    local = configuration.check_configuration("local")
    assert not any(issue.code == "cloud_secret_in_local" for issue in local.issues)


def test_secrets_not_injected_by_start_are_still_rejected_locally() -> None:
    configuration = make_settings(
        GEMINI_API_KEY="synthetic-gemini-key", CRON_SECRET="synthetic-cron-secret"
    )
    report = configuration.check_environment()
    assert not report["configuration_valid"]
    fields = {issue["field"] for issue in report["issues"] if issue["severity"] == "error"}
    assert fields == {"CRON_SECRET"}


def test_api_main_rejects_invalid_environment_before_app_assembly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configuration = make_settings(VERCEL="1", VERCEL_ENV="production", APP_ENV="local")
    monkeypatch.setattr(config, "settings", configuration)
    source = Path(config.BASE_DIR) / "app" / "main.py"
    spec = importlib.util.spec_from_file_location("_api_invalid_environment", source)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(EnvironmentConfigurationError):
        spec.loader.exec_module(module)
    assert "app" not in vars(module)
