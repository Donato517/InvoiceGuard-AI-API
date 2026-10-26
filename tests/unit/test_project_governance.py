"""以合成程式碼及專案副本驗證 AI 協作規範，不載入應用或讀取公司密鑰。"""

import builtins
import errno
import importlib.util
import json
import os
import py_compile
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
PROJECTS = ("InvoiceGuard-AI", "InvoiceGuard-AI-ADMIN", "InvoiceGuard-AI-API")
CHECKER_NAME = "project_governance_checker"


@contextmanager
def loaded_checker() -> Iterator[ModuleType]:
    """以檔案位置載入自己 Repository 的標準函式庫檢查器，結束後還原模組表。"""
    spec = importlib.util.spec_from_file_location(
        CHECKER_NAME, ROOT / "scripts" / "check_project.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    previous = sys.modules.get(CHECKER_NAME)
    sys.modules[CHECKER_NAME] = module
    try:
        spec.loader.exec_module(module)
        yield module
    finally:
        if previous is None:
            sys.modules.pop(CHECKER_NAME, None)
        else:
            sys.modules[CHECKER_NAME] = previous


# 與檢查器相同，以 Settings.APP_NAME 判斷本站角色；Clone 資料夾可以不是 Repository 名稱。
with loaded_checker() as _role_checker:
    PROJECT = _role_checker._project_name(ROOT)


@pytest.fixture(scope="module")
def checker() -> Iterator[ModuleType]:
    """提供本站檢查器；不 import app，也不讀取設定值。"""
    with loaded_checker() as module:
        yield module


def synthetic(body: str) -> str:
    """加入模組說明，讓案例只測分層行為。"""
    return '"""模組名稱：規範測試；功能說明：合成相依案例。"""\n' + body


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("app/routers/example.py", "from sqlalchemy.orm import Session\n"),
        ("app/routers/example.py", "import psycopg as database_driver\n"),
        ("app/routers/example.py", "from app.db.session import get_db\n"),
        ("app/routers/example.py", "from ..db import session\n"),
        ("app/routers/example.py", "from app import db\n"),
        ("app/routers/example.py", "import app.db.session as connection\n"),
        (
            "app/routers/example.py",
            'def route() -> None:\n    """不得在函式內繞過分層。"""\n'
            "    from app.db.session import get_db\n",
        ),
        (
            "app/routers/example.py",
            "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n"
            "    from app.db.models.user import User\n",
        ),
        (
            "app/services/example_service.py",
            "from fastapi import Request as WebRequest\n",
        ),
        ("app/services/example_service.py", "import fastapi as web\n"),
        (
            "app/services/example_service.py",
            "from starlette.responses import Response\n",
        ),
        ("app/services/example_service.py", "from app.routers import health\n"),
        (
            "app/db/repositories/example_repository.py",
            "from app.services import data_service\n",
        ),
        ("app/db/models/example.py", "from app.routers import health\n"),
        (
            "app/integrations/example_client.py",
            "from app.services import data_service\n",
        ),
        ("app/schemas/example.py", "from app.db.models.user import User\n"),
        ("app/core/example.py", "from app.services import data_service\n"),
    ],
)
def test_layer_violations_are_rejected(checker: ModuleType, path: str, body: str) -> None:
    """絕對、相對、別名及巢狀 import 都必須遵守相同規則。"""
    assert checker.check_source(synthetic(body), path, PROJECT)


@pytest.mark.parametrize(
    "expression",
    ["db.commit()", "transaction.commit()", "await db.commit()", "db.rollback()"],
)
def test_repository_cannot_commit(checker: ModuleType, expression: str) -> None:
    """交易提交責任不得悄悄移至 Repository。"""
    source = synthetic(
        'async def save(db: object, transaction: object) -> None:\n    """合成交易。"""\n'
        f"    {expression}\n"
    )
    assert checker.check_source(source, "app/db/repositories/example_repository.py", PROJECT)


@pytest.mark.parametrize(
    "body",
    [
        "import os as system\nvalue = system.environ['SYNTHETIC_SETTING']\n",
        "from os import getenv as read_setting\nvalue = read_setting('SYNTHETIC_SETTING')\n",
        "from os import environ as inherited\nvalue = inherited.get('SYNTHETIC_SETTING')\n",
        "from pydantic_settings import BaseSettings\n",
        "from dotenv import load_dotenv\n",
    ],
)
def test_settings_cannot_bypass_config(checker: ModuleType, body: str) -> None:
    """合成設定名稱不含密鑰，仍驗證集中設定的界線。"""
    assert checker.check_source(synthetic(body), "app/utils/example.py", PROJECT)


@pytest.mark.parametrize(
    "body",
    [
        "__import__('app.db.session')\n",
        "import builtins as runtime\nruntime.__import__('app.db.session')\n",
        "from importlib import import_module as load\nload('app.db.session')\n",
        "eval('1 + 1')\n",
        "exec('value = 1')\n",
        "import builtins as runtime\nruntime.eval('1 + 1')\n",
        "from builtins import exec as run\nrun('value = 1')\n",
    ],
)
def test_dynamic_execution_cannot_hide_dependencies(checker: ModuleType, body: str) -> None:
    """動態匯入及字串執行不可用來逃避靜態相依檢查。"""
    assert checker.check_source(synthetic(body), "app/routers/example.py", PROJECT)


@pytest.mark.parametrize(
    ("path", "source"),
    [
        ("app/routers/example.py", "value = 1\n"),
        ("app/routers/BadName.py", synthetic("value = 1\n")),
        (
            "app/routers/example.py",
            synthetic('def value():\n    """缺少型別。"""\n    return 1\n'),
        ),
    ],
)
def test_new_python_files_follow_common_format(checker: ModuleType, path: str, source: str) -> None:
    """新檔案需維持用途說明、snake_case 與函式型別格式。"""
    assert checker.check_source(source, path, PROJECT)


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("app/routers/example.py", "from app.core.deps import DbSession\n"),
        (
            "app/services/example_service.py",
            "from app.schemas.data import InvoiceRead\n",
        ),
        (
            "app/services/example_service.py",
            'def save(db: object) -> None:\n    """由服務管理交易。"""\n    db.commit()\n',
        ),
        (
            "app/db/repositories/example_repository.py",
            "from app.db.models.user import User\n",
        ),
        ("app/db/models/example.py", "from app.db.base import Base\n"),
        ("app/db/contracts.py", "from app.schemas.common import OperationContext\n"),
        (
            "app/integrations/example_client.py",
            "from app.core.config import settings\n",
        ),
        ("app/schemas/example.py", "from app.schemas.common import RecordId\n"),
    ],
)
def test_permitted_backend_layers(checker: ModuleType, path: str, body: str) -> None:
    """合法後端相依與 Service 交易不可被規範誤擋。"""
    if PROJECT == "InvoiceGuard-AI":
        pytest.skip("前端沒有 DB、Schema 或 Service 層")
    assert not checker.check_source(synthetic(body), path, PROJECT)


def test_service_collection_methods_do_not_look_like_session_writes(
    checker: ModuleType,
) -> None:
    """一般集合的 add 方法不可被誤認為 ORM 新增。"""
    if PROJECT == "InvoiceGuard-AI":
        pytest.skip("前端沒有 Service 層")
    source = synthetic(
        'def remember(value: int) -> set[int]:\n    """記錄已處理項目。"""\n'
        "    seen: set[int] = set()\n    seen.add(value)\n    return seen\n"
    )
    assert not checker.check_source(source, "app/services/example_service.py", PROJECT)


@pytest.mark.parametrize(
    "body",
    [
        "from sqlalchemy.orm import Session as DbSession\n"
        'def save(unit: DbSession, record: object) -> None:\n    """不可直接寫入 ORM。"""\n'
        "    unit.add(record)\n",
        'def load(db: object) -> None:\n    """不可直接執行查詢。"""\n'
        "    db.execute('synthetic query')\n",
    ],
)
def test_service_session_operations_still_require_repository(
    checker: ModuleType, body: str
) -> None:
    """Session 型別與既有 db 命名都不能略過 Repository。"""
    if PROJECT == "InvoiceGuard-AI":
        pytest.skip("前端沒有 Service 層")
    assert checker.check_source(synthetic(body), "app/services/example_service.py", PROJECT)


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("app/routers/example.py", "import httpx\n"),
        ("app/routers/example.py", "from httpx import AsyncClient as Client\n"),
        ("app/clients/example.py", "from sqlalchemy import create_engine\n"),
        ("app/clients/example.py", "from app.db import session\n"),
    ],
)
def test_frontend_uses_clients_without_database(checker: ModuleType, path: str, body: str) -> None:
    """前端不得自行加 DB，也不能把 HTTP 呼叫分散至一般 Router。"""
    if PROJECT != "InvoiceGuard-AI":
        pytest.skip("只檢查前端界線")
    assert checker.check_source(synthetic(body), path, PROJECT)


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("app/main.py", "from app.routers import health\n"),
        ("app/core/deps.py", "from app.db.session import get_db\n"),
        ("app/core/exceptions.py", "from app.clients.base import ApiError\n"),
        ("app/routers/mobile_dev.py", "import httpx\n"),
        ("app/mobile_dev.py", "from app.main import create_app\n"),
    ],
)
def test_explicit_composition_exceptions(checker: ModuleType, path: str, body: str) -> None:
    """既有組裝及固定手機健康檢查的精確例外仍可使用。"""
    if path == "app/core/deps.py" and PROJECT == "InvoiceGuard-AI":
        pytest.skip("前端 DI 不含 DB")
    if (
        path in {"app/core/exceptions.py", "app/routers/mobile_dev.py", "app/mobile_dev.py"}
        and PROJECT != "InvoiceGuard-AI"
    ):
        pytest.skip("只允許前端既有的組裝例外")
    assert not checker.check_source(synthetic(body), path, PROJECT)


def test_ast_digest_ignores_only_real_docstrings(checker: ModuleType) -> None:
    """文件更新不改契約摘要，但 SQL 字串、預設值與函式行為會改。"""
    first = '"""舊說明。"""\nclass Item:\n    """舊說明。"""\n    rule = "score >= 0"\n'
    second = '"""新說明。"""\nclass Item:\n    """新說明。"""\n    rule = "score >= 0"\n'
    assert checker.ast_digest(first) == checker.ast_digest(second)
    assert checker.ast_digest(first) != checker.ast_digest(first.replace("score >= 0", "score > 0"))
    function = 'def validate(value: int) -> bool:\n    """驗證。"""\n    return value > 0\n'
    assert checker.ast_digest(function) != checker.ast_digest(function.replace("> 0", "> 1"))


def test_ast_subset_requires_every_declared_name(checker: ModuleType) -> None:
    """選取共用子集不得悄悄忽略遺失的常數或型別。"""
    first = "MAX_SIZE = 4\nEXTRA = 1\n"
    assert checker.ast_digest(first, ("MAX_SIZE",)) == checker.ast_digest(
        "MAX_SIZE = 4\nEXTRA = 2\n", ("MAX_SIZE",)
    )
    assert checker.ast_digest(first, ("MAX_SIZE",)) != checker.ast_digest(
        "MAX_SIZE = 8\n", ("MAX_SIZE",)
    )
    with pytest.raises(ValueError):
        checker.ast_digest(first, ("MAX_SIZE", "MISSING_TYPE"))


def test_ast_subset_keeps_used_imports_and_transitive_helpers(
    checker: ModuleType,
) -> None:
    """共用子集包含真正用到的 import 與輔助閉包，忽略無關 import。"""
    source = (
        "from dataclasses import dataclass\nimport math as unused\nSCALE = 1\n"
        'def normalize(value: int) -> int:\n    """合成輔助函式。"""\n    return value * SCALE\n'
        '@dataclass\nclass Entry:\n    """合成契約。"""\n    value: int\n'
        '    def normalized(self) -> int:\n        """回傳正規化值。"""\n'
        "        return normalize(self.value)\n"
    )
    original = checker.ast_digest(source, ("Entry",))
    assert original != checker.ast_digest(
        source.replace("from dataclasses", "from synthetic_dataclasses"), ("Entry",)
    )
    assert original != checker.ast_digest(source.replace("SCALE = 1", "SCALE = 2"), ("Entry",))
    assert original != checker.ast_digest(
        source.replace("value * SCALE", "value + SCALE"), ("Entry",)
    )
    assert original == checker.ast_digest(
        source.replace("import math as unused", "import statistics as unused"),
        ("Entry",),
    )


def copy_project(source: Path, target: Path) -> Path:
    """只複製規範檢查會使用的非機密程式與文件。"""
    target.mkdir()
    ignored = shutil.ignore_patterns("__pycache__", "*.pyc", ".env", ".env.*", "*.pem", "*.key")
    for directory in ("app", "docs", "scripts", "contracts", ".github"):
        shutil.copytree(source / directory, target / directory, ignore=ignored)
    for filename in ("AGENTS.md", "CLAUDE.md", "README.md"):
        shutil.copy2(source / filename, target / filename)
    return target


@pytest.fixture
def standalone_project(tmp_path: Path) -> Path:
    """只複製已知程式與規範資料夾，沒有 .env、venv、Git 或兄弟專案。"""
    return copy_project(ROOT, tmp_path / PROJECT)


def test_standalone_checkout_passes_without_importing_app(
    checker: ModuleType, standalone_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """單站 CI 不需要兄弟 Repo，也不能為檢查而載入應用程式。"""
    original = builtins.__import__

    def forbid_app_import(name: str, *args: object, **kwargs: object) -> object:
        """若檢查器企圖載入 app，立即指出副作用風險。"""
        assert name != "app" and not name.startswith("app."), "檢查器不可 import app"
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", forbid_app_import)
    assert not checker.check_project(standalone_project)


@pytest.mark.parametrize(
    ("relative_path", "before", "after"),
    [
        (
            "app/schemas/files.py",
            "MAX_UPLOAD_BYTES = 4 * 1024 * 1024",
            "MAX_UPLOAD_BYTES = 8 * 1024 * 1024",
        ),
        ("app/schemas/common.py", "MAX_PAGE = 10_000", "MAX_PAGE = 20_000"),
        (
            "app/db/models/invoice.py",
            'CheckConstraint("risk_score BETWEEN 0 AND 100",',
            'CheckConstraint("risk_score BETWEEN 0 AND 101",',
        ),
        (
            "app/integrations/vercel.py",
            "operations_implemented: bool = False",
            "operations_implemented: bool = True",
        ),
    ],
)
def test_contract_mutations_fail_without_siblings(
    checker: ModuleType,
    standalone_project: Path,
    relative_path: str,
    before: str,
    after: str,
) -> None:
    """單站快照也能發現 DTO 大小、分頁與 DB 約束的漂移。"""
    if PROJECT == "InvoiceGuard-AI":
        pytest.skip("前端沒有後端契約或 ORM")
    path = standalone_project / relative_path
    original = path.read_text(encoding="utf-8")
    assert before in original
    path.write_text(original.replace(before, after, 1), encoding="utf-8")
    assert checker.check_project(standalone_project)


@pytest.mark.parametrize("mutation", ["missing_required", "invalid_syntax", "unknown_app_layer"])
def test_incomplete_or_unscannable_project_fails(
    checker: ModuleType, standalone_project: Path, mutation: str
) -> None:
    """缺檔、語法錯與未知層都必須失敗，避免漏掃被誤認為通過。"""
    if mutation == "missing_required":
        (standalone_project / "app" / "core" / "config.py").unlink()
    elif mutation == "invalid_syntax":
        (standalone_project / "app" / "routers" / "broken.py").write_text(
            '"""無法解析的合成案例。"""\ndef broken(:\n', encoding="utf-8"
        )
    else:
        directory = standalone_project / "app" / "unapproved_layer"
        directory.mkdir()
        (directory / "example.py").write_text(synthetic("value = 1\n"), encoding="utf-8")
    assert checker.check_project(standalone_project)


@pytest.mark.parametrize("mutation", ["extra_model", "model_registration"])
def test_model_inventory_and_registration_cannot_drift(
    checker: ModuleType, standalone_project: Path, mutation: str
) -> None:
    """合法語法的新 Model 及註冊變更，都必須先經契約相容性審查。"""
    if PROJECT == "InvoiceGuard-AI":
        pytest.skip("前端沒有 ORM")
    if mutation == "extra_model":
        path = standalone_project / "app/db/models/extra.py"
        path.write_text(synthetic("from app.db.base import Base\n"), encoding="utf-8")
    else:
        path = standalone_project / "app/db/models/__init__.py"
        path.write_text(
            path.read_text(encoding="utf-8") + "\nEXTRA_MODEL_REGISTERED = False\n",
            encoding="utf-8",
        )
    assert checker.check_project(standalone_project)


def test_explicit_cross_repo_check_requires_siblings(
    checker: ModuleType, standalone_project: Path
) -> None:
    """明確要求跨站驗證時，不可把缺少兄弟 Repository 當成略過。"""
    assert checker.check_project(standalone_project, standalone_project.parent)


@pytest.mark.parametrize(
    "relative_path",
    ["app/static/.env", "app/static/private/example.txt", "app/static/example.key"],
)
def test_private_runtime_files_cannot_enter_static(
    checker: ModuleType, standalone_project: Path, relative_path: str
) -> None:
    """公開目錄的測試內容全為合成文字，不使用真實機密或金鑰。"""
    if PROJECT == "InvoiceGuard-AI-API":
        pytest.skip("API 沒有公開靜態資源目錄")
    path = standalone_project / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("synthetic fixture only\n", encoding="utf-8")
    assert checker.check_project(standalone_project)


def test_public_asset_and_documented_template_are_allowed(
    checker: ModuleType, standalone_project: Path
) -> None:
    """正常公開 JS 及帶用途註解的樣板，不應被私檔規則誤擋。"""
    if PROJECT == "InvoiceGuard-AI-API":
        pytest.skip("API 沒有靜態資源或樣板目錄")
    (standalone_project / "app/static/js/governance_example.js").write_text(
        "// 規範檢查用公開資源。\nconst example = 1;\n", encoding="utf-8"
    )
    (standalone_project / "app/templates/governance_example.html").write_text(
        "{# @template: 規範測試；用途：合成樣板。 #}\n<p>example</p>\n",
        encoding="utf-8",
    )
    assert not checker.check_project(standalone_project)


@pytest.mark.parametrize(
    "mutation", ["claude_reference", "shared_rules", "snapshot_key", "snapshot_group"]
)
def test_entry_and_baseline_mutations_fail(
    checker: ModuleType, standalone_project: Path, mutation: str
) -> None:
    """AI 入口及快照失去共同依據時，單站檢查即須拒絕。"""
    if mutation == "claude_reference":
        path = standalone_project / "CLAUDE.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace("@AGENTS.md", "AGENTS.md"),
            encoding="utf-8",
        )
    elif mutation == "shared_rules":
        path = standalone_project / "AGENTS.md"
        path.write_text(
            path.read_text(encoding="utf-8").replace(
                "<!-- shared-rules:start -->",
                "<!-- shared-rules:start -->\n合成規則漂移。",
                1,
            ),
            encoding="utf-8",
        )
    else:
        path = standalone_project / "contracts/project-contract.json"
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "snapshot_key":
            del snapshot["common"]
        else:
            snapshot["models"].pop(next(iter(snapshot["models"])))
        path.write_text(json.dumps(snapshot), encoding="utf-8")
    assert checker.check_project(standalone_project)


def test_complete_peer_tree_passes_and_checker_drift_fails(
    checker: ModuleType, standalone_project: Path
) -> None:
    """明確跨站模式會驗證完整三站，也能抓到個別 AI 更改檢查器。"""
    missing = [
        name
        for name in PROJECTS
        if name != PROJECT and not (ROOT.parent / name / "scripts" / "check_project.py").is_file()
    ]
    if missing:
        # 單站 CI 只 checkout 本站；缺站時的失敗行為由上方 requires_siblings 測試驗證。
        pytest.skip("單站 checkout 沒有兄弟 Repository；跨站比對只在三站齊全時執行")
    project_root = standalone_project.parent
    peers = []
    for name in PROJECTS:
        if name != PROJECT:
            peers.append(copy_project(ROOT.parent / name, project_root / name))
    assert not checker.check_project(standalone_project, project_root)
    path = peers[0] / "scripts/check_project.py"
    path.write_text(path.read_text(encoding="utf-8") + "\n# 合成跨站差異。\n", encoding="utf-8")
    assert checker.check_project(standalone_project, project_root)


BACKEND_ONLY = "前端沒有 DB、Repository、Service 或 deps DB 例外"


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("app/routers/example.py", "import app\n\nVALUE = app.db.session.get_db\n"),
        (
            "app/routers/example.py",
            "import importlib.util\n\n"
            "SPEC = importlib.util.spec_from_file_location('x', 'app/db/session.py')\n",
        ),
        (
            "app/routers/example.py",
            "import runpy\n\nVALUE = runpy.run_module('app.db.session')\n",
        ),
        (
            "app/routers/example.py",
            "import pkgutil\n\nVALUE = pkgutil.resolve_name('app.db.session:get_db')\n",
        ),
        ("app/routers/example.py", "import urllib\n\nVALUE = urllib.request.urlopen\n"),
        (
            "app/routers/example.py",
            "import http.client\n\nVALUE = http.client.HTTPSConnection\n",
        ),
        (
            "app/routers/example.py",
            "import asyncio\n\nVALUE = asyncio.open_connection\n",
        ),
        ("app/routers/example.py", "import urllib3\n"),
        (
            "app/utils/example.py",
            "from app.core.config import BaseSettings\n\n\nclass Extra(BaseSettings):\n"
            '    """合成的額外設定來源。"""\n\n    VALUE: str = ""\n',
        ),
        ("app/utils/example.py", "from pydantic.v1 import BaseSettings\n"),
        (
            "app/utils/example.py",
            "from pathlib import Path\n\nTEXT = Path('.env').read_text()\n",
        ),
        (
            "app/utils/example.py",
            "import os\n\nVALUE = os.getenvb(b'SYNTHETIC_SETTING')\n",
        ),
        ("app/utils/example.py", "import nt\n\nVALUE = nt.environ\n"),
    ],
)
def test_attribute_aliases_loaders_and_settings_cannot_bypass_rules(
    checker: ModuleType, path: str, body: str
) -> None:
    """經匯入別名的屬性、importlib／runpy／pkgutil、其他網路模組與額外設定來源都要被擋。"""
    assert checker.check_source(synthetic(body), path, PROJECT)


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "app/routers/example.py",
            "from app.core.deps import DbSession\n\n\ndef route(db: DbSession) -> None:\n"
            '    """合成 Router。"""\n'
            "    db.connection().exec_driver_sql('synthetic statement')\n",
        ),
        (
            "app/db/repositories/example_repository.py",
            'def save(db: object) -> None:\n    """合成交易。"""\n    with db.begin():\n        pass\n',
        ),
        (
            "app/db/repositories/example_repository.py",
            'def save(db: object) -> None:\n    """合成交易。"""\n'
            "    finish = db.commit\n    finish()\n",
        ),
        (
            "app/services/example_service.py",
            'class Example:\n    """合成服務。"""\n\n'
            '    def __init__(self, session: object) -> None:\n        """保存 Session。"""\n'
            "        self._session = session\n\n"
            '    def run(self) -> None:\n        """不可直接查詢。"""\n'
            "        self._session.execute('synthetic query')\n",
        ),
        (
            "app/core/deps.py",
            "from sqlalchemy import text\n\nQUERY = text('synthetic')\n",
        ),
        ("app/core/deps.py", "import psycopg\n"),
        ("app/core/deps.py", "from app.db.repositories import invoice_repository\n"),
        ("app/schemas/example.py", "import app\n\nVALUE = app.services\n"),
    ],
)
def test_backend_session_transaction_and_exception_scope_are_exact(
    checker: ModuleType, path: str, body: str
) -> None:
    """Router 不直接用 Session、Repository 不開交易、deps 例外不能整層放行。"""
    if PROJECT == "InvoiceGuard-AI":
        pytest.skip(BACKEND_ONLY)
    assert checker.check_source(synthetic(body), path, PROJECT)


@pytest.mark.parametrize(
    ("path", "body", "projects"),
    [
        (
            "app/utils/example.py",
            "from urllib.parse import urlsplit\n\nVALUE = urlsplit\n",
            PROJECTS,
        ),
        (
            "app/utils/example.py",
            "from importlib.metadata import version\n\nVALUE = version\n",
            PROJECTS,
        ),
        (
            "app/utils/example.py",
            '"""說明：不可自行讀取 .env，請改用 settings。"""\n'
            "from pathlib import Path\n\nNAME = Path('settings.env.example').name\n",
            PROJECTS,
        ),
        (
            "app/core/exceptions.py",
            "from app.clients.base import ApiError\n\nNAME = ApiError.__name__\n",
            ("InvoiceGuard-AI",),
        ),
        (
            "app/core/deps.py",
            "from sqlalchemy.orm import Session\n\nfrom app.db.session import get_db\n\n"
            "VALUE = (Session, get_db)\n",
            ("InvoiceGuard-AI-ADMIN", "InvoiceGuard-AI-API"),
        ),
        (
            "app/core/deps.py",
            "from app.db.models.user import User, UserRole\n"
            "from app.db.repositories import user_repository\n\n"
            "VALUE = (User, UserRole, user_repository.get_by_id)\n",
            ("InvoiceGuard-AI-ADMIN",),
        ),
        (
            "app/routers/example.py",
            "from app.core.deps import DbSession\n\n\ndef route(db: DbSession) -> DbSession:\n"
            '    """只把 Session 交給 Service。"""\n    return db\n',
            ("InvoiceGuard-AI-ADMIN", "InvoiceGuard-AI-API"),
        ),
        (
            "app/db/repositories/example_repository.py",
            'def save(db: object) -> None:\n    """只同步至交易，不提交。"""\n    db.flush()\n',
            ("InvoiceGuard-AI-ADMIN", "InvoiceGuard-AI-API"),
        ),
    ],
)
def test_precise_exceptions_and_safe_modules_stay_allowed(
    checker: ModuleType, path: str, body: str, projects: tuple[str, ...]
) -> None:
    """收緊規則後，既有 DI、ApiError 轉換與一般標準函式庫用法不能被誤擋。"""
    if PROJECT not in projects:
        pytest.skip("此例外只屬於其他站")
    assert not checker.check_source(synthetic(body), path, PROJECT)


@pytest.mark.parametrize(
    ("relative_path", "content", "expected"),
    [
        ("app/routers/example.pyc", b"synthetic bytecode placeholder", True),
        (
            "app/routers/__pycache__/example.py",
            synthetic("import psycopg\n").encode(),
            True,
        ),
        (
            "app/routers/__pycache__/example.cpython-312.pyc",
            b"synthetic orphan cache",
            True,
        ),
        ("app/routers/__pycache__/example.pyc", b"synthetic sourceless module", True),
        ("app/routers/__pycache__/__init__.pyc", b"synthetic package module", True),
        (
            "app/routers/__pycache__/nested/example.cpython-312.pyc",
            b"synthetic nested cache",
            True,
        ),
    ],
)
def test_modules_without_scanned_source_are_rejected(
    checker: ModuleType,
    standalone_project: Path,
    relative_path: str,
    content: bytes,
    expected: bool,
) -> None:
    """沒有 .py 原始碼仍可 import 的檔案，以及藏在 __pycache__ 的原始碼，不能逃過掃描。"""
    path = standalone_project / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    assert bool(checker.check_project(standalone_project)) is expected


@pytest.mark.parametrize("optimization", [None, "1", "2"])
def test_source_backed_standard_bytecode_cache_is_allowed(
    checker: ModuleType, standalone_project: Path, optimization: str | None
) -> None:
    """正常 CPython 標記快取及 opt-1／opt-2 有對應來源時不誤擋。"""
    source = standalone_project / "app/routers/governance_cache_example.py"
    source.write_text(synthetic("VALUE = 'synthetic cache'\n"), encoding="utf-8")
    target = Path(importlib.util.cache_from_source(str(source), optimization=optimization))
    target.parent.mkdir(parents=True, exist_ok=True)
    py_compile.compile(
        str(source), cfile=str(target), optimize=int(optimization or "0"), doraise=True
    )
    assert not checker.check_project(standalone_project)


@pytest.mark.parametrize("package_init", [False, True])
def test_importable_sourceless_cache_module_is_rejected(
    checker: ModuleType, standalone_project: Path, tmp_path: Path, package_init: bool
) -> None:
    """真正可匯入的 name.pyc／__init__.pyc 不得躲在 namespace 快取目錄。"""
    source = tmp_path / "synthetic_bytecode_source.py"
    source.write_text('MARKER = "governance-synthetic-bytecode"\n', encoding="utf-8")
    directory = standalone_project / "app/routers/__pycache__"
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / ("__init__.pyc" if package_init else "synthetic_payload.pyc")
    py_compile.compile(str(source), cfile=str(target), doraise=True)
    module_name = "__pycache__" if package_init else "__pycache__.synthetic_payload"
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
    }
    # -I 會忽略 PYTHONIOENCODING；固定 UTF-8，匯入失敗時的非 ASCII 錯誤訊息才不會在父程序解碼失敗。
    command = [
        sys.executable,
        "-I",
        "-B",
        "-X",
        "utf8",
        "-c",
        "import importlib, sys; sys.path.insert(0, sys.argv[1]); "
        "print(importlib.import_module(sys.argv[2]).MARKER)",
        str(directory.parent),
        module_name,
    ]
    imported = subprocess.run(
        command,
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=15,
        check=False,
    )
    assert imported.returncode == 0, imported.stderr[-500:]
    assert imported.stdout.strip() == "governance-synthetic-bytecode"
    assert any(
        issue.code == "compiled_module" for issue in checker.check_project(standalone_project)
    )


def symlink_or_skip(link: Path, target: Path) -> None:
    """只有缺少建立權限（Windows 1314、POSIX EPERM）才 skip；路徑過長、目標已存在等錯誤必須失敗。"""
    try:
        link.symlink_to(target)
    except OSError as error:
        if getattr(error, "winerror", None) != 1314 and error.errno != errno.EPERM:
            raise
        pytest.skip("本機未提供建立符號連結的權限")


@pytest.mark.parametrize(
    "error",
    [
        FileNotFoundError(errno.ENOENT, "合成路徑過長"),
        FileExistsError(errno.EEXIST, "合成連結已存在"),
        OSError(errno.ENAMETOOLONG, "合成名稱過長"),
        OSError(errno.EINVAL, "合成無效參數"),
        OSError(errno.EIO, "合成 I/O 錯誤"),
        PermissionError(errno.EACCES, "合成存取遭拒"),
        OSError(errno.ENOENT, "合成 Windows 路徑錯誤", None, 3),
        OSError(errno.ENOENT, "合成 Windows 檔名過長", None, 206),
    ],
    ids=["ENOENT", "EEXIST", "ENAMETOOLONG", "EINVAL", "EIO", "EACCES", "WinError3", "WinError206"],
)
def test_symlink_helper_does_not_report_path_errors_as_missing_privilege(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: OSError
) -> None:
    """路徑過長、已存在、EACCES／EINVAL／EIO 等非權限錯誤須原樣拋出同一例外，不能當成權限不足而 skip。"""

    def fail(self: Path, target: Path) -> None:
        raise error

    monkeypatch.setattr(Path, "symlink_to", fail)
    with pytest.raises(type(error)) as caught:
        try:
            symlink_or_skip(tmp_path / "link", tmp_path / "target")
        except pytest.skip.Exception:
            pytest.fail("路徑或檔案錯誤被誤判為權限不足而 skip")
    assert caught.value is error


@pytest.mark.parametrize(
    "error",
    [
        PermissionError(errno.EPERM, "合成權限不足"),
        pytest.param(
            OSError(errno.EINVAL, "合成權限不足", None, 1314),
            marks=pytest.mark.skipif(sys.platform != "win32", reason="WinError 1314 只在 Windows"),
        ),
    ],
)
def test_symlink_helper_skips_only_without_privilege(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, error: OSError
) -> None:
    """缺少建立符號連結的權限時明確 skip，不算通過。"""

    def fail(self: Path, target: Path) -> None:
        raise error

    monkeypatch.setattr(Path, "symlink_to", fail)
    with pytest.raises(pytest.skip.Exception):
        symlink_or_skip(tmp_path / "link", tmp_path / "target")


def test_symlink_in_bytecode_cache_is_rejected(
    checker: ModuleType, standalone_project: Path, tmp_path: Path
) -> None:
    """快取分支也必須拒絕 symlink，不因先略過 __pycache__ 而漏檢。"""
    source = standalone_project / "app/routers/governance_cache_example.py"
    source.write_text(synthetic("VALUE = 1\n"), encoding="utf-8")
    target = Path(importlib.util.cache_from_source(str(source)))
    target.parent.mkdir(parents=True, exist_ok=True)
    outside = tmp_path / "synthetic_cache.pyc"
    py_compile.compile(str(source), cfile=str(outside), doraise=True)
    symlink_or_skip(target, outside)
    assert any(
        issue.code == "source_symlink" for issue in checker.check_project(standalone_project)
    )


@pytest.mark.parametrize(
    "appended",
    [
        "\nMAX_PAGE += 90_000\n",
        '\nContractModel.model_config["extra"] = "allow"\n',
        "\nif True:\n    MAX_PAGE = 99_999\n",
    ],
)
def test_later_rewrites_of_common_contract_fail(
    checker: ModuleType, standalone_project: Path, appended: str
) -> None:
    """定義本身不變、檔尾再改常數或設定，快照仍須偵測。"""
    if PROJECT == "InvoiceGuard-AI":
        pytest.skip("前端沒有共用 DTO")
    path = standalone_project / "app/schemas/common.py"
    path.write_text(path.read_text(encoding="utf-8") + appended, encoding="utf-8")
    assert checker.check_project(standalone_project)


def test_ast_subset_includes_rewrites_but_not_unrelated_statements(
    checker: ModuleType,
) -> None:
    """只有改寫核定名稱的頂層敘述才影響子集摘要。"""
    source = "LIMIT = 4\nOTHER = 1\n"
    original = checker.ast_digest(source, ("LIMIT",))
    assert original != checker.ast_digest(source + "LIMIT += 1\n", ("LIMIT",))
    assert original != checker.ast_digest(source + "if True:\n    LIMIT = 8\n", ("LIMIT",))
    assert original == checker.ast_digest(source + "OTHER += 1\n", ("LIMIT",))


@pytest.mark.parametrize(
    "appended",
    [
        '\nif True:\n    class PageQuery:\n        """合成條件式替換。"""\n        page: int = 99999\n',
        '\ntry:\n    class PageQuery:\n        """合成例外區塊替換。"""\n        page: int = 99999\n'
        "except RuntimeError:\n    pass\n",
        "\nif True:\n    def reject_bool_and_float(value: object) -> int:\n"
        '        """合成驗證器替換。"""\n        return 1\n',
        "\nif True:\n    async def reject_bool_and_float(value: object) -> int:\n"
        '        """合成非同步替換。"""\n        return 1\n',
    ],
)
def test_conditional_contract_definitions_cannot_escape_snapshot(
    checker: ModuleType, standalone_project: Path, appended: str
) -> None:
    """if／try 裡的類別、函式與非同步函式重定義仍須改變契約摘要。"""
    if PROJECT == "InvoiceGuard-AI":
        pytest.skip("前端沒有共用 DTO")
    path = standalone_project / "app/schemas/common.py"
    path.write_text(path.read_text(encoding="utf-8") + appended, encoding="utf-8")
    assert any(
        issue.code == "contract_drift" for issue in checker.check_project(standalone_project)
    )


def test_unrelated_conditional_definitions_do_not_change_contract_digest(
    checker: ModuleType,
) -> None:
    """沒有重新綁定核定名稱的條件式定義及其 docstring，不擴大共用摘要。"""
    source = 'class Entry:\n    """核定契約。"""\n    value: int = 1\n'
    unrelated = (
        '\nif True:\n    class Other:\n        """無關類別。"""\n        value: int = 2\n'
        '\ntry:\n    async def helper() -> int:\n        """無關函式。"""\n        return 2\n'
        "except RuntimeError:\n    pass\n"
    )
    assert checker.ast_digest(source, ("Entry",)) == checker.ast_digest(
        source + unrelated, ("Entry",)
    )
    assert checker.ast_digest(source, ("Entry",)) == checker.ast_digest(
        source.replace("核定契約", "更新說明"), ("Entry",)
    )


@pytest.mark.parametrize(
    ("relative_path", "appended"),
    [
        ("app/schemas/common.py", "\nif True:\n    from typing import Any as PageQuery\n"),
        (
            "app/schemas/common.py",
            "\ntry:\n    from operator import truth as reject_bool_and_float\n"
            "except ImportError:\n    pass\n",
        ),
        ("app/schemas/common.py", "\nfrom typing import Any as PageQuery\n"),
        (
            "app/schemas/common.py",
            "\ntry:\n    raise ValueError\nexcept ValueError as reject_bool_and_float:\n    pass\n",
        ),
        ("app/schemas/common.py", "\nmatch 0:\n    case PageQuery:\n        pass\n"),
        ("app/integrations/vercel.py", "\nfrom os import getcwd as get_platform\n"),
    ],
)
def test_import_except_and_match_rebindings_cannot_escape_snapshot(
    checker: ModuleType, standalone_project: Path, relative_path: str, appended: str
) -> None:
    """import、except as 與 match 擷取同樣會重新綁定核定名稱，不能繞過子集快照。"""
    if PROJECT == "InvoiceGuard-AI":
        pytest.skip("前端沒有共用 DTO 或 Vercel 契約")
    path = standalone_project / relative_path
    path.write_text(path.read_text(encoding="utf-8") + appended, encoding="utf-8")
    assert any(
        issue.code == "contract_drift" for issue in checker.check_project(standalone_project)
    )


def test_unrelated_imports_handlers_and_captures_do_not_change_digest(
    checker: ModuleType,
) -> None:
    """未綁定核定名稱的 import、except as 與 match 擷取不擴大共用摘要。"""
    source = 'class Entry:\n    """核定契約。"""\n    value: int = 1\n'
    unrelated = (
        "\nimport statistics as unrelated_statistics\n"
        "\ntry:\n    from operator import truth as unrelated_truth\nexcept ImportError:\n    pass\n"
        "\ntry:\n    raise ValueError\nexcept ValueError as unrelated_error:\n    pass\n"
        "\nmatch 0:\n    case unrelated_value:\n        pass\n"
        "\nmatch [1]:\n    case [*unrelated_items]:\n        pass\n"
        "\nmatch {}:\n    case {**unrelated_rest}:\n        pass\n"
    )
    assert checker.ast_digest(source, ("Entry",)) == checker.ast_digest(
        source + unrelated, ("Entry",)
    )
    assert checker.ast_digest(source, ("Entry",)) != checker.ast_digest(
        source + "\nfrom typing import Any as Entry\n", ("Entry",)
    )


@pytest.mark.parametrize(
    "appended",
    [
        "\nmatch [1]:\n    case [*Entry]:\n        pass\n",
        "\nmatch {}:\n    case {**Entry}:\n        pass\n",
    ],
)
def test_match_star_and_mapping_rest_rebindings_change_subset_digest(
    checker: ModuleType, appended: str
) -> None:
    """match 的 star 與 mapping rest 擷取同樣重新綁定核定名稱，須改變子集摘要。"""
    source = 'class Entry:\n    """核定契約。"""\n    value: int = 1\n'
    assert checker.ast_digest(source, ("Entry",)) != checker.ast_digest(
        source + appended, ("Entry",)
    )


@pytest.mark.parametrize(
    ("relative_path", "appended"),
    [
        ("app/schemas/common.py", "\nif True:\n    from synthetic_overrides import *\n"),
        (
            "app/schemas/common.py",
            "\ntry:\n    from synthetic_overrides import *\nexcept ImportError:\n    pass\n",
        ),
        ("app/integrations/vercel.py", "\nif True:\n    from synthetic_overrides import *\n"),
    ],
)
def test_conditional_wildcard_imports_cannot_escape_snapshot(
    checker: ModuleType, standalone_project: Path, relative_path: str, appended: str
) -> None:
    """星號匯入可改寫任意核定名稱；DTO 與 Vercel 子集都須保留此敘述。"""
    if PROJECT == "InvoiceGuard-AI":
        pytest.skip("前端沒有共用 DTO 或 Vercel 契約")
    path = standalone_project / relative_path
    path.write_text(path.read_text(encoding="utf-8") + appended, encoding="utf-8")
    assert any(
        issue.code == "contract_drift" for issue in checker.check_project(standalone_project)
    )


@pytest.mark.parametrize(
    "appended",
    [
        "\nif True:\n    from synthetic_overrides import *\n",
        "\ntry:\n    from synthetic_overrides import *\nexcept ImportError:\n    pass\n",
        "\nfrom synthetic_overrides import *\n",
    ],
)
def test_wildcard_imports_are_retained_in_subset_digest(checker: ModuleType, appended: str) -> None:
    """頂層及條件式星號匯入皆保守納入摘要，無關的明確匯入仍不擴大子集。"""
    source = 'class Entry:\n    """合成核定契約。"""\n    value: int = 1\n'
    original = checker.ast_digest(source, ("Entry",))
    assert original != checker.ast_digest(source + appended, ("Entry",))
    assert original == checker.ast_digest(
        source + "\nif True:\n    from typing import Any as Unrelated\n", ("Entry",)
    )


@pytest.mark.parametrize(
    ("relative_path", "appended"),
    [
        ("app/schemas/common.py", "\n_synthetic = (PageQuery := dict)\n"),
        (
            "app/schemas/common.py",
            '\nclass _Synthetic:\n    """合成類別本體改寫。"""\n\n'
            "    global PageQuery\n    PageQuery = dict\n",
        ),
        (
            "app/schemas/common.py",
            '\ndef _synthetic() -> None:\n    """合成 global 改寫。"""\n'
            "    global MAX_PAGE\n    MAX_PAGE = 99_999\n\n\n_synthetic()\n",
        ),
        ("app/integrations/vercel.py", "\n_synthetic = (get_platform := dict)\n"),
        (
            "app/integrations/vercel.py",
            '\ndef _synthetic() -> None:\n    """合成 global 改寫。"""\n'
            "    global get_platform\n    get_platform = dict\n\n\n_synthetic()\n",
        ),
    ],
)
def test_rebinding_inside_unrelated_definitions_cannot_escape_snapshot(
    checker: ModuleType, standalone_project: Path, relative_path: str, appended: str
) -> None:
    """無關定義裡的海象或 global 仍會改寫核定名稱，DTO 與 Vercel 子集都須偵測。"""
    if PROJECT == "InvoiceGuard-AI":
        pytest.skip("前端沒有共用 DTO 或 Vercel 契約")
    path = standalone_project / relative_path
    path.write_text(path.read_text(encoding="utf-8") + appended, encoding="utf-8")
    assert any(
        issue.code == "contract_drift" for issue in checker.check_project(standalone_project)
    )


@pytest.mark.parametrize(
    "appended",
    [
        "\n_synthetic = (Entry := 1)\n",
        "\n_synthetic: object = (Entry := 1)\n",
        "\n_synthetic = [(Entry := value) for value in (1,)]\n",
        "\ndef _synthetic(value: object = (Entry := 1)) -> object:\n    return value\n",
        "\n@(Entry := (lambda function: function))\ndef _synthetic() -> None:\n    pass\n",
        "\nclass _Synthetic((Entry := object)):\n    pass\n",
        "\nclass _Synthetic:\n    global Entry\n    Entry = 1\n",
        "\nclass _Synthetic:\n    Entry.value = 99\n",
        "\ndef _synthetic() -> None:\n    global Entry\n    Entry = 1\n\n\n_synthetic()\n",
        "\ndef _synthetic() -> None:\n    Entry.options['extra'] = 'allow'\n\n\n_synthetic()\n",
    ],
)
def test_unrelated_definitions_that_rebind_contracts_change_subset_digest(
    checker: ModuleType, appended: str
) -> None:
    """海象、global 與屬性／索引指定即使藏在無關定義裡，仍須改變子集摘要。"""
    source = 'class Entry:\n    """合成核定契約。"""\n    value: int = 1\n'
    assert checker.ast_digest(source, ("Entry",)) != checker.ast_digest(
        source + appended, ("Entry",)
    )


def test_unrelated_definitions_that_only_read_contracts_keep_subset_digest(
    checker: ModuleType,
) -> None:
    """只讀取核定名稱的函式、子類別、別名，或只改寫自身名稱的定義，不擴大子集摘要。"""
    source = 'class Entry:\n    """合成核定契約。"""\n    value: int = 1\n'
    unrelated = (
        "\ndef build() -> object:\n    return Entry()\n"
        "\nclass Child(Entry):\n    extra: int = 2\n"
        "\nDEFAULT_VALUE = Entry.value\n"
        "\n_counter = (_local := 1)\n"
        "\ndef _reset() -> None:\n    global _state\n    _state = 0\n"
        "\nclass Holder:\n    def put(self, value: int) -> None:\n        self.value = value\n"
    )
    assert checker.ast_digest(source, ("Entry",)) == checker.ast_digest(
        source + unrelated, ("Entry",)
    )


@pytest.mark.parametrize(
    "appended",
    [
        "\ndef build() -> object:\n    global Entry\n    return Entry()\n",
        "\nclass Reader:\n    global Entry\n    mirror = Entry.value\n",
    ],
)
def test_global_declarations_that_only_read_keep_subset_digest(
    checker: ModuleType, appended: str
) -> None:
    """global 只宣告名稱作用域；沒有寫入的函式／類別不應造成契約漂移。"""
    source = 'class Entry:\n    """合成契約。"""\n    value: int = 1\n'
    assert checker.ast_digest(source, ("Entry",)) == checker.ast_digest(
        source + appended, ("Entry",)
    )


@pytest.mark.parametrize(
    "appended",
    [
        "\ndef replace() -> None:\n    global Entry\n    from builtins import dict as Entry\n\nreplace()\n",
        "\ndef replace() -> None:\n    global Entry\n    class Entry:\n        value: int = 2\n\nreplace()\n",
        "\ndef replace() -> None:\n    global Entry\n    del Entry\n\nreplace()\n",
        "\ndef replace() -> None:\n    global Entry\n    try:\n        raise ValueError\n"
        "    except ValueError as Entry:\n        pass\n\nreplace()\n",
        "\ndef replace() -> None:\n    global Entry\n    match 0:\n        case Entry:\n"
        "            pass\n\nreplace()\n",
    ],
)
def test_global_import_definition_and_delete_still_change_subset_digest(
    checker: ModuleType, appended: str
) -> None:
    """縮小只讀誤報後，global 匯入／定義／刪除及 except／match 綁定仍必須納入契約摘要。"""
    source = 'class Entry:\n    """合成契約。"""\n    value: int = 1\n'
    assert checker.ast_digest(source, ("Entry",)) != checker.ast_digest(
        source + appended, ("Entry",)
    )


@pytest.mark.parametrize(
    ("relative_path", "name"),
    [("app/schemas/common.py", "PageQuery"), ("app/integrations/vercel.py", "get_platform")],
)
def test_read_only_global_helpers_do_not_drift_project_contract(
    checker: ModuleType, standalone_project: Path, relative_path: str, name: str
) -> None:
    """DTO／Vercel 的未使用只讀 helper 不應要求更新快照。"""
    if PROJECT == "InvoiceGuard-AI":
        pytest.skip("前端沒有共用 DTO 或 Vercel 契約")
    path = standalone_project / relative_path
    appended = (
        '\ndef _synthetic_reader() -> object:\n    """合成只讀函式。"""\n'
        f"    global {name}\n    return {name}\n"
    )
    path.write_text(path.read_text(encoding="utf-8") + appended, encoding="utf-8")
    assert not checker.check_project(standalone_project)


def test_checker_runs_by_absolute_path_from_another_directory(
    standalone_project: Path, tmp_path: Path
) -> None:
    """從其他工作目錄以絕對路徑執行，仍以腳本位置判斷 Repository。"""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    environment = {
        name: value
        for name, value in os.environ.items()
        if name.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
    }
    command = [
        sys.executable,
        "-I",
        "-B",
        "-X",
        "utf8",
        str(standalone_project / "scripts/check_project.py"),
    ]
    passed = subprocess.run(
        command,
        cwd=elsewhere,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert passed.returncode == 0, passed.stdout[-500:] + passed.stderr[-500:]
    assert "PASS" in passed.stdout
    (standalone_project / "app/unapproved_layer").mkdir()
    failed = subprocess.run(
        command,
        cwd=elsewhere,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    # 未捕捉例外同樣 exit 1；兩個斷言都附上 stdout／stderr，崩潰時的中文診斷才可獨立閱讀。
    assert failed.returncode == 1, failed.stdout[-500:] + failed.stderr[-500:]
    assert "source_location" in failed.stdout, failed.stdout[-500:] + failed.stderr[-500:]
