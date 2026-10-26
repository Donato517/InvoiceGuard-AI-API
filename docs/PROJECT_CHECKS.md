# AI 協作、契約與分層檢查

## 入口與使用

`AGENTS.md` 是正式規範；`CLAUDE.md` 用 `@AGENTS.md` 匯入同一份內容。其他 AI 工具若不自動載入，開始工作時明確要求它先讀入口。規範是工作約定，不能宣稱它能強制控制每個 AI；可重現的錯誤由下列自動檢查補強。

從本站根目錄執行（只有 Python 3.12 標準函式庫也能跑檢查器）：

```powershell
.\.venv\Scripts\python.exe -B scripts/check_project.py
# 選填：含三個固定 Repository 資料夾的根目錄，由目前位置推導。
.\.venv\Scripts\python.exe -B scripts/check_project.py --project-root ..
.\.venv\Scripts\python.exe -B -m pytest -q
.\.venv\Scripts\python.exe -B -m ruff check app tests scripts
.\.venv\Scripts\python.exe -B -m ruff format --check app tests scripts
```

單站模式不尋找兄弟專案；跨站模式必須三站齊全，缺站會失敗，不默默略過。檢查器根目錄由腳本自身位置推導，不依賴 PowerShell 目前目錄或個人 C 槽路徑。exit 0 為通過、exit 1 為失敗；輸出檔案、行號及固定錯誤代碼，不輸出來源文字或設定值。不匯入 `app`、不載入 `.env`、不連 DB／網路、不執行 SQL。

## 自動檢查範圍

| 類別 | 檢查 |
|---|---|
| 規範入口 | 必要文件、CLAUDE 匯入、共同規則版本、AGENTS／README 的站內相對連結 |
| 檔案配置 | 核定 app 頂層目錄；Python snake_case、用途 docstring、函式型別；樣板 Jinja `@template` 檔頭；app 內不得有 `.pyc`／`.pyd`／`.so` 等沒有原始碼仍可 import 的模組，`__pycache__` 只允許緊鄰來源目錄、有對應 `.py` 的標準 CPython 標籤快取（含 opt-1／opt-2）；拒絕一般 `name.pyc`／`__init__.pyc`、無來源或巢狀快取及符號連結 |
| 公開靜態資源 | 拒絕已知機密／程式／runtime 副檔名及 uploads/private/secrets/credentials 目錄；不能據此推定任意圖片都能公開 |
| 分層 | Router 不直接依賴 DB／Storage，也不直接呼叫注入 Session 的查詢／寫入／交易方法；前台一般 Router 不直接 HTTP（含 http.client、urllib3、asyncio 連線）；Service 不依賴 HTTP 框架／直接 ORM 查詢；Repository 不 commit／rollback／自行 begin；低層不反向依賴 Router／Service |
| 設定 | 業務模組不得自行讀 os.getenv／getenvb／environ（含 nt／posix）、`.env` 路徑字串、建立其他 pydantic-settings／pydantic.v1／dotenv 來源或經 config 轉匯入的 BaseSettings 子類別，也不得用 importlib／runpy／pkgutil 載入器或 eval／exec 規避靜態檢查 |
| 契約 | 共用環境隔離、Vercel 公開執行描述／設定檢查介面、ADMIN/API 七份模組／契約、共用 DTO 常數／驗證器／相依匯入／授權上下文、ORM 約束／欄位／Model 檔案集合及註冊的 AST 快照 |
| 跨站 | 額外核對三站快照、共用 AGENTS 區塊、檢查器來源；兩站各自先通過本站檢查 |

相對 import、別名、函式內及 TYPE_CHECKING 內 import 都會解析；經匯入別名的屬性存取（例如 `import app` 後使用 `app.db.session`、`import urllib` 後使用 `urllib.request`）與 import 套用相同規則。AST 摘要保留驗證器函式體、SQL 字串、預設值及約束；共用子集也包含其引用的匯入、模組內 helper，以及之後改寫核定名稱的頂層敘述（增量指定、屬性／索引指定、if／try 內類別、函式與 async 函式的同名重新定義，以及 if／try 內或頂層 import、except as、match 擷取把核定名稱重新綁定；頂層或條件區塊內的 `from … import *` 無法靜態確定綁定名稱，因此保守納入整個敘述；無關的頂層變數、函式或類別若在其中以海象、global 或屬性／索引指定改寫核定名稱，也納入該定義，只讀取核定名稱者不納入；單純 global 宣告不等於寫入，須有相應的綁定／刪除，但 global import、class/def、except/match 等字串名稱綁定也會檢查），只忽略真正 module/class/function docstring、空白與備註。Model 集合與 models/__init__.py 註冊也須一致。Service／Router 的 Session 呼叫檢查使用 Session 型別、db/session 等既有命名及由它們指定的 `self` 屬性，合法 set.add 不誤擋；不是完整資料流分析。前端不具有 DB 模組，因此只檢自身共用環境及規範，持有後端契約版本作相容性參照。

## 精確例外

- `app/core/config.py` 與受它委派的 `app/core/environment.py`：設定來源／環境隔離；不能擴大成任意業務環境讀取。
- ADMIN/API `app/core/deps.py`：既有 Session／登入授權相依注入，只可引用 `app.db.session.get_db` 與 `sqlalchemy.orm.Session`；ADMIN 另可引用登入所需的 `app.db.models.user.User`／`UserRole` 與 `app.db.repositories.user_repository`。不能擴大成其他 Repository、Model、SQL 建構或 DB 驅動；確有需要時先更新本節與檢查器並經審查。
- 前端 `app/core/exceptions.py` 僅可引用 `app.clients.base.ApiError`：HTTP 錯誤轉換。
- 前端 `app/routers/mobile_dev.py` 可引用 httpx：已審查的固定 loopback health 檢查；原有 Host／Origin／Basic 防護及相關測試必須保留。這不是一般 Router 的網路通行證。
- 三站 `app/main.py` 與前端 `app/mobile_dev.py`：既有組裝入口；前端仍不得加 DB／雲端整合。
- Service 的 commit／rollback 合法；Repository 不可 commit／rollback。現有 ADMIN 登入的稽核 TODO 仍未完成。

## 契約權威與更新

`contracts/project-contract.json` 是受審查的非機密 AST 快照，三站保存同版副本；`contract_version=1.0`。API 仍是資料表結構與 Alembic 的唯一來源，ADMIN 同步 ORM。快照只描述程式定義，不能證明雲端資料表已存在或相符。

失敗時先找出真實差異；禁止為讓測試變綠而刪測試、放寬例外或自動重建快照。正式需要變更共用契約時：提出原因與相容性影響 → 同步來源／Schema／兩站與文件 → 由維護者審查快照差異與版本 → 本站及跨站檢查／回歸測試。檢查器沒有 `--update` 捷徑；不需要新增 Repository 或取得 Vercel／Supabase 管理權限。

需要更新快照時：先修改並審查來源，再以 `scripts/check_project.py` 的 `ast_digest()` 重新計算受影響項目（新增 Model 檔時同步更新檢查器的 `MODEL_PATHS`；檢查器本身三站相同），三站 `contracts/project-contract.json` 寫入相同值。共同 AGENTS 區塊（`<!-- shared-rules -->` 之間）改動時，三站 AGENTS.md 同步修改，並將區塊內文去除前後空白後的 SHA-256 寫入 `agent_rules_sha256`。

`app/core/constants.py`、`app/routers/robots.py`、`tests/unit/test_constants.py` 與 ADMIN／API 的 `app/integrations/supabase_storage.py` 是手動同步的相同檔案，檢查器不比對；修改時自行同步並逐站測試。

單站 CI 只能比對本站與核定快照，不能取得未 checkout 的另一站最新分支。同步修改程式與快照可以繞過一致性檢查，因此仍需要 PR 審查；它不是惡意程式沙箱、完整 taint analysis、秘密掃描器或安全授權實作。變數再賦值、`getattr`／`setattr`／`globals` 等反射、無關定義內以方法呼叫間接修改核定物件、以字串組出的路徑與外部工具，也不能只靠此 AST 檢查判定安全。

規範測試以 `Settings.APP_NAME` 判斷本站角色，Clone 資料夾名稱不同也能執行。單站 checkout（例如 CI）沒有兄弟 Repository 時，完整跨站比對測試會明確 skip；缺站必須失敗的行為另有測試，三站齊全的本機執行仍會跑完整比對。型別註記有無不等於完整型別正確性，Ruff／pytest 分別補上格式與行為驗證。

## CI 與處理紀錄

`.github/workflows/project-checks.yml` 在本站 checkout，以 Python 3.12 的 Windows／Linux 執行上述檢查；UI 額外執行 djLint。工作流程只有 contents:read，不要求公司 secrets，不 checkout 私有兄弟站，不含部署或 migration。套件下載只用現有 requirements-dev.txt。新增工作流程檔不代表 GitHub 已實際跑過；2026-10-26 已 Push 至 feature/python-web，遠端 CI 結果須到 GitHub Actions 確認。Vercel 原有 Git 部署整合不在此工作流程控制範圍，不能將新增 CI 視為部署授權。

測試結果與限制見 [TEST_REPORT.md](TEST_REPORT.md)；發現與修正記在 [REVIEW_FIX_LOG.md](REVIEW_FIX_LOG.md)。[CLAUDE_REVIEW_PROMPT.md](CLAUDE_REVIEW_PROMPT.md) 是歷史檢驗指令，不是現行規則。

## 官方參考

- [OpenAI AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md)
- [Claude Code 的 CLAUDE.md 與 @import](https://code.claude.com/docs/en/memory)
- [Vercel FastAPI](https://vercel.com/docs/frameworks/backend/fastapi)
- [Vercel 環境變數](https://vercel.com/docs/environment-variables)
- [Supabase PostgreSQL 連線](https://supabase.com/docs/guides/database/connecting-to-postgres)

規範測試的隔離子程序一律使用 `-I -X utf8`，父程序以 `encoding="utf-8"` 讀取輸出，避免 `-I` 忽略 PYTHONIOENCODING 時，失敗訊息因 Windows 地區編碼與父程序 UTF-8 模式不一致而無法解碼。子程序結果的斷言都附上 stdout 與 stderr 尾端；未捕捉例外同樣是 exit 1，崩潰診斷不能只靠 pytest 截斷的 repr。

快取檢查只驗證檔案配置與來源存在，不讀取或執行既有 `.pyc` 內容，也不保證其位元組碼與來源相同；不能當作惡意程式沙箱。正常快取案例使用合成來源編譯；負例另用可實際匯入的合成 `.pyc` 驗證，不以任意假位元組當成唯一證據。符號連結案例只在缺少建立權限（Windows 1314、POSIX EPERM）時 skip；Windows 會先回報路徑過長或連結已存在，這些錯誤以及 EACCES、EINVAL、EIO 等其他 OSError，都必須原樣拋出同一例外讓測試失敗，不能記成權限不足。格式參考 [PEP 3147](https://peps.python.org/pep-3147/)。
