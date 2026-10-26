"""三站一致的環境／URL 邊界；只讀公開本機 URL，不下載或輸出機密。"""

import argparse
import ipaddress
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

LOCAL_URL_FIELDS = {
    "frontend": {"API_BASE_URL"},
    "admin": {"REMOTE_ADMIN_BASE_URL"},
    "api": {"REMOTE_API_BASE_URL"},
}
CLOUD_SECRET_FIELDS = (
    "DATABASE_URL",
    "DATABASE_URL_UNPOOLED",
    "SESSION_SECRET_KEY",
    "JWT_SECRET_KEY",
    "CRON_SECRET",
    "SUPABASE_SECRET_KEY",
    "SUPABASE_SERVICE_ROLE_KEY",
    "GEMINI_API_KEY",
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "AI_API_KEY",
    "EINVOICE_APP_ID",
    "EINVOICE_API_KEY",
    "BLOB_READ_WRITE_TOKEN",
    "VERCEL_TOKEN",
)
# 已知臨時隧道／分享網域；清單不可能完整，管理者仍需核定實際目標網址
TUNNEL_SUFFIXES = (
    "trycloudflare.com",
    "ngrok.io",
    "ngrok.app",
    "ngrok.dev",
    "ngrok.pizza",
    "ngrok-free.app",
    "ngrok-free.dev",
    "loca.lt",
    "localtunnel.me",
    "localhost.run",
    "lhr.life",
    "serveo.net",
    "serveousercontent.com",
    "pinggy.io",
    "pinggy.link",
    "tunnelmole.net",
    "loophole.site",
    "bore.pub",
    "zrok.io",
    "ts.net",
    "devtunnels.ms",
)
# 公開 DNS 但固定解析到 loopback 或內嵌任意 IP 的網域；驗證不解析 DNS，只能以名稱拒絕
LOOPBACK_DNS_SUFFIXES = (
    "nip.io",
    "sslip.io",
    "xip.io",
    "traefik.me",
    "localtest.me",
    "lvh.me",
    "vcap.me",
    "localhost.direct",
)
# 非公開的保留網域
PRIVATE_DNS_SUFFIXES = ("localhost", "local", "internal", "home.arpa")


class LocalSettingsError(ValueError):
    """固定訊息，不包含檔案內容、未知欄位名稱或設定值。"""


class EnvironmentConfigurationError(RuntimeError):
    """啟動拒絕時僅顯示固定欄位與代碼。"""


def _issue(field: str, code: str, message: str, severity: str = "error") -> dict[str, str]:
    return {"field": field, "code": code, "message": message, "severity": severity}


def _matches_suffix(host: str, suffixes: tuple[str, ...]) -> bool:
    return any(host == suffix or host.endswith("." + suffix) for suffix in suffixes)


def _cloud_marker(values: dict[str, Any]) -> bool:
    return (
        bool(values.get("VERCEL") or values.get("VERCEL_ENV"))
        or values.get("APP_ENV", "local") != "local"
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise LocalSettingsError("local_urls: duplicate_field")
        result[key] = value
    return result


def load_local_urls(repo_root: Path, platform: str) -> dict[str, str]:
    """只在本機 source 呼叫；固定 sibling 路徑，不接受任意檔案／秘密欄位。"""
    path = repo_root.parent / "InvoiceGuard-STARTUP" / "dev-urls.local.json"
    try:
        if not path.exists():
            return {}
        if path.is_symlink() or not path.resolve().is_relative_to(repo_root.parent.resolve()):
            raise LocalSettingsError("local_urls: unsafe_path")
        if path.stat().st_size > 65536:
            raise LocalSettingsError("local_urls: file_too_large")
        data = json.loads(path.read_text(encoding="utf-8-sig"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise LocalSettingsError("local_urls: unreadable_or_invalid_json") from None
    if (
        not isinstance(data, dict)
        or set(data) != {"schema_version", *LOCAL_URL_FIELDS}
        or type(data["schema_version"]) is not int
        or data["schema_version"] != 1
    ):
        raise LocalSettingsError("local_urls: invalid_schema")
    for section, allowed in LOCAL_URL_FIELDS.items():
        values = data[section]
        if not isinstance(values, dict) or not set(values) <= allowed:
            raise LocalSettingsError("local_urls: unapproved_field")
        if any(not isinstance(value, str) or len(value) > 2048 for value in values.values()):
            raise LocalSettingsError("local_urls: invalid_value_type")
    return data[platform]


def settings_sources(
    init_settings: Any, env_settings: Any, *, repo_root: Path, platform: str
) -> tuple[Any, ...]:
    """程序環境優先；刻意不使用 dotenv 與 secrets_dir，即使呼叫者傳入覆寫參數。"""

    def secret_guard_source() -> dict[str, tuple[str, ...]]:
        # 只保留核定機密欄位的名稱，不將未使用的機密值載入前端 Settings。
        variables = env_settings.env_vars
        prefix = env_settings.env_prefix
        names = tuple(
            name
            for name in CLOUD_SECRET_FIELDS
            if variables.get(
                prefix + name if env_settings.case_sensitive else (prefix + name).lower()
            )
        )
        return {"LOCAL_SECRET_FIELDS": names}

    def local_source() -> dict[str, str]:
        # 在檢查檔案存在與否之前就決定是否忽略；任一來源的雲端標記都不能被降級。
        if _cloud_marker(env_settings()) or _cloud_marker(init_settings()):
            return {}
        defaults = (
            {"API_BASE_URL": "http://127.0.0.1:8000/api/v1"} if platform == "frontend" else {}
        )
        # 留空的欄位視同未設定，保留本機預設值
        local_urls = {
            key: value for key, value in load_local_urls(repo_root, platform).items() if value
        }
        return defaults | local_urls

    return secret_guard_source, env_settings, init_settings, local_source


def valid_service_url(
    value: str, *, allow_loopback: bool = False, allow_tunnel: bool = False
) -> bool:
    """無 DNS／網路的格式驗證；不是完整 SSRF 或遠端服務身分驗證。"""
    if not isinstance(value, str) or not value or len(value) > 2048:
        return False
    if any(ord(char) <= 32 or ord(char) >= 127 for char in value) or any(
        char in value for char in "\\%?#"
    ):
        return False
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        port = url.port
        if (
            not host
            or url.scheme not in {"http", "https"}
            or host.endswith(".")
            or url.username is not None
            or url.password is not None
            or (port is not None and not 1 <= port <= 65535)
            or any(part in {".", ".."} for part in url.path.split("/"))
        ):
            return False
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
            return False
        loopback = host == "localhost" or bool(address and address.is_loopback)
        if loopback:
            return allow_loopback
        if url.scheme != "https" or port not in {None, 443}:
            return False
        if address is not None:
            return address.is_global and not address.is_multicast and not address.is_reserved
        labels = host.split(".")
        if (
            len(labels) < 2
            or labels[-1].isdigit()
            or not all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels
            )
        ):
            return False
        if _matches_suffix(host, PRIVATE_DNS_SUFFIXES + LOOPBACK_DNS_SUFFIXES):
            return False
        return allow_tunnel or not _matches_suffix(host, TUNNEL_SUFFIXES)
    except (ValueError, TypeError):
        return False


def environment_report(configuration: Any, platform: str) -> dict[str, Any]:
    """環境與路由的靜態檢查；不驗證 DB、登入或業務操作是否可用。"""
    issues = []
    vercel = configuration.VERCEL
    deployed = configuration.VERCEL_ENV
    app_env = configuration.APP_ENV
    cloud = bool(vercel or deployed or app_env != "local")
    if cloud:
        if vercel != "1":
            issues.append(_issue("VERCEL", "cloud_runtime_required", "雲端環境必須有平台執行標記"))
        if deployed not in {"preview", "production"}:
            issues.append(
                _issue(
                    "VERCEL_ENV", "deployment_environment_required", "需為 preview 或 production"
                )
            )
        elif app_env != deployed:
            issues.append(_issue("APP_ENV", "environment_mismatch", "應用與部署環境必須一致"))
        if configuration.DEBUG:
            issues.append(_issue("DEBUG", "debug_in_cloud", "雲端必須關閉除錯輸出"))
        if getattr(configuration, "module_backend", "cloud") != "cloud":
            issues.append(_issue("MODULE_BACKEND", "cloud_required", "雲端不得使用本機遠端模式"))
    else:
        if getattr(configuration, "module_backend", "remote") != "remote":
            issues.append(_issue("MODULE_BACKEND", "remote_required", "本機不得直接使用雲端整合"))
        inherited = getattr(configuration, "LOCAL_SECRET_FIELDS", ())
        consumed = getattr(type(configuration), "model_fields", {})
        for name in CLOUD_SECRET_FIELDS:
            secret = getattr(configuration, name, None)
            value = secret.get_secret_value() if hasattr(secret, "get_secret_value") else secret
            if value or (name in inherited and name in consumed):
                issues.append(_issue(name, "cloud_secret_in_local", "本機不得載入公司機密"))
            elif name in inherited:
                # 本站沒有此欄位，值不會載入；多為開發者 shell 的個人 Key，只提醒、不阻擋啟動
                issues.append(
                    _issue(
                        name,
                        "inherited_secret_unused",
                        "程序環境有本站不使用的機密名稱，值未載入；建議只在目前 PowerShell 移除",
                        "warning",
                    )
                )
    if platform == "frontend":
        if not valid_service_url(configuration.API_BASE_URL, allow_loopback=not cloud):
            issues.append(
                _issue(
                    "API_BASE_URL",
                    "invalid_api_url",
                    "需設定符合環境的 API 基底網址；雲端必須為公開 HTTPS",
                )
            )
        mobile_origin = getattr(configuration, "LOCAL_HTTPS_ORIGIN", "")
        origin_file = getattr(configuration, "LOCAL_MOBILE_ORIGIN_FILE", "")
        mobile_code = getattr(configuration, "LOCAL_MOBILE_ACCESS_CODE", "")
        mobile_code = (
            mobile_code.get_secret_value()
            if hasattr(mobile_code, "get_secret_value")
            else mobile_code
        )
        if cloud and (mobile_origin or mobile_code or origin_file):
            issues.append(
                _issue(
                    "LOCAL_HTTPS_ORIGIN", "local_setting_in_cloud", "雲端不得啟用本機手機測試入口"
                )
            )
        elif mobile_origin or mobile_code or origin_file:
            if origin_file and (
                not Path(origin_file).is_absolute() or Path(origin_file).name != "origin.json"
            ):
                issues.append(
                    _issue(
                        "LOCAL_MOBILE_ORIGIN_FILE",
                        "invalid_origin_file",
                        "手機測試需使用本次暫存目錄的 origin.json 絕對路徑",
                    )
                )
            if (mobile_origin or not origin_file) and (
                not valid_service_url(mobile_origin, allow_tunnel=True)
                or urlsplit(mobile_origin).path not in {"", "/"}
            ):
                issues.append(
                    _issue(
                        "LOCAL_HTTPS_ORIGIN",
                        "invalid_mobile_origin",
                        "手機入口需為單一公開 HTTPS origin，不含路徑或憑證",
                    )
                )
            if len(mobile_code) < 24:
                issues.append(
                    _issue(
                        "LOCAL_MOBILE_ACCESS_CODE",
                        "mobile_code_required",
                        "手機測試需要至少 24 字元的本次臨時存取碼",
                    )
                )
            api = (
                urlsplit(configuration.API_BASE_URL)
                if valid_service_url(configuration.API_BASE_URL, allow_loopback=True)
                else None
            )
            if (
                api is None
                or api.scheme != "http"
                or api.hostname not in {"127.0.0.1", "localhost", "::1"}
                or api.path.rstrip("/") != "/api/v1"
            ):
                issues.append(
                    _issue(
                        "API_BASE_URL",
                        "local_api_required",
                        "手機開發只能連線本機 loopback API 的 /api/v1",
                    )
                )
    else:
        field = "REMOTE_ADMIN_BASE_URL" if platform == "admin" else "REMOTE_API_BASE_URL"
        value = getattr(configuration, field)
        if cloud and value:
            issues.append(_issue(field, "local_setting_in_cloud", "雲端不得載入本機遠端轉送網址"))
        elif value and not valid_service_url(value):
            issues.append(_issue(field, "invalid_remote_url", "遠端服務需使用核定公開 HTTPS 網址"))
        storage_url = getattr(configuration, "SUPABASE_URL", "")
        if storage_url and not valid_service_url(storage_url):
            issues.append(
                _issue("SUPABASE_URL", "invalid_storage_url", "Storage 需使用公開 HTTPS 專案網址")
            )
    return {
        "scope": "environment",
        "platform": platform,
        "environment": app_env,
        # 警告不影響結果；只有 error 會拒絕啟動
        "configuration_valid": not any(issue["severity"] == "error" for issue in issues),
        "connectivity_checked": False,
        "local_file_ignored": cloud,
        "issues": issues,
    }


def require_environment(configuration: Any, platform: str) -> None:
    """在組裝 app 或發出請求前呼叫；錯誤文字不包含任何設定值。"""
    report = environment_report(configuration, platform)
    if not report["configuration_valid"]:
        codes = ", ".join(
            f"{item['field']}:{item['code']}"
            for item in report["issues"]
            if item["severity"] == "error"
        )
        raise EnvironmentConfigurationError("環境設定驗證失敗：" + codes)


def main(argv: list[str] | None = None) -> int:
    """python -m app.core.environment --check；不讀出或列印任何變數值。"""
    parser = argparse.ArgumentParser(description="環境與 URL 離線檢查")
    parser.add_argument("--check", action="store_true", required=True)
    parser.parse_args(argv)
    try:
        from app.core.config import settings

        report = settings.check_environment()
    except (ValueError, RuntimeError):
        # BaseSettings／JSON 的錯誤不回顯原始輸入，亦不沿用 exception.message。
        report = {
            "scope": "environment",
            "configuration_valid": False,
            "connectivity_checked": False,
            "issues": [
                _issue(
                    "settings",
                    "invalid_settings",
                    "設定無法載入；請檢查欄位名稱、型別與公開設定格式",
                )
            ],
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["configuration_valid"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
