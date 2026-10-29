"""三站相同的環境邊界案例；全部使用合成值並禁止外部連線。"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from app.core import config, environment

PLATFORM = {
    "InvoiceGuard-AI": "frontend",
    "InvoiceGuard-AI-ADMIN": "admin",
    "InvoiceGuard-AI-API": "api",
}[config.settings.APP_NAME]
URL_FIELD = next(iter(environment.LOCAL_URL_FIELDS[PLATFORM]))
MARKER = "synthetic-secret-marker"


def make_settings(**values: Any) -> Any:
    return config.Settings(_env_prefix="IG_ENV_TEST_", **values)


def cloud_settings(**values: Any) -> Any:
    defaults: dict[str, Any] = {
        "VERCEL": "1",
        "VERCEL_ENV": "production",
        "APP_ENV": "production",
    }
    if PLATFORM == "frontend":
        defaults["API_BASE_URL"] = "https://api.example.invalid/api/v1"
    return make_settings(**(defaults | values))


@pytest.fixture
def local_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    repo = tmp_path / "repository"
    repo.mkdir()
    monkeypatch.setattr(config, "BASE_DIR", repo)
    startup = tmp_path / "InvoiceGuard-STARTUP"
    startup.mkdir()
    return startup / "dev-urls.local.json"


def public_document() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "frontend": {"API_BASE_URL": "http://127.0.0.1:9000/api/v1"},
        "admin": {"REMOTE_ADMIN_BASE_URL": "https://admin-dev.example.invalid"},
        "api": {"REMOTE_API_BASE_URL": "https://api-dev.example.invalid"},
    }


def test_local_public_url_is_loaded(local_root: Path) -> None:
    data = public_document()
    local_root.write_text(json.dumps(data), encoding="utf-8")
    settings = make_settings()
    assert getattr(settings, URL_FIELD) == data[PLATFORM][URL_FIELD]
    assert settings.check_environment()["configuration_valid"]


def test_environment_overrides_constructor_and_local_file(
    local_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_root.write_text(json.dumps(public_document()), encoding="utf-8")
    monkeypatch.setenv("IG_ENV_TEST_" + URL_FIELD, "https://environment.example.invalid/api/v1")
    settings = make_settings(**{URL_FIELD: "https://constructor.example.invalid/api/v1"})
    assert getattr(settings, URL_FIELD) == "https://environment.example.invalid/api/v1"


def test_constructor_overrides_local_file(local_root: Path) -> None:
    local_root.write_text(json.dumps(public_document()), encoding="utf-8")
    settings = make_settings(**{URL_FIELD: "https://constructor.example.invalid/api/v1"})
    assert getattr(settings, URL_FIELD) == "https://constructor.example.invalid/api/v1"


@pytest.mark.parametrize("app_env", ["preview", "production"])
def test_cloud_never_calls_local_file_loader(
    local_root: Path, monkeypatch: pytest.MonkeyPatch, app_env: str
) -> None:
    local_root.write_text("{ " + MARKER, encoding="utf-8")

    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("雲端不得讀取本機檔案")

    monkeypatch.setattr(environment, "load_local_urls", forbidden)
    settings = cloud_settings(APP_ENV=app_env, VERCEL_ENV=app_env)
    assert settings.check_environment()["configuration_valid"]
    assert settings.check_environment()["local_file_ignored"]


def test_cloud_marker_cannot_fall_back_to_local_settings(
    local_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("不完整的雲端旗標也不得讀取本機檔案")

    monkeypatch.setattr(environment, "load_local_urls", forbidden)
    settings = make_settings(VERCEL="1")
    assert not settings.check_environment()["configuration_valid"]
    if PLATFORM == "frontend":
        assert settings.API_BASE_URL == ""


def test_platform_flags_from_environment_cannot_be_downgraded(
    local_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    local_root.write_text("{ " + MARKER, encoding="utf-8")
    for name, value in {
        "VERCEL": "1",
        "VERCEL_ENV": "production",
        "APP_ENV": "production",
    }.items():
        monkeypatch.setenv("IG_ENV_TEST_" + name, value)
    settings = make_settings(
        VERCEL="",
        VERCEL_ENV="",
        APP_ENV="local",
        **(
            {"API_BASE_URL": "https://api.example.invalid/api/v1"} if PLATFORM == "frontend" else {}
        ),
    )
    assert settings.APP_ENV == settings.VERCEL_ENV == "production"
    assert settings.VERCEL == "1"
    assert settings.check_environment()["configuration_valid"]


def test_dotenv_and_secret_directory_overrides_are_never_sources(local_root: Path) -> None:
    dotenv = local_root.parent / ".env"
    dotenv.write_text(
        f"{URL_FIELD}=https://{MARKER}.example.invalid\nAPP_ENV=production\n", encoding="utf-8"
    )
    secrets = local_root.parent / "secret-files"
    secrets.mkdir()
    (secrets / URL_FIELD).write_text(f"https://{MARKER}.example.invalid", encoding="utf-8")
    settings = config.Settings(_env_prefix="IG_ENV_TEST_", _env_file=dotenv, _secrets_dir=secrets)
    assert MARKER not in getattr(settings, URL_FIELD)
    assert settings.APP_ENV == "local"


@pytest.mark.parametrize(
    "mutation", ["secret", "environment", "unknown_section", "wrong_type", "bool_version"]
)
def test_local_json_rejects_unapproved_fields_without_echo(local_root: Path, mutation: str) -> None:
    data = public_document()
    if mutation == "secret":
        data[PLATFORM][MARKER] = MARKER
    elif mutation == "environment":
        data[PLATFORM]["APP_ENV"] = "production"
    elif mutation == "unknown_section":
        data[MARKER] = {"DATABASE_URL": MARKER}
    elif mutation == "wrong_type":
        data[PLATFORM][URL_FIELD] = {"value": MARKER}
    else:
        data["schema_version"] = True
    local_root.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(environment.LocalSettingsError) as caught:
        make_settings()
    assert MARKER not in str(caught.value)


def test_empty_local_value_keeps_local_default(local_root: Path) -> None:
    data = public_document()
    data[PLATFORM][URL_FIELD] = ""
    local_root.write_text(json.dumps(data), encoding="utf-8")
    settings = make_settings()
    expected = "http://127.0.0.1:8000/api/v1" if PLATFORM == "frontend" else ""
    assert getattr(settings, URL_FIELD) == expected
    assert settings.check_environment()["configuration_valid"]


def test_local_json_rejects_duplicate_fields(local_root: Path) -> None:
    local_root.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    with pytest.raises(environment.LocalSettingsError, match="duplicate_field"):
        make_settings()


@pytest.mark.parametrize("name", environment.CLOUD_SECRET_FIELDS)
def test_inherited_secrets_block_only_fields_this_site_reads(
    local_root: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    # 本站會讀取的機密欄位：拒絕啟動；本站沒有的欄位（例如個人 shell Key）：僅警告且不載入值
    # ADMIN／API 依核定允許本機 DATABASE_URL：合法連線字串不阻擋，也不回報為機密
    # API 另允許 START 注入的 Google AI 設定（2026-10-28 使用者核定）
    approved = (PLATFORM in {"admin", "api"} and name == "DATABASE_URL") or (
        PLATFORM == "api" and name in {"GEMINI_API_KEY", "GOOGLE_SERVICE_ACCOUNT_JSON"}
    )
    value = (
        f"postgresql://synthetic:{MARKER}@db.example.invalid/test?sslmode=require"
        if name == "DATABASE_URL"
        else MARKER
    )
    monkeypatch.setenv("IG_ENV_TEST_" + name, value if approved else MARKER)
    settings = make_settings()
    report = settings.check_environment()
    if approved:
        assert report["configuration_valid"]
        assert not any(issue["field"] == name for issue in report["issues"])
        settings.require_environment()
        assert MARKER not in repr(settings) + json.dumps(report)
        return
    consumed = name in type(settings).model_fields
    issue = next(item for item in report["issues"] if item["field"] == name)
    assert issue["code"] == ("cloud_secret_in_local" if consumed else "inherited_secret_unused")
    assert issue["severity"] == ("error" if consumed else "warning")
    assert report["configuration_valid"] is not consumed
    message = ""
    if consumed:
        with pytest.raises(environment.EnvironmentConfigurationError) as caught:
            settings.require_environment()
        message = str(caught.value)
    else:
        settings.require_environment()
    assert MARKER not in message + repr(settings) + json.dumps(report)


@pytest.mark.parametrize(
    "values",
    [
        {"VERCEL_ENV": ""},
        {"VERCEL": ""},
        {"APP_ENV": "local"},
        {"APP_ENV": "preview"},
        {"VERCEL_ENV": "development"},
        {"DEBUG": True},
    ],
)
def test_cloud_conflicting_or_missing_flags_are_rejected(values: dict[str, Any]) -> None:
    assert not cloud_settings(**values).check_environment()["configuration_valid"]


@pytest.mark.parametrize(
    "url",
    [
        "http://api.example.invalid",
        "https://localhost",
        "https://localhost.",
        "https://127.0.0.1",
        "https://10.0.0.1",
        "https://169.254.169.254",
        "https://[::1]",
        "https://[::ffff:127.0.0.1]",
        "https://224.0.0.1",
        "https://[ff02::1]",
        "https://2130706433",
        "https://0x7f000001",
        "https://127.1",
        "https://0177.0.0.1",
        "https://127.0.0.1.nip.io.localhost",
        "https://test.trycloudflare.com",
        "https://test.ngrok-free.app",
        "https://127.0.0.1.nip.io",
        "https://127-0-0-1.sslip.io",
        "https://localtest.me",
        "https://api.lvh.me",
        "https://abc123.lhr.life",
        "https://abc.serveo.net",
        "https://abc.a.pinggy.link",
        "https://abc.tunnelmole.net",
        "https://host.tailnet-name.ts.net",
        "https://abc.ngrok.dev",
        f"https://user:{MARKER}@api.example.invalid",
        f"https://api.example.invalid?key={MARKER}",
        f"https://api.example.invalid/#{MARKER}",
        "https://api.example.invalid\\path",
        "https://api.example.invalid:bad",
        "https://api.example.invalid:8443",
        "https://api.example.invalid/%2e%2e",
        "https://api.example.invalid/../other",
        "https://api.example.invalid\n",
        "https://user@api.example.invalid",
    ],
)
def test_unsafe_remote_and_cloud_urls_are_rejected(url: str) -> None:
    assert not environment.valid_service_url(url)


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:8000/api/v1", "http://localhost:8000/api/v1", "http://[::1]:8000/api/v1"],
)
def test_http_loopback_is_only_allowed_explicitly(url: str) -> None:
    assert environment.valid_service_url(url, allow_loopback=True)
    assert not environment.valid_service_url(url)


def test_cli_report_contains_no_url_or_secret_values(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = make_settings(**{URL_FIELD: f"https://user:{MARKER}@api.example.invalid"})
    monkeypatch.setattr(config, "settings", settings)
    assert environment.main(["--check"]) == 2
    output = capsys.readouterr()
    assert MARKER not in output.out + output.err
    assert json.loads(output.out)["connectivity_checked"] is False


def test_valid_local_cli_does_not_claim_connectivity(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(config, "settings", make_settings())
    assert environment.main(["--check"]) == 0
    assert json.loads(capsys.readouterr().out)["connectivity_checked"] is False


@pytest.mark.parametrize("scenario", ["invalid_json", "invalid_type", "cloud_ignores_file"])
def test_real_module_cli_is_offline_and_redacts_load_errors(
    local_root: Path,
    scenario: str,
) -> None:
    """在只含設定模組的暫存套件執行真正 -m；不啟動應用、服務或 DB。"""
    package = local_root.parent.parent / "repository" / "app"
    core = package / "core"
    core.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    (core / "__init__.py").write_text("", encoding="utf-8")
    source = Path(config.__file__).parent
    # config.py 可能引用三站共用的 constants.py（目前 ADMIN 有），暫存套件需一起複製。
    for name in ("config.py", "constants.py", "environment.py", "module_errors.py"):
        if (source / name).is_file():
            (core / name).write_bytes((source / name).read_bytes())
    child_env = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "LOCALAPPDATA"}
    }
    child_env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
    local_root.write_text("{ " + MARKER, encoding="utf-8")
    if scenario == "invalid_type":
        local_root.unlink()
        child_env["APP_ENV"] = MARKER
    elif scenario == "cloud_ignores_file":
        child_env.update(VERCEL="1", VERCEL_ENV="production", APP_ENV="production")
        if PLATFORM == "frontend":
            child_env["API_BASE_URL"] = "https://api.example.invalid/api/v1"
    result = subprocess.run(
        [sys.executable, "-B", "-m", "app.core.environment", "--check"],
        cwd=package.parent,
        env=child_env,
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert MARKER not in result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert not report["connectivity_checked"]
    if scenario == "cloud_ignores_file":
        assert result.returncode == 0
        assert report["local_file_ignored"]
    else:
        assert result.returncode == 2
        assert report["issues"][0]["code"] == "invalid_settings"
