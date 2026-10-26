"""模組名稱：scripts.check_project；功能說明：離線檢查 AI 入口、分層與版本化契約。

只解析受版控來源／非機密契約，不匯入 app、不載入環境設定、不連網或執行 SQL。
快照用來發現意外漂移，不是阻止惡意修改的安全沙箱。
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

PROJECTS = ("InvoiceGuard-AI", "InvoiceGuard-AI-ADMIN", "InvoiceGuard-AI-API")
FRONTEND, ADMIN, API = PROJECTS
SCHEMA_VERSION = 1
CONTRACT_VERSION = "1.0"
PLATFORM_NAMES = ("VercelPlatform", "get_platform", "check_configuration")
COMMON_NAMES = (
    "MAX_BIGINT",
    "MAX_PAGE",
    "reject_bool_and_float",
    "RecordId",
    "Version",
    "PageNumber",
    "PageSize",
    "ContractModel",
    "PageQuery",
    "Page",
    "Permission",
    "OperationContext",
)
SHARED_PATHS = ("app/core/environment.py",)
BACKEND_PATHS = (
    "app/integrations/storage_client.py",
    "app/db/session.py",
    "app/db/contracts.py",
    "app/schemas/files.py",
    "app/schemas/data.py",
    "app/services/data_service.py",
    "app/services/file_service.py",
)
MODEL_PATHS = (
    "app/db/base.py",
    "app/db/models/__init__.py",
    "app/db/models/user.py",
    "app/db/models/invoice.py",
    "app/db/models/audit_log.py",
    "app/db/models/job_run.py",
)
REQUIRED = (
    "AGENTS.md",
    "CLAUDE.md",
    "README.md",
    "app/main.py",
    "app/core/config.py",
    "app/core/environment.py",
    "docs/ARCHITECTURE.md",
    "docs/CODING_CONVENTIONS.md",
    "docs/DEVELOPMENT_STATUS.md",
    "docs/PROJECT_CHECKS.md",
    "docs/REVIEW_FIX_LOG.md",
    "docs/TEST_REPORT.md",
    "docs/CLAUDE_REVIEW_PROMPT.md",
    "contracts/project-contract.json",
    "scripts/check_project.py",
    ".github/workflows/project-checks.yml",
)
ALLOWED_DIRS = {
    FRONTEND: {"core", "utils", "clients", "routers", "static", "templates"},
    ADMIN: {
        "core",
        "utils",
        "routers",
        "services",
        "schemas",
        "integrations",
        "db",
        "static",
        "templates",
    },
    API: {
        "core",
        "utils",
        "routers",
        "services",
        "schemas",
        "integrations",
        "db",
        "jobs",
    },
}
NETWORK = (
    "httpx",
    "requests",
    "urllib.request",
    "urllib3",
    "http.client",
    "aiohttp",
    "socket",
    "websockets",
    "ftplib",
    "smtplib",
    "xmlrpc.client",
    "asyncio.open_connection",
)
DB_LIBRARIES = ("sqlalchemy", "psycopg", "psycopg2", "sqlite3")
SETTINGS_FILES = {"app/core/config.py", "app/core/environment.py"}
SETTINGS_LIBRARIES = ("pydantic_settings", "dotenv", "environs", "decouple")
ENVIRONMENT_READS = {
    "os.getenv",
    "os.getenvb",
    "os.environ",
    "os.environb",
    "nt.environ",
    "posix.environ",
}
# 以字串或路徑載入模組的標準函式庫；metadata／resources 只讀套件資訊，不執行程式。
DYNAMIC_MODULES = ("importlib", "runpy", "pkgutil", "imp", "zipimport")
SAFE_DYNAMIC = ("importlib.metadata", "importlib.resources")
ENV_FILE = re.compile(r"(?:^|[\\/])\.env(?:\.[^\\/]*)?$")
# 精確例外：只列出既有 DI／例外轉換真正使用的名稱，不能整層放行 app.db、DB 驅動或 clients。
DEPS_ALLOWED = {
    ADMIN: (
        "app.db.session.get_db",
        "sqlalchemy.orm.Session",
        "app.db.models.user.User",
        "app.db.models.user.UserRole",
        "app.db.repositories.user_repository",
    ),
    API: ("app.db.session.get_db", "sqlalchemy.orm.Session"),
}
FRONTEND_EXCEPTIONS_ALLOWED = ("app.clients.base.ApiError",)
SERVICE_SESSION_METHODS = {
    "query",
    "execute",
    "scalar",
    "scalars",
    "get",
    "merge",
    "add",
    "add_all",
    "delete",
    "connection",
    "exec_driver_sql",
    "bulk_save_objects",
    "bulk_insert_mappings",
    "bulk_update_mappings",
}
ROUTER_SESSION_METHODS = SERVICE_SESSION_METHODS | {
    "commit",
    "rollback",
    "flush",
    "refresh",
    "begin",
    "begin_nested",
}
# 不經 .py 原始碼也能被 import 的檔案；AST 檢查看不到內容，因此 app 內一律拒絕。
COMPILED_SUFFIXES = {".pyc", ".pyo", ".pyd", ".so", ".pyw"}
BYTECODE_CACHE = re.compile(r"(?P<stem>[a-z_][a-z0-9_]*)\.cpython-[0-9]+(?:\.opt-[0-9]+)?\.pyc")
SHARED_START = "<!-- shared-rules:start -->"
SHARED_END = "<!-- shared-rules:end -->"


@dataclass(frozen=True)
class Issue:
    """固定代碼與檔案位置；訊息不包含原始碼或設定值。"""

    path: str
    line: int
    code: str
    message: str


class _RemoveDocstrings(ast.NodeTransformer):
    """只移除定義開頭的 docstring，保留 SQL 字串及其他語意常數。"""

    def generic_visit(self, node: ast.AST) -> ast.AST:
        super().generic_visit(node)
        body = getattr(node, "body", [])
        if (
            isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body.pop(0)
        return node


def _definition_name(node: ast.AST) -> str | None:
    if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
        return node.name
    if (
        isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    ):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def _names_in(node: ast.AST) -> set[str]:
    return {item.id for item in ast.walk(node) if isinstance(item, ast.Name)}


def _import_binding(item: ast.alias) -> str:
    return item.asname or item.name.split(".")[0]


def _bound_definition_names(node: ast.AST) -> set[str]:
    """以字串儲存而非 Name 節點的綁定：定義、import、except as、match 擷取都可能重新綁定契約。"""
    names = set()
    for item in ast.walk(node):
        if isinstance(item, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(item.name)
        elif isinstance(item, (ast.Import, ast.ImportFrom)):
            names.update(_import_binding(alias) for alias in item.names if alias.name != "*")
        elif isinstance(item, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)) and item.name:
            names.add(item.name)
        elif isinstance(item, ast.MatchMapping) and item.rest:
            names.add(item.rest)
    return names


def _has_wildcard_import(node: ast.AST) -> bool:
    """星號匯入的實際綁定名稱無法由本檔靜態確定，須保留整個敘述。"""
    return any(
        isinstance(item, ast.ImportFrom) and any(alias.name == "*" for alias in item.names)
        for item in ast.walk(node)
    )


def _rebound_in_definition(node: ast.AST) -> set[str]:
    """無關定義的海象、global 寫入及屬性／索引指定仍可能改寫核定名稱。"""
    names = set()
    global_names = set()
    assigned_names = set()
    for item in ast.walk(node):
        if isinstance(item, ast.NamedExpr):
            names.add(item.target.id)
        elif isinstance(item, ast.Global):
            global_names.update(item.names)
        elif isinstance(item, ast.Name) and isinstance(item.ctx, (ast.Store, ast.Del)):
            assigned_names.add(item.id)
        elif isinstance(item, (ast.Attribute, ast.Subscript)) and not isinstance(
            item.ctx, ast.Load
        ):
            root = item.value
            while isinstance(root, (ast.Attribute, ast.Subscript)):
                root = root.value
            if isinstance(root, ast.Name):
                names.add(root.id)
    # global 宣告本身不寫入；import、定義、except/match 綁定名稱不是 Name(Store)。
    return names | (global_names & (assigned_names | _bound_definition_names(node)))


def ast_digest(source: str, names: tuple[str, ...] | None = None) -> str:
    """對語意 AST 取 SHA256；指定子集時缺少任何必要定義即拒絕。

    子集也納入之後改寫核定名稱的頂層敘述（增量指定、屬性／索引指定、if／try 內重新定義），
    以及在無關定義內以海象、global、屬性／索引指定改寫核定名稱者，
    否則定義本身不變、檔尾再修改常數或設定時快照會看不出差異。
    """
    tree = ast.parse(source)
    if names is not None:
        definitions = {_definition_name(node): node for node in tree.body if _definition_name(node)}
        if not set(names).issubset(definitions):
            raise ValueError("必要共用契約定義缺失")
        selected = set(names)
        while True:
            rewrites = [
                node
                for node in tree.body
                if (
                    _definition_name(node) is None
                    and not isinstance(node, (ast.Import, ast.ImportFrom))
                    and (
                        (_names_in(node) | _bound_definition_names(node)) & selected
                        or _has_wildcard_import(node)
                    )
                )
                or (
                    _definition_name(node) not in selected
                    and _rebound_in_definition(node) & selected
                )
            ]
            used = set().union(
                *(_names_in(definitions[name]) for name in selected),
                *(_names_in(node) for node in rewrites),
            )
            closure = selected | (used & definitions.keys())
            if closure == selected:
                break
            selected = closure
        body = []
        for node in tree.body:
            if _definition_name(node) in selected or any(node is item for item in rewrites):
                body.append(node)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                # 保留被核定定義使用的匯入，以及在頂層把核定名稱重新綁定成其他物件的匯入。
                aliases = [
                    item
                    for item in node.names
                    if _import_binding(item) in used | selected or item.name == "*"
                ]
                if aliases:
                    node.names = aliases
                    body.append(node)
        tree.body = body
    normalized = ast.dump(_RemoveDocstrings().visit(tree), include_attributes=False)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _matches(module: str, prefixes: tuple[str, ...]) -> bool:
    return any(module == prefix or module.startswith(prefix + ".") for prefix in prefixes)


def _imports(tree: ast.AST, path: str) -> tuple[list[tuple[str, int]], dict[str, str]]:
    dependencies = []
    aliases = {}
    package = list(Path(path).with_suffix("").parts[:-1])
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for item in node.names:
                dependencies.append((item.name, node.lineno))
                aliases[item.asname or item.name.split(".")[0]] = (
                    item.name if item.asname else item.name.split(".")[0]
                )
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                keep = len(package) - node.level + 1
                base = ".".join(package[: max(0, keep)] + ([base] if base else []))
            for item in node.names:
                full = base + "." + item.name if base else item.name
                dependencies.append((full, node.lineno))
                aliases[item.asname or item.name] = full
    return dependencies, aliases


def _qualified(node: ast.AST, aliases: dict[str, str]) -> str:
    if isinstance(node, ast.Name):
        return aliases.get(node.id, node.id)
    if isinstance(node, ast.Attribute):
        return _qualified(node.value, aliases) + "." + node.attr
    return ""


def _root_name(node: ast.AST) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def _forbidden(path: str, layer: str) -> tuple[str, ...]:
    """各層不可依賴的模組前綴；精確例外另由 _permitted 放行。"""
    if layer == "routers":
        return ("app.db", "app.integrations", *DB_LIBRARIES, *NETWORK)
    if layer == "services":
        return (
            "app.routers",
            "app.jobs",
            "app.clients",
            "app.db.session",
            "fastapi",
            "starlette",
            *NETWORK,
        )
    if layer == "clients":
        return ("app.routers", "app.services", "app.db", "app.jobs", "app.integrations")
    if layer == "schemas":
        return (
            "app.routers",
            "app.services",
            "app.db",
            "app.jobs",
            "app.integrations",
            "app.clients",
            *DB_LIBRARIES,
            *NETWORK,
        )
    if layer == "integrations":
        return (
            "app.routers",
            "app.services",
            "app.db",
            "app.jobs",
            "app.clients",
            *DB_LIBRARIES,
        )
    if layer == "db":
        return (
            "app.routers",
            "app.services",
            "app.jobs",
            "app.clients",
            "app.integrations",
            *NETWORK,
        )
    if layer == "utils":
        return (
            "app.routers",
            "app.services",
            "app.db",
            "app.jobs",
            "app.clients",
            "app.integrations",
            *DB_LIBRARIES,
            *NETWORK,
        )
    if layer == "core":
        upward = ("app.routers", "app.services", "app.db", "app.jobs", "app.clients")
        upward += ("app.integrations",)
        return upward if path in SETTINGS_FILES else upward + DB_LIBRARIES
    return ()


def _permitted(project: str, path: str, module: str) -> bool:
    """PROJECT_CHECKS.md 列出的精確例外；只比對完整名稱及其屬性，不放行同層其他模組。"""
    if path == "app/core/deps.py":
        return _matches(module, DEPS_ALLOWED.get(project, ()))
    if project == FRONTEND and path == "app/core/exceptions.py":
        return _matches(module, FRONTEND_EXCEPTIONS_ALLOWED)
    if project == FRONTEND and path == "app/routers/mobile_dev.py":
        return _matches(module, ("httpx",))
    return False


def check_source(source: str, path: str, project: str) -> list[Issue]:
    """解析單一 app 模組，檢查靜態相依、設定集中及既有格式約定。"""
    issues = []
    path = path.replace("\\", "/")

    def flag(line: int, code: str, message: str) -> None:
        issues.append(Issue(path, line, code, message))

    try:
        tree = ast.parse(source)
    except SyntaxError as error:
        return [Issue(path, error.lineno or 1, "python_syntax", "Python 語法錯誤")]
    if not ast.get_docstring(tree) and source.strip():
        flag(1, "module_docstring", "Python 模組需有用途 docstring")
    if not re.fullmatch(r"[a-z_][a-z0-9_]*\.py", Path(path).name):
        flag(1, "module_name", "Python 檔名需使用 snake_case")
    parts = path.split("/")
    layer = parts[1] if len(parts) > 2 else "assembly"
    dependencies, aliases = _imports(tree, path)
    # import 之外，也解析經匯入別名的屬性存取（例如 import app 後使用 app.db.session）。
    references = [
        (_qualified(node, aliases), node.lineno)
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and _root_name(node) in aliases
    ]
    session_names = {"db", "session", "db_session", "connection"}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.arg)
            and node.annotation is not None
            and _qualified(node.annotation, aliases)
            in {
                "sqlalchemy.orm.Session",
                "sqlalchemy.orm.session.Session",
                "app.core.deps.DbSession",
            }
        ):
            session_names.add(node.arg)
    # self._session = session 之類的屬性也是 Session，不能換名稱繞過 Repository。
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Name)
            and node.value.id in session_names
        ):
            session_names.update(
                target.attr for target in node.targets if isinstance(target, ast.Attribute)
            )
    forbidden = _forbidden(path, layer)
    for module, line in dependencies + references:
        if project == FRONTEND and _matches(module, ("app.db", "app.integrations", *DB_LIBRARIES)):
            flag(line, "frontend_database", "前台不可直接依賴 DB 或雲端整合")
        if _matches(module, forbidden) and not _permitted(project, path, module):
            flag(line, "layer_dependency", "相依方向違反本站分層規則")
        if (
            layer == "services"
            and _matches(module, DB_LIBRARIES)
            and module
            not in {
                "sqlalchemy.orm.Session",
                "sqlalchemy.orm.session.Session",
            }
        ):
            flag(
                line,
                "service_sql",
                "Service 只使用 Session 型別；SQL／ORM 查詢由 Repository 負責",
            )
        if path not in SETTINGS_FILES and (
            _matches(module, SETTINGS_LIBRARIES)
            or module.rsplit(".", 1)[-1] in {"BaseSettings", "SettingsConfigDict"}
        ):
            flag(line, "settings_source", "設定來源只能由既有 config／environment 管理")
        if path not in SETTINGS_FILES and _matches(module, tuple(ENVIRONMENT_READS)):
            flag(line, "settings_source", "業務模組不得直接讀取程序環境")
        if _matches(module, DYNAMIC_MODULES) and not _matches(module, SAFE_DYNAMIC):
            flag(line, "dynamic_execution", "app 不使用動態匯入或字串執行規避靜態分層")
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            parameters = node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            parameters += [arg for arg in (node.args.vararg, node.args.kwarg) if arg]
            if node.returns is None or any(
                arg.annotation is None for arg in parameters if arg.arg not in {"self", "cls"}
            ):
                flag(node.lineno, "function_types", "函式參數與回傳值需有型別註記")
        if (
            isinstance(node, ast.Name)
            and path not in SETTINGS_FILES
            and _qualified(node, aliases) in ENVIRONMENT_READS
        ):
            flag(node.lineno, "settings_source", "業務模組不得直接讀取程序環境")
        if path not in SETTINGS_FILES and (
            (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and ENV_FILE.search(node.value)
            )
            or (
                isinstance(node, ast.ClassDef)
                and any(
                    _qualified(base, aliases).rsplit(".", 1)[-1] == "BaseSettings"
                    for base in node.bases
                )
            )
        ):
            flag(
                node.lineno,
                "settings_source",
                "設定來源只能由既有 config／environment 管理",
            )
        if (
            layer == "db"
            and "repositories" in parts
            and isinstance(node, ast.Attribute)
            and node.attr in {"commit", "rollback"}
        ):
            flag(
                node.lineno,
                "repository_commit",
                "Repository 不可 commit／rollback；交易由 Service 控制",
            )
        if not isinstance(node, ast.Call):
            continue
        qualified = _qualified(node.func, aliases)
        if qualified in {
            "__import__",
            "builtins.__import__",
            "importlib.import_module",
            "eval",
            "exec",
            "builtins.eval",
            "builtins.exec",
        }:
            flag(
                node.lineno,
                "dynamic_execution",
                "app 不使用動態匯入或字串執行規避靜態分層",
            )
        if (
            layer == "db"
            and "repositories" in parts
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"begin", "begin_nested"}
        ):
            flag(
                node.lineno,
                "repository_commit",
                "Repository 不可自行開啟交易；交易由 Service 控制",
            )
        if (
            layer == "services"
            and isinstance(node.func, ast.Attribute)
            and (
                (_qualified(node.func.value, {}) in session_names)
                or (
                    isinstance(node.func.value, ast.Attribute)
                    and node.func.value.attr in session_names
                )
            )
            and node.func.attr in SERVICE_SESSION_METHODS
        ):
            flag(node.lineno, "service_sql", "ORM 查詢與新增刪除請經 Repository")
        if (
            layer == "routers"
            and project != FRONTEND
            and isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in session_names
            and node.func.attr in ROUTER_SESSION_METHODS
        ):
            flag(
                node.lineno,
                "router_database",
                "Router 只可把 Session 交給 Service，不可直接操作 DB",
            )
    return sorted(set(issues), key=lambda item: (item.path, item.line, item.code))


def _read(root: Path, relative: str) -> str:
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("來源路徑不在 Repository 內")
    return path.read_text(encoding="utf-8-sig")


def _is_source_backed_cache(path: Path, root: Path) -> bool:
    """只允許標準 CPython 具標籤快取，且來源必須在同層快取目錄外實際存在。"""
    relative = path.relative_to(root)
    match = BYTECODE_CACHE.fullmatch(path.name)
    if (
        not match
        or relative.parts.count("__pycache__") != 1
        or path.parent.name != "__pycache__"
        or not path.is_file()
        or path.is_symlink()
    ):
        return False
    source = path.parent.parent / (match["stem"] + ".py")
    return (
        source.is_file()
        and not source.is_symlink()
        and source.resolve().is_relative_to(root.resolve())
    )


def _project_name(root: Path) -> str:
    tree = ast.parse(_read(root, "app/core/config.py"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            for field in node.body:
                if (
                    isinstance(field, ast.AnnAssign)
                    and isinstance(field.target, ast.Name)
                    and field.target.id == "APP_NAME"
                    and isinstance(field.value, ast.Constant)
                    and field.value.value in PROJECTS
                ):
                    return field.value.value
    raise ValueError("無法辨識本站角色")


def _shared_rules(root: Path) -> str:
    text = _read(root, "AGENTS.md")
    if text.count(SHARED_START) != 1 or text.count(SHARED_END) != 1:
        raise ValueError("共同規範區塊缺失或重複")
    shared = text.split(SHARED_START)[1].split(SHARED_END)[0].strip()
    if not shared or SHARED_END not in text.split(SHARED_START)[1]:
        raise ValueError("共同規範區塊格式錯誤")
    return shared


def _snapshot(root: Path) -> dict[str, object]:
    value = json.loads(_read(root, "contracts/project-contract.json"))
    expected = {
        "schema_version",
        "contract_version",
        "shared",
        "backend",
        "models",
        "common",
        "platform",
        "agent_rules_sha256",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value["schema_version"] != SCHEMA_VERSION
        or type(value["schema_version"]) is not int
        or value["contract_version"] != CONTRACT_VERSION
    ):
        raise ValueError("契約快照格式或版本不合規")
    for key, paths in (
        ("shared", SHARED_PATHS),
        ("backend", BACKEND_PATHS),
        ("models", MODEL_PATHS),
    ):
        if not isinstance(value[key], dict) or set(value[key]) != set(paths):
            raise ValueError("契約快照缺少必要範圍")
        if any(
            not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
            for digest in value[key].values()
        ):
            raise ValueError("契約快照雜湊格式不合規")
    for key in ("common", "platform", "agent_rules_sha256"):
        if not isinstance(value[key], str) or not re.fullmatch(r"[a-f0-9]{64}", value[key]):
            raise ValueError("契約快照雜湊格式不合規")
    return value


def check_project(root: Path, project_root: Path | None = None) -> list[Issue]:
    """本站獨立離線檢查；指定根目錄時額外比對三站，缺站不靜默略過。"""
    root = root.resolve()
    issues = []
    for relative in REQUIRED:
        if not (root / relative).is_file():
            issues.append(Issue(relative, 1, "required_file", "缺少必要入口、規範或檢查檔案"))
    if issues:
        return issues
    try:
        project = _project_name(root)
        snapshot = _snapshot(root)
        rules = _shared_rules(root)
        if hashlib.sha256(rules.encode()).hexdigest() != snapshot["agent_rules_sha256"]:
            issues.append(Issue("AGENTS.md", 1, "agent_rules_drift", "共同規範與核定版本不一致"))
        if _read(root, "CLAUDE.md").splitlines().count("@AGENTS.md") != 1:
            issues.append(
                Issue(
                    "CLAUDE.md",
                    1,
                    "claude_import",
                    "Claude 入口需明確匯入同站 AGENTS.md",
                )
            )
        for path in (root / "app").rglob("*"):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                issues.append(Issue(relative, 1, "source_symlink", "app 來源不可使用未審查連結"))
                continue
            if "__pycache__" in path.parts:
                # 普通 name.pyc 可從 namespace package 直接 import，不能當成正常快取放行。
                cache_directory = (
                    path.is_dir()
                    and path.name == "__pycache__"
                    and path.relative_to(root).parts.count("__pycache__") == 1
                )
                if not cache_directory and not _is_source_backed_cache(path, root):
                    issues.append(
                        Issue(
                            relative,
                            1,
                            "compiled_module",
                            "__pycache__ 只可存放有對應 .py 來源的標準 CPython 快取",
                        )
                    )
                continue
            if path.is_file() and path.suffix.lower() in COMPILED_SUFFIXES:
                issues.append(
                    Issue(
                        relative,
                        1,
                        "compiled_module",
                        "app 內不可放沒有 .py 原始碼的可匯入模組",
                    )
                )
            parts = path.relative_to(root / "app").parts
            if len(parts) == 1 and (
                (path.is_dir() and parts[0] not in ALLOWED_DIRS[project])
                or (
                    path.is_file()
                    and parts[0]
                    not in {
                        "__init__.py",
                        "main.py",
                        "constants.py",
                        *({"mobile_dev.py"} if project == FRONTEND else set()),
                    }
                )
            ):
                issues.append(
                    Issue(
                        relative,
                        1,
                        "source_location",
                        "新增檔案／目錄需遵循本站既有分層",
                    )
                )
            if path.is_file() and path.suffix == ".py":
                issues.extend(check_source(_read(root, relative), relative, project))
            if "static" in parts and (
                path.name.lower().startswith(".env")
                or path.suffix.lower()
                in {
                    ".py",
                    ".pyc",
                    ".db",
                    ".sqlite",
                    ".pem",
                    ".key",
                    ".pfx",
                    ".p12",
                    ".log",
                }
                or any(
                    part.lower() in {"uploads", "private", "secrets", "credentials"}
                    for part in parts
                )
            ):
                issues.append(
                    Issue(
                        relative,
                        1,
                        "private_static",
                        "公開 static 不可放機密、上傳或 runtime 檔案",
                    )
                )
            if (
                path.is_file()
                and path.suffix == ".html"
                and "templates" in parts
                and not re.search(r"\{#[\s\S]*?@template", _read(root, relative)[:1200])
            ):
                issues.append(
                    Issue(
                        relative,
                        1,
                        "template_header",
                        "樣板檔頭需有 Jinja @template 用途備註",
                    )
                )
        groups = [snapshot["shared"]]
        if project != FRONTEND:
            groups.extend([snapshot["backend"], snapshot["models"]])
            model_files = {
                p.relative_to(root).as_posix() for p in (root / "app/db/models").rglob("*.py")
            }
            expected_models = {p for p in MODEL_PATHS if p.startswith("app/db/models/")}
            if model_files != expected_models:
                issues.append(
                    Issue(
                        "app/db/models",
                        1,
                        "model_inventory",
                        "Model 檔案集合與核定 Schema 範圍不一致",
                    )
                )
        for group in groups:
            for relative, expected in group.items():
                if ast_digest(_read(root, relative)) != expected:
                    issues.append(
                        Issue(
                            relative,
                            1,
                            "contract_drift",
                            "來源與核定契約快照不一致；需檢查跨站相容性",
                        )
                    )
        if (
            project != FRONTEND
            and ast_digest(_read(root, "app/schemas/common.py"), COMMON_NAMES) != snapshot["common"]
        ):
            issues.append(
                Issue(
                    "app/schemas/common.py",
                    1,
                    "contract_drift",
                    "共用型別、驗證或授權上下文漂移",
                )
            )
        if (
            project != FRONTEND
            and ast_digest(_read(root, "app/integrations/vercel.py"), PLATFORM_NAMES)
            != snapshot["platform"]
        ):
            issues.append(
                Issue(
                    "app/integrations/vercel.py",
                    1,
                    "contract_drift",
                    "Vercel 公開執行描述／設定檢查契約漂移",
                )
            )
        for relative in ("AGENTS.md", "README.md"):
            text = _read(root, relative)
            for match in re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text):
                target = match.group(1).split("#", 1)[0]
                if not target or ":" in target or target.startswith(("http", "../", "..\\")):
                    continue
                if not (root / target).is_file():
                    issues.append(Issue(relative, 1, "document_link", "入口引用的本機文件不存在"))
        if project_root is not None:
            for name in PROJECTS:
                peer = project_root.resolve() / name
                if not peer.is_dir():
                    issues.append(Issue(name, 1, "peer_missing", "跨站模式缺少必要 Repository"))
                    continue
                if peer.resolve() == root:
                    continue
                peer_issues = check_project(peer)
                issues.extend(
                    Issue(name + "/" + issue.path, issue.line, issue.code, issue.message)
                    for issue in peer_issues
                )
                if not peer_issues and (
                    _snapshot(peer) != snapshot
                    or _shared_rules(peer) != rules
                    or _read(peer, "scripts/check_project.py")
                    != _read(root, "scripts/check_project.py")
                ):
                    issues.append(
                        Issue(
                            name,
                            1,
                            "peer_contract_drift",
                            "跨站規範、檢查器或契約版本不一致",
                        )
                    )
    except (OSError, UnicodeError, ValueError, SyntaxError, TypeError) as error:
        issues.append(
            Issue(
                "project",
                getattr(error, "lineno", 1) or 1,
                "unreadable_contract",
                "必要來源、身分或契約無法安全讀取／解析",
            )
        )
    return sorted(set(issues), key=lambda item: (item.path, item.line, item.code))


def main(argv: list[str] | None = None) -> int:
    """成功回傳 0，任何檢查失敗回傳 1；不提供自動更新快照的捷徑。"""
    parser = argparse.ArgumentParser(description="InvoiceGuard 無密鑰專案規範檢查")
    parser.add_argument(
        "--project-root", type=Path, help="選填：含三個固定 Repository 名稱的根目錄"
    )
    args = parser.parse_args(argv)
    issues = check_project(Path(__file__).resolve().parents[1], args.project_root)
    for issue in issues:
        print(f"{issue.path}:{issue.line}: {issue.code}: {issue.message}")
    print(
        f"Project checks: {'FAIL' if issues else 'PASS'} ({len(issues)} issues; offline, no app imports)"
    )
    return int(bool(issues))


if __name__ == "__main__":
    raise SystemExit(main())
