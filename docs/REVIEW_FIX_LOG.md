# AI 協作規範檢驗與修正紀錄

## 2026-10-23 Codex：規範入口、文件對齊與離線檢查

- 範圍：三站入口／文件、版本化契約快照、標準函式庫分層檢查、無密鑰測試及單站 CI。保留既有功能與未提交工作。
- 原因：AI 入口缺失、啟動說明分散、Blob／Supabase 與 migration 例子不一致，且缺乏可重現的一致性檢查。
- 修正：AGENTS.md + CLAUDE.md、DEVELOPMENT_STATUS.md、PROJECT_CHECKS.md、README／既有規範對齊；契約保留驗證器／ORM 約束、精確組裝例外。未實作 CRUD／Storage。
- 檢驗中處理：為前台既有兩份手機開發模板補 Jinja 檔頭註解，避免新增格式檢查把舊的合法頁面誤判；沒有變更頁面邏輯。
- 內部獨立審查並修正檢查器：Service 的 set.add 誤判（改辨識 Session／既有 DB 命名）；補 Repository rollback；共用子集納入相依匯入與 helper；Model 集合及註冊納入快照；builtins.eval／exec 別名納入拒絕。均未變更業務程式。
- 初版 ORM 突變測試只改到 docstring，未改真正 CheckConstraint，故不能作退化證據；改成精確約束突變後重跑，不把該次失敗當通過。
- 本輪測試結果與限制由 TEST_REPORT.md 記錄；後續 Claude 在下方追加每個問題的嚴重度、重現方式、原因、檔案、修正與實測，不覆寫本節。
- 邊界：公司密鑰留雲端；不部署、migration、修改正式資料或 Commit／Merge／Push。

## 後續 Claude 紀錄格式

每次檢驗追加日期／版本範圍、發現／嚴重度、重現、原因、修正檔案、驗證命令與結果、未驗項目。無問題亦記錄範圍與實測。修正限本輪規範／檢查，不擴張業務功能；不可只改快照或刪測試掩蓋退化。

## 2026-10-23 最終驗證及內部覆核收斂

- 實際 checkout 三站全套與 Ruff／djLint、跨站／其他 cwd 檢查全部通過，數量及限制見 TEST_REPORT.md。
- 檢查器實際副本突變已證實能抓分層拒絕與 DTO／ORM 摘要退化；沒有靠刪測試或在實際專案改壞來演示。
- 快照首次建立時加入 Vercel 公開 metadata／設定檢查子集，保留 ADMIN session 與 API auth／cron CLI 的合理差異；三站保持同版。快照不是公司資料，也不證明資料庫已上線。
- 目前變更留在本機，GitHub CI 尚未執行；不代表其他開發者的 Clone 已同步。後續 Claude 發現本輪問題可直接修正並在本檔追加，不實作 CRUD／Storage，不以重新產生快照掩蓋錯誤。


## 2026-10-23 Claude：規範／契約／檢查器獨立檢驗與直接修正

- 範圍：三站 AGENTS.md／CLAUDE.md、README、DEVELOPMENT_STATUS、PROJECT_CHECKS、check_project.py、project-contract.json、test_project_governance.py、CI 工作流程，以及對應來源。CLAUDE.md 含單獨一行 `@AGENTS.md`；本次由 Claude 手動讀完 AGENTS.md，不宣稱任何工具一定會自動載入。
- **中 G1｜單站 CI 必然失敗**：重現方式是只複製單站來源執行 pytest，三站各 1 failed（`test_complete_peer_tree_passes_and_checker_drift_fails`）。原因是測試直接讀取 ROOT.parent 的兄弟 Repository，而 GitHub CI 只 checkout 本站。修正：缺兄弟站時明確 skip，三站齊全時照跑。檔案：tests/unit/test_project_governance.py（三站）。
- **中 G2｜Clone 資料夾改名就失敗**：重現方式是用小寫資料夾名稱複製，前台 7 failed、API 2 failed。原因是測試用資料夾名稱判斷角色，和檢查器用 APP_NAME 不一致。修正：測試改由檢查器的 `_project_name`（APP_NAME）判斷。檔案同上。
- **中 G3｜分層／設定規則可被繞過**：重現方式是把 21 個合成繞過案例交給 check_source，全部漏判，包括：
  - `import app` 後以屬性存取 app.db；
  - importlib.util／runpy／pkgutil；
  - urllib.request 屬性存取、http.client、urllib3、asyncio.open_connection；
  - 經 config 轉匯入或 pydantic.v1 的 BaseSettings、`Path('.env')`、os.getenvb／nt.environ；
  - Router 直接用注入的 Session、Repository 以 begin 或綁定 commit 開交易、Service 的 self._session；
  - deps.py 可匯入 sqlalchemy.text、psycopg 與其他 Repository。

  原因是檢查器只比對 import 名稱、網路清單不完整、deps 例外整層放行 app.db 與 DB 驅動。修正：屬性存取與 import 套用相同規則、補齊模組清單、新增 router_database 與 Repository 交易規則、deps 改成精確名稱清單。檔案：scripts/check_project.py、tests、docs/PROJECT_CHECKS.md（三站）。
- **中 G4｜沒有原始碼的模組未掃描**：重現方式是在副本放入 app/routers/x.pyc 或 app/routers/__pycache__/x.py，檢查仍 PASS。原因是只掃描 .py，而且整個 __pycache__ 都被略過。修正：新增 compiled_module 規則。
- **中 G5｜共用子集看不到檔尾改寫**：重現方式是在 common.py 檔尾加 `MAX_PAGE += 90_000`、修改 ContractModel.model_config，或在 if 區塊內重新定義，快照都不變。原因是子集摘要只取定義本身。修正：納入改寫核定名稱的頂層敘述；現有快照值不變，未重建快照。
- **低 G6｜Blob 說明矛盾**：API 的 .env.example 仍把 BLOB_READ_WRITE_TOKEN 標成「檔案儲存（Vercel Blob）」，與文件寫的「舊名稱保留、Storage 方向為 Supabase、尚未接線」矛盾。只改這行註解，沒有改變數或設定邏輯。
- 未列為問題的檢查：
  - README／AGENTS 的日常入口一致為 START.cmd 與 Repository 全名別名，內部埠只標為單站診斷；
  - migration 由 API 管理，ADMIN 只同步 Model；
  - DEVELOPMENT_STATUS 沒有把頁面、health、Protocol 寫成業務完成；
  - 未接線的工廠仍為 ModuleNotReadyError；
  - CI 只有 contents:read、無 secrets 或部署，checkout／setup-python 的 v7 tag 已線上核對存在。
- 我自己的突變案例中，CheckConstraint 錨點一度改到 docstring，不能當成退化證據；已改用精確約束重跑，這是測試腳本的錯誤，不是檢查器缺陷。
- 驗證指令與結果：各站以 `.venv\Scripts\python.exe -B scripts/check_project.py`、`-m pytest -q -p no:cacheprovider --basetemp <專案外>`、`-m ruff check --no-cache app tests scripts`、`-m ruff format --check app tests scripts`、UI 兩站加 `-m djlint app/templates --lint`，並跑 `scripts/check_project.py --project-root ..`。結果：前台 299 passed／33 skipped、ADMIN 380／8、API 375／13，其餘全部 exit 0。單站與改名副本全數通過；新測試套到舊檢查器時 API 27 failed、前台 16 failed。明細見 TEST_REPORT.md 最新一節，證據在 C:\Project\tmp\invoiceguard-claude-governance-20261023。
- 未驗收：GitHub 遠端 CI 與 Linux runner、全新 pip 安裝、真 DB／Supabase／Vercel／登入；反射與完整資料流不在靜態檢查範圍。未修改業務程式、契約快照或 STARTUP；沒有部署、migration、正式資料修改、Commit／Merge／Push，未取得或讀取公司密鑰。

## 2026-10-23 Codex：Claude G1–G6 獨立覆核與 F1–F3 修正

- **中 F1｜G4 快取分支仍可藏可匯入位元組碼**：原 checker 放行任何 __pycache__/*.pyc。外部副本實證 name.pyc／__init__.pyc 可在 namespace 路徑成功 import，check_project 卻仍回傳 0 issues。修正為只允許單層 __pycache__ 下、具標準 CPython 標籤並有對應 .py 來源的快取；拒絕一般 .pyc、孤兒／巢狀快取與 symlink。測試不只用假位元組，另以合成來源 py_compile 產生可實際匯入的兩類 .pyc。正常及 opt-1／opt-2 快取保留正例。本機既有 app 快取唯讀盤點前台 0、ADMIN 45、API 32 個，均符合，沒有清除任何檔案。此為配置／來源存在檢查，不讀或驗證既有快取內容。
- **中 F2｜G5 仍漏條件式類別／函式重定義**：ast.Name 不包含 ClassDef/FunctionDef/AsyncFunctionDef 的字串 name。common.py 檔尾在 if/try 內重新定義 PageQuery 或驗證器時，原子集摘要可保持相同。修正另收集這些定義名稱；四個類別／函式／async 負例必須產生 contract_drift，無關定義及僅改 docstring 保留正例。既有契約快照不變，沒有為了通過而重建。
- **中 F3｜Windows 隔離子程序輸出編碼不一致**：治理測試以 -I 啟動 checker，子程序忽略父程序 PYTHONUTF8；本機子程序用 CP950，父測試用 UTF-8 解碼，六份單站/改名副本都重現 UnicodeDecodeError，接著 stdout=None／TypeError。子程序加 -X utf8，成功／失敗兩次 subprocess.run 明確 encoding='utf-8'；保留 -I、白名單、exit 1 與 source_location 負向斷言。修正後六份均通過，另 API 父程序非 UTF-8 也通過。
- 修改檔案（每站同版）：scripts/check_project.py、tests/unit/test_project_governance.py、docs/PROJECT_CHECKS.md、本檔及 docs/TEST_REPORT.md。限定規範檢查與測試，未改 app 業務、Schema／ORM、雲端、依賴、CI 或 STARTUP。
- 驗證：各站 own venv 執行 check_project.py、全套 pytest、Ruff check/format；UI djLint、跨站比對、其他 cwd 的 -I 啟動皆通過。實際數量、指令、證據與未驗項目見 TEST_REPORT.md 本輪最新節。舊版負例 10 failed 為有效性證據，非新版失敗。
- 稽核：三站 HEAD／branch／status／index 保留，15 個核定既有檔案以外來源不變。公司密鑰留雲端；沒有部署、migration、正式資料修改、Commit／Merge／Push。遠端 CI／Linux／正式服務未驗證，不宣稱通過。


## 2026-10-23 Claude：F1–F3 覆核、單站 CI 與改名 Clone

- 範圍：三站最新未提交的 checker、治理測試、PROJECT_CHECKS、契約快照與 CI；重點驗證 F1–F3，並在六份隔離副本驗證單站 CI 與改名 Clone。F1、F2 原定案例與 F3 皆重現有效，詳見 TEST_REPORT.md 最新一節。
- **中 F2-a｜import／except／match 仍可重新綁定核定契約**
  - 重現：在 common.py 加入 `if True: from typing import Any as PageQuery`、`try: from operator import truth as reject_bool_and_float`、檔尾頂層 `from typing import Any as PageQuery`、`except ValueError as reject_bool_and_float`、`match 0: case PageQuery`，或在 vercel.py 加入 `from os import getcwd as get_platform`，子集摘要都不變；專案層級沒有 contract_drift。
  - 原因：`_bound_definition_names` 只收 class／def／async def；頂層 import 只在被核定定義使用時才保留，不檢查它是否改寫核定名稱。
  - 修正：綁定名稱另收 import、except as、match 擷取（MatchAs／MatchStar／MatchMapping rest）；頂層 import 若綁定核定名稱就納入摘要。現有程式摘要不變，未重建快照。檔案：scripts/check_project.py、docs/PROJECT_CHECKS.md（三站同步）。
- **低 F3-a｜F1 匯入證明測試的子程序編碼**
  - 重現：子程序有 `-I`，沒有 `-X utf8` 與 encoding。父程序 PYTHONUTF8=1 時，若子程序錯誤訊息含非 ASCII，讀取會 UnicodeDecodeError，stderr 為 None，斷言訊息變成 TypeError。
  - 修正：比照 F3 加上 `-X utf8` 與 `encoding="utf-8"`，沒有使用 errors=，也沒有放寬斷言。檔案：tests/unit/test_project_governance.py（三站同步）。
- 新增回歸測試：`test_import_except_and_match_rebindings_cannot_escape_snapshot`（6 個案例，後端專屬）、`test_unrelated_imports_handlers_and_captures_do_not_change_digest`（三站）。在專案外副本套用修正前的 checker 時 7 failed，修正後通過。
- 驗證指令與結果：
  - 三站以自己的 venv 執行 `python -B scripts/check_project.py`、`python -B -m pytest -q -p no:cacheprovider --basetemp <本輪專案外目錄>`、`python -B -m ruff check --no-cache app tests scripts`、`python -B -m ruff format --check --no-cache app tests scripts`；UI 兩站加 `python -B -m djlint app/templates --lint`，再跑 `--project-root ..`。
  - 全套 pytest：前台 309 passed／44 skipped、ADMIN 400／9、API 395／14，其餘全部 exit 0，三站齊全時完整跨站測試 1 passed。
  - 六份隔離副本：checker exit 0；治理測試前台 92／45、ADMIN 127／10、API 122／15；完整跨站測試 skip；明確 --project-root 缺站 exit 1；他處 -I 絕對路徑 exit 0。
  - F1 三站各 12／12；F3 在兩種 PYTHONUTF8 模式加中文 basetemp 下各 3 passed。
- 未驗證：GitHub 遠端 CI、Linux runner、symlink 負例（WinError 1314，skip 不算通過）、全新 pip 安裝、真登入／DB／Storage／Vercel。
- 保留：快取檢查不驗證位元組碼內容；無來源的標籤快取依規範一律拒絕，開發者刪除或改名模組後，需先清掉舊的 __pycache__ 再跑檢查。
- 邊界：只修改三站的 checker、治理測試、PROJECT_CHECKS、本檔與 TEST_REPORT。契約快照、AGENTS 共同規則、業務程式、CI、STARTUP 皆未改；未讀取公司密鑰；沒有部署、migration、正式資料修改、Commit／Merge／Push。證據在 C:\Project\tmp\invoiceguard-claude-governance-followup-20261023。

## 2026-10-23 Codex：獨立驗收 F1–F3、重新綁定與六份 Clone

- 實際重新執行三站完整測試、F1/F2/F3 探測及六份固定名/改名的獨立來源副本完整 pytest；保存非機密來源與 Git/index 基準，未僅採用前輪報告。
- **中 R1｜條件式星號匯入漏掉契約改寫**：在 common.py 檔尾加 if True: from synthetic_overrides import *，舊 checker 不產生 contract_drift。外部完全合成 Entry 類別與模組實證名稱被改寫，舊摘要卻相同。原因：綁定收集器排除 *，而該匯入無 ast.Name 指向核定名稱，故整個條件敘述被略過。
- 修正：新增 _has_wildcard_import；條件式星號匯入無法由本檔確定實際名稱，因此整個敘述保守納入子集。頂層星號匯入、明確無關匯入的既有行為保留。沒有載入或追查外部套件，不擴張成完整資料流分析。
- 測試：新增 6 案例，涵蓋 common DTO/Vercel 專案層與 if/try/頂層子集。外部新舊控制為舊版 5 failed/1 passed（預期）、新版 6 passed；實際來源快照仍相同。修正後再次跑完三站、六份副本、F1–F3；數量及證據見 TEST_REPORT.md 最新節。
- 修改檔案（三站同步）：scripts/check_project.py、tests/unit/test_project_governance.py、docs/PROJECT_CHECKS.md、docs/TEST_REPORT.md、本檔。快照、AGENTS 規則、業務、CI、依賴與 STARTUP 未改。
- 驗收腳本自身曾有一處括號語法錯誤，在案例開始前失敗，已修正並重跑；保留限制紀錄，不視為專案問題。沒有刪除舊證據或實際專案快取。
- 邊界：公司密鑰留雲端，不實作 CRUD/Storage，不連真服務、不部署/migration/操作正式資料、不 Commit/Merge/Push；Git branch/HEAD/index 與既有工作保留。遠端 CI/Linux/正式服務及無權建立的 symlink 未驗證。

稽核方法補註：未追蹤檔以單次 Git -c 選項避免全域 LF/CRLF 轉換警告，並將 CR 視為合法行尾；不改使用者 Git 設定。--no-index 因檔案內容不同可回傳 1，須連同診斷、LF/CRLF 乾淨控制、故意行尾空白控制及逐行檢查判斷。初次稽核腳本曾將此回傳碼/換行警告誤判，已校正；另移除本輪報告追加時產生的結尾空行，不視為應用缺陷。


## 2026-10-23 Claude：R1 覆核、F2-b 無關定義內重新綁定、F3-b 失敗診斷

- 範圍：三站最新未提交的 checker、治理測試、PROJECT_CHECKS、契約快照與 CI；驗證 R1、F1–F3 及六份固定名／改名隔離副本。R1 有效，新舊對照與 Codex 回報一致（後端舊版 5 failed／1 passed、新版 6 passed）；詳見 TEST_REPORT.md 最新一節。
- **中 F2-b｜無關的頂層定義內，仍可重新綁定或修改核定名稱**
  - 重現：在 common.py 加 `_synthetic = (PageQuery := dict)`、class 本體 `global PageQuery` 後重新指定，或含 `global MAX_PAGE` 的函式在頂層被呼叫；在 vercel.py 加 `_synthetic = (get_platform := dict)`。子集摘要不變，整個專案檢查 0 issue。合成模組實際匯入後，名稱確實被替換或修改（共 11 種寫法）。
  - 原因：子集只從「非定義」的頂層敘述找改寫；單一名稱指定、def、class 被視為定義，不在核定閉包中就整個略過。但它們的值、預設值、裝飾器、基底類別與 class 本體在匯入時執行，函式也可能以 `global` 改寫模組層名稱。
  - 修正：新增 `_rebound_in_definition`。無關定義只要以海象、`global`，或以核定名稱為根的屬性／索引指定或刪除改寫核定名稱，就納入子集摘要。只讀取核定名稱的定義（函式、子類別、別名）不納入；不追蹤方法呼叫、反射或資料流。現有摘要不變，未重建快照。
- **低 F3-b｜絕對路徑隔離測試失敗時未附 stderr**：斷言訊息只帶 stdout，中文 stderr 只出現在 pytest 截斷的 repr 裡。已改成附上 stderr 尾端；`-I -X utf8`、`encoding="utf-8"` 與原有斷言都保留。
- 新增回歸測試：`test_rebinding_inside_unrelated_definitions_cannot_escape_snapshot`（5 例，後端）、`test_unrelated_definitions_that_rebind_contracts_change_subset_digest`（10 例，三站）、`test_unrelated_definitions_that_only_read_contracts_keep_subset_digest`（三站）。對 R1 版 checker，後端 15 failed、前台 10 failed；修正後全部通過。
- 驗證：三站以自己的 venv、OS 環境白名單與專案外 TEMP／basetemp 執行 check_project、全套 `pytest -q -p no:cacheprovider`、Ruff check／format（--no-cache）、UI 兩站 djLint、`--project-root ..`，全部 exit 0。全套 pytest：前台 323 passed, 52 skipped、ADMIN 422 passed, 9 skipped、API 417 passed, 14 skipped；六份副本：前台 322 passed, 53 skipped、ADMIN 421 passed, 10 skipped、API 416 passed, 15 skipped（改名副本相同）。F1 每站符合預期（symlink skip）；F3 兩種模式加中文路徑通過，中文失敗訊息可讀。
- 未驗證：GitHub 遠端 CI、Linux runner、symlink 負例、全新 pip 安裝、真登入／DB／Storage／Vercel。
- 邊界：只修改三站的 checker、治理測試、PROJECT_CHECKS、本檔與 TEST_REPORT。契約快照、AGENTS、業務程式、CI、STARTUP 皆未改；未讀取公司密鑰；沒有部署、migration、正式資料修改、Commit／Merge／Push，也沒有修改 Git 全域設定。證據在 C:\Project\tmp\invoiceguard-claude-governance-r1-20261023。

## 2026-10-23 Codex：完整獨立驗收 F2-b／F3-b 與只讀 global 誤報修正

- 範圍：實際重跑三站完整 pytest、R1、F1–F3、F2-b/F3-b 的合成執行與新舊故障控制，並重新建立六份單站／改名來源副本完整測試。保留全部既有 Git/索引與非機密來源基準；沒有沿用先前聚焦測試當完整驗收。
- **低 R2｜只讀 global 宣告造成摘要誤報**：函式 `global Entry; return Entry()` 與 class 本體 `global Entry; mirror = Entry.value` 實際匯入不改寫 Entry，舊 `_rebound_in_definition` 仍將其視為改寫，違反只讀 helper 不擴大摘要的規範。
- 原因：遇到 Global 節點就直接納入名稱，沒有判斷相同名稱是否實際綁定或刪除。修正為 global 名稱與 Name(Store/Del) 或 import/定義/except/match 字串名稱綁定的交集；保留海象及屬性／索引改寫的檢查。沒有放行真正 global 賦值/匯入/定義/刪除，也沒有擴張完整資料流分析。
- 新增 7 案例：2 個只讀摘要正例、3 個 global import/class/del 負例、2 個 DTO/Vercel 專案正例。外部 API 舊版 4 failed/3 passed、新版 7 passed；所有既有改寫負例仍通過，新舊快照相同，未重建快照。
- 修改：三站 scripts/check_project.py、tests/unit/test_project_governance.py、docs/PROJECT_CHECKS.md、docs/TEST_REPORT.md、本檔，共 15 檔。其他 app 業務、Schema/ORM、設定、依賴、CI、AGENTS、STARTUP 均不改。
- 修正後完整重驗結果與實際命令/證據見 TEST_REPORT 最新節：前台 328 passed/54 skipped、ADMIN 429/9、API 424/14；六份副本各為前台 327/55、ADMIN 428/10、API 423/15。Ruff/djLint/checker/跨站與所有正常／預期故障控制均符合預期。symlink 權限不足明確 skip，不算通過。
- 驗收器自身一度把其他 write_text 的 encoding 算進安全斷言，中止該外部控制；修正成只處理兩個子程序測試後，以新副本完整重跑，不視為專案問題、不刪舊證據。
- 邊界：公司密鑰留雲端，不讀秘密檔、不連公司服務、不實作 CRUD/Storage、不部署/migration/改正式資料/Commit/Merge/Push。Git 分支/HEAD/index/status 與快照保持原狀。遠端 CI/Linux/全新安裝/正式服務與無權建立的 symlink 未驗證。


## 2026-10-23 Claude：R2 驗收、T1 缺少的綁定回歸測試、F3-c 失敗路徑診斷

- 範圍：實際重跑 R2、R1、F1–F3、F2-b／F3-b 與六份固定名／改名隔離副本。R2 修正有效：只讀 global 不再改變摘要，global 賦值／刪除／import／class／def／except／match 等寫入仍被偵測；API／ADMIN 的 7 例新舊對照為 F2-b 版 4 failed／3 passed、R2 版 7 passed。詳見 TEST_REPORT.md 最新一節。
- **低 T1｜match star／mapping rest 與 global 搭配 except／match 的綁定沒有回歸測試**
  - 重現：在 API 專案外副本做三個突變（拿掉 MatchStar、拿掉 MatchMapping rest、讓 global 忽略 except／match 綁定），現有治理測試全部通過，突變存活。
  - 原因：這些規則只在 checker 與文件中，測試只覆蓋 match 一般擷取、頂層 except as，以及 global 的 import／class／del。
  - 修正：新增 `test_match_star_and_mapping_rest_rebindings_change_subset_digest`（2 例，三站執行）；`test_global_import_definition_and_delete_still_change_subset_digest` 增加 except as 與 match 擷取 2 例；無關綁定正例加入無關 star／rest 擷取。9 個突變全部被殺；checker 未修改。
- **低 F3-c｜絕對路徑測試第二次執行的斷言未附 stdout／stderr**
  - 重現：專案外副本讓 checker 只在掃到未核定目錄時拋中文 RuntimeError；未捕捉例外同樣 exit 1，第一個斷言通過，第二個斷言失敗時中文診斷只在截斷 repr 中，且被從字中間截斷。
  - 修正：兩個斷言都附上 stdout 與 stderr 尾端，並加註原因；`-I -X utf8`、`encoding="utf-8"` 與原斷言都保留。修正後三站兩種模式都以獨立 `E` 行顯示中文診斷。
- 驗證：三站以自己的 venv、OS 環境白名單與專案外 TEMP／basetemp 執行 check_project、全套 `pytest -q -p no:cacheprovider`、Ruff check／format（--no-cache）、UI 兩站 djLint、`--project-root ..`，全部 exit 0。全套 pytest：前台 332 passed, 54 skipped、ADMIN 433 passed, 9 skipped、API 428 passed, 14 skipped；六份副本：前台 331 passed, 55 skipped、ADMIN 432 passed, 10 skipped、API 427 passed, 15 skipped（改名副本相同）。F1 每站符合預期（symlink skip）；F3 兩種模式加中文路徑通過，故意失敗控制依預期核對。
- 修改檔案（三站同步）：tests/unit/test_project_governance.py、docs/PROJECT_CHECKS.md（補註子程序斷言附 stdout／stderr）、docs/TEST_REPORT.md、本檔。checker、契約快照、AGENTS、業務程式、CI、STARTUP 皆未改。
- 未驗證：GitHub 遠端 CI、Linux runner、symlink 負例、全新 pip 安裝、真登入／DB／Storage／Vercel。
- 邊界：未讀取公司密鑰；不實作 CRUD／Storage；未啟動服務或 Tunnel；沒有部署、migration／seed、正式資料修改、Commit／Merge／Push／reset，也沒有修改 Git 全域設定。突變與新舊對照只在專案外副本。證據在 C:\Project\tmp\invoiceguard-claude-governance-r2-20261023。

## 2026-10-23 Codex：最新版 R1／R2、T1／F3-c 完整獨立驗收

- 結論：未發現本輪範圍內需要新增修正的專案缺陷；不為了產生修正而改動程式。Claude 的 T1 4 個回歸案例與 F3-c 第二次執行診斷已獨立驗證有效。
- 實測：三站完整 pytest 前台 332 passed/54 skipped、ADMIN 433/9、API 428/14；六份固定名／改名單站副本各為前台 331/55、ADMIN 432/10、API 427/15。checker、Ruff、djLint 與完整跨站檢查均 exit 0。單站缺兄弟的 skip／明確 --project-root 失敗／APP_NAME 角色識別均符合規範。
- R1/R2/F2-b：實際匯入合成模組與來源副本雙重驗證；R2 29 案例（6 只讀、23 寫入）0 個非預期；歷史版本控制重現漏判／誤報，不重建契約快照。F1 每站 13 符合預期、1 symlink 權限 skip；F3 兩種模式與兩種路徑正常 36 次目標案例通過。
- T1：三站各 9/9 突變被整份治理測試抓到，且無收集錯誤；API 舊測試控制重現 M1–M3 存活、其餘 6 個被抓到，證明新增案例補上原缺口。
- 驗收器首輪 T1 basetemp 過長造成 Windows py_compile 路徑錯誤，原紀錄保留且不納入判定；改用短路徑，加入 4 組未突變控制，完整重跑 36 組並核對對應 assertion failure。不是專案缺陷，未為此修改專案測試。
- F3-b/F3-c：首輪 checker／合成匯入故障與第二輪 checker 故障，皆在外部副本注入中文例外；最新版訊息獨立可讀。第二輪跨三站、兩模式、兩路徑共 12 組依預期在 source_location 斷言失敗。只附 stdout／移除第二次診斷／移除編碼保護的控制均重現退化。預期失敗與正常通過分開記錄。
- 修改：僅三站 docs/TEST_REPORT.md 與本檔，共 6 份記錄；未修改 checker、治理測試、PROJECT_CHECKS、快照、AGENTS、CI、業務或 STARTUP。最終基準稽核確認 branch/HEAD/index/status 及未列為更新的非機密檔案不變；另檢查 55 個未追蹤檔空白，沒有變更全域 Git 設定。
- 證據：C:/Project/tmp/invoiceguard-full-acceptance-t1-20261023-01，含命令／JUnit／日誌／版本控制、final-audit.json 與 SHA256SUMS；詳細數量與限制見 TEST_REPORT 最新節。
- 未驗證：遠端 CI、Linux、全新安裝、無權建立的 symlink、公司真登入/DB/Storage/Vercel。公司密鑰留雲端；沒有實作 CRUD/Storage、啟服務/Tunnel、部署、migration/seed、正式資料修改或 Commit/Merge/Push。


## 2026-10-23 Claude：最新版獨立驗收與 F1-c symlink 誤標修正

- 範圍：實際重跑三站完整檢查、R1／R2、F1–F3／F3-b／F3-c、T1 九種突變（三站各自 JUnit 判定）、六份最新工作區隔離副本。歷史 checker 與舊測試先依 historical-versions.json 核對雜湊，全部吻合。R1、R2、T1、F3-c 修正均有效；突變三站各 9／9，舊測試控制 M1–M3 存活、其餘 6 種被抓到。
- **低 F1-c｜symlink 測試把路徑錯誤記成「權限不足」而 skip**
  - 重現：修正前測試（`0ea3bfda…`）在 basetemp 長度 150／160 時，`symlink_to` 實際拋 `FileNotFoundError winerror=3`（路徑過長），測試卻 skip 為「本機未提供建立符號連結的權限」；長度 120 才是真正的 WinError 1314。
  - 原因：`except OSError` 一律 skip，Windows 會先回報路徑或已存在錯誤，才檢查權限。
  - 修正：新增 `symlink_or_skip`，只有 WinError 1314／EPERM 才 skip；新增 2 個路徑錯誤負例與 2 個權限 skip 正例。改回捕捉所有 OSError 時新測試 2 failed；修正後 150／160 會以 FileNotFoundError 失敗並顯示原因。
  - 修改檔案（三站同步）：tests/unit/test_project_governance.py、docs/PROJECT_CHECKS.md、docs/TEST_REPORT.md、本檔。checker、契約快照、AGENTS、業務程式、CI、STARTUP 與其 SHA256SUMS.txt 皆未改。
- 驗證：三站以自己的 venv、OS 環境白名單、短路徑 TEMP／basetemp（先建立父目錄）與 JUnit 執行 check_project、全套 `pytest -q -p no:cacheprovider`、Ruff check／format（--no-cache）、UI 兩站 djLint、`--project-root ..`，全部 exit 0。修正後全套 pytest：前台 336 passed, 54 skipped、ADMIN 437 passed, 9 skipped、API 432 passed, 14 skipped；六份副本：前台 335 passed, 55 skipped、ADMIN 436 passed, 10 skipped、API 431 passed, 15 skipped（改名副本相同）。
- 驗收器自身的錯誤（不是專案問題，原始輸出保留）：M7／M8 的必要案例名稱原本只對新測試有效，舊測試控制被誤判為 INVALID，已依實際案例重新判讀同一批 JUnit；STARTUP SHA256SUMS.txt 的 CRLF 讓 GNU sha256sum 解析失敗，改為讀取時去除 CR 後驗證通過。
- 未驗證：GitHub 遠端 CI、Linux runner（含 1314 案例在 Linux 會 skip 的計數）、全新 pip 安裝、有權限的 symlink 真負例、真登入／DB／Storage／Vercel。
- 邊界：未讀取 .env 或公司密鑰、未執行 vercel env pull、未連正式服務；不實作 CRUD／Storage；未啟動服務或 Tunnel；沒有部署、migration／seed、正式資料修改、Commit／Merge／Push／reset，也沒有修改 Git 全域設定。突變與新舊對照只在專案外副本。證據在 C:\Project\tmp\invoiceguard-claude-acceptance-r6-20261023。

## 2026-10-23 Codex：F1-c 最新版完整獨立驗收

- 結論：F1-c 修正有效，未發現需要新增修正的專案缺陷。未為產生修正而更改 checker、測試或快照；本輪只追加三站各自 TEST_REPORT.md／本檔，共 6 檔。
- 完整實測：前台 336 passed/54 skipped、ADMIN 437/9、API 432/14；六份固定名／改名單站副本各為前台 335/55、ADMIN 436/10、API 431/15。checker、Ruff、djLint、完整跨站及寫報告後重驗均通過；skip 不算通過。
- F1-c：每站 10 種合成錯誤分類、真實短路徑/既有檔案/275 字元長路徑均符合預期。只有 EPERM/1314 skip，其餘同一例外原樣拋出。basetemp 120 為真權限 skip、150/160 明確以 WinError 3 失敗。最新回歸各 4 passed；還原 catch-all 各 2 failed/2 passed，兩個失敗均為預期路徑負例。
- R1/R2/F1–F3/F2-b/F3-b/F3-c 全部獨立重跑，正常與故障控制符合預期；R2 29 種合成實際匯入、T1 新版三站各 9/9、API 舊測試控制 M1–M3 存活，皆有證據。F3-c 確認實際第二次執行在 source_location 斷言失敗，中文診斷可讀；詳見 TEST_REPORT 最新節。
- 執行期間 Claude 追加六份報告，來源防護安全中止部分副本／控制；確認程式/Git 不變後保存新舊基準，保留並接續其最新紀錄，再完整重跑最終六份副本及歷史控制。之後 TEST_REPORT 再補充時，寫入前防護亦阻止覆寫；穩定 20 秒後保留測試副本基準與最後文件基準，接續最新內容。公開 .env.example 已補入基準與最終副本；實際 .env 仍排除。沒有覆寫他人修改。
- 稽核：branch/HEAD/index/status 不變，共用來源／文件／快照一致，非機密未追蹤檔亦有空白檢查。STARTUP 校驗清單讀取時處理 CRLF、逐筆核對，原檔完全不改。
- 證據與校驗：C:/Project/tmp/ig-accept-f1c-20261023-01，含命令、JUnit、日誌、原始/公開範本/更新後基準、final-audit 與 SHA256SUMS。
- 未驗證遠端 CI/Linux/全新安裝/有權限 symlink 真負例/公司真服務；公司密鑰留雲端。不實作 CRUD/Storage、不啟服務/Tunnel、不部署/migration/seed/改正式資料/Commit/Merge/Push，不改 Git 全域設定。


## 2026-10-23 Claude：最新版獨立驗收與 F1-d helper 回歸補強

- 範圍：實際重跑三站完整檢查、F1-c（分類、真實 Windows、長路徑、新舊控制）、R1／R2、F1–F3／F3-b／F3-c、T1 九種突變（新版三站與 T1 前舊測試）、六份最新工作區隔離副本。歷史版本雜湊全部吻合。F1-c、R1、R2、T1、F3-c 修正均有效。
- **低 F1-d｜symlink helper 的回歸測試範圍太窄**
  - 重現：專案外副本把 helper 改成「只重拋 ENOENT／EEXIST」、「把 EINVAL 當成權限不足」或「包成新的例外物件」，原有 4 個回歸案例全部通過，三種突變在三站都存活。
  - 原因：負例只有 ENOENT、EEXIST，且只檢查例外型別，不檢查例外物件身分。
  - 修正：負例擴充為 ENOENT、EEXIST、ENAMETOOLONG、EINVAL、EIO、EACCES、WinError 3、WinError 206 共 8 例，並斷言拋出的是原例外物件。修正後三站 helper 測試 10 passed，4 種 helper 突變全部被抓到。
  - 修改檔案（三站同步）：tests/unit/test_project_governance.py、docs/PROJECT_CHECKS.md、docs/TEST_REPORT.md、本檔。checker、契約快照、AGENTS、CI、業務程式、STARTUP 與其 SHA256SUMS.txt 皆未改。
- 驗證：三站以自己的 venv、OS 環境白名單、短 TEMP／basetemp（先建立父目錄）與 JUnit 執行 check_project、全套 `pytest -q -p no:cacheprovider`、Ruff check／format（--no-cache）、UI 兩站 djLint、`--project-root ..`，全部 exit 0。修正後全套 pytest：前台 342 passed, 54 skipped、ADMIN 443 passed, 9 skipped、API 438 passed, 14 skipped；六份副本：前台 341 passed, 55 skipped、ADMIN 442 passed, 10 skipped、API 437 passed, 15 skipped（改名副本相同）。T1 新版三站各 9／9，舊測試控制 M1–M3 存活、其餘 6 種被抓到。
- 未驗證：GitHub 遠端 CI、Linux runner、全新 pip 安裝、有權限時 checker 拒絕真實 symlink 的負例、真登入／DB／Storage／Vercel。
- 邊界：未讀取實際 .env 或公司密鑰、未執行 vercel env pull、未連正式服務；不實作 CRUD／Storage；未啟動服務或 Tunnel；沒有部署、migration／seed、正式資料修改、Commit／Merge／Push／reset，也沒有修改 Git 全域設定。突變與新舊對照只在專案外副本。證據在 C:\Project\tmp\invoiceguard-claude-acceptance-r7-20261023。

## 2026-10-23 Codex：F1-c／F1-d、H1–H4 完整獨立驗收

- 結論：未發現本輪範圍內需新增修正的專案缺陷；F1-d 的八種負例與例外物件身分保護有效，helper／checker／快照不需修改。本輪只追加三站 TEST_REPORT.md／本檔，共 6 檔。
- 實際完整測試：前台 342 passed/54 skipped、ADMIN 443/9、API 438/14；固定名／改名副本各為前台 341/55、ADMIN 442/10、API 437/15。checker、Ruff、djLint、完整跨站與寫報告後複驗皆通過，skip 不算通過。
- F1-c/F1-d：每站 10 種錯誤分類均正確且非權限錯誤原樣拋出同物件；真 Windows 短連結 1314 skip，已存在檔案 183／275 字元長路徑 3 原樣失敗；長 basetemp 120 是權限 skip，150/160 在 helper 以 WinError 3 失敗，沒有被誤標。
- H1–H4：三站分別跑最新十例與歷史四例，相同 helper AST、歷史 SHA256 已核對。新版共抓到 12/12；舊版僅 H1 被抓到，H2/H3/H4 均存活。未突變控制均通過，JUnit 確認失敗僅為預期負例斷言／明確 pytest.fail，不接受無關錯誤。H1 新版 8 failed/2 passed、舊版 2 failed/2 passed；H4 新版 8 failed/2 passed、舊版 4 passed。
- R1/R2、F1–F3、F2-b/F3-b、T1、F3-c 已全部重新實測：R2 合成 29／來源 20 例符合預期；F2 兩站各 59 種刺激由獨立驅動重新判定，另各 22 個來源控制；T1 新版各 9/9、舊測試 M1–M3 存活。中文故障診斷與退化控制均符合預期，F3-c 失敗點為第二次 source_location 斷言。詳細命令／結果見 TEST_REPORT 最新節與證據 JSON。
- 六份副本來自最新非機密工作區，含公開 .env.example、必要未追蹤及中繼檔；原始來源與基準逐檔核對，沒有實際 .env/Git/venv/快取或兄弟站。APP_NAME、缺站 skip／明確跨站失敗、他處絕對路徑均正確。
- 最終稽核：branch/HEAD/index/status 保留，共用副本與快照一致；追蹤／非機密未追蹤空白及 LF/CRLF 正負控制通過；STARTUP 42 筆校驗唯讀處理 CRLF 後全相符，原清單未改。
- 證據 C:/Project/tmp/ig-accept-f1d-20261023-01，含基準、版本、實際命令／JUnit／日誌、控制、final-audit 與校驗碼。遠端 CI/Linux/全新安裝/有權限 symlink 真負例/真公司服務未驗證。
- 邊界：公司密鑰留雲端；未啟服務/Tunnel、不實作 CRUD/Storage、不部署/migration/seed/改正式資料/Commit/Merge/Push，不改 Git 全域設定。


## 2026-10-23 Claude：最新版獨立驗收（未發現新問題）

- 範圍：實際重跑三站完整檢查、F1-c／F1-d（分類、真實 Windows、長路徑）、H1–H4 對最新十例與 F1-d 前四例、R1／R2、F1、F2（含 59 種刺激的專案層級 contract_drift）、F2-b、F3／F3-b／F3-c、T1 九種突變（新版三站與 T1 前舊測試），以及六份最新工作區隔離副本。歷史版本與兩種舊測試的 SHA256 全部吻合，並分開使用。
- 結果：全套 pytest 前台 342 passed, 54 skipped、ADMIN 443 passed, 9 skipped、API 438 passed, 14 skipped；六份副本 前台 341 passed, 55 skipped、ADMIN 442 passed, 10 skipped、API 437 passed, 15 skipped（改名副本相同）；checker、Ruff、djLint、`--project-root ..` 全部 exit 0。H1–H4 最新版 12／12 抓到，F1-d 前只抓到 H1；T1 新版三站各 9／9，T1 前舊測試 M1–M3 存活、其餘 6 種被抓到。
- 發現：本輪範圍內沒有新的專案問題，因此沒有修改程式、測試、PROJECT_CHECKS 或契約快照；只追加三站 docs/TEST_REPORT.md 與本檔。
- 未驗證：GitHub 遠端 CI、Linux runner、全新 pip 安裝、有權限時 checker 拒絕真實 symlink 的負例、真登入／DB／Storage／Vercel。
- 邊界：未讀取實際 .env 或公司密鑰、未執行 vercel env pull、未連正式服務；不實作 CRUD／Storage；未啟動服務或 Tunnel；沒有部署、migration／seed、正式資料修改、Commit／Merge／Push／reset，也沒有修改 Git 全域設定。突變與新舊對照只在專案外副本。證據在 C:\Project\tmp\ig-claude-r8-20261023。

## 2026-10-23 Codex：F2 專案層 118 案例獨立驗收

- 範圍：以獨立驅動器在 ADMIN/API 非機密來源副本各實跑 59 種刺激，呼叫完整 check_project；不僅比較摘要，也不沿用 Claude 結果。
- 結果：每站 44/44 改寫案例恰好產生 contract_drift，15/15 無關案例零問題，總共 118/118 符合預期，沒有新問題；不需要改 checker、測試或快照。
- 還原：每案只允許指定來源檔變更，finally 還原原始 bytes，再驗證完整副本檔案集合／SHA256 及完整 checker 零問題；各 59/59 與最終副本全部還原。兩站副本 CLI exit 0 後再核對內容不變。
- 修改：只同步追加三站 docs/TEST_REPORT.md 與本檔，共 6 檔；程式、測試、PROJECT_CHECKS、快照、AGENTS、CI、依賴、業務與 STARTUP 均未改。branch/HEAD/index/status 保留，追蹤及非機密未追蹤檔空白檢查通過。
- 寫入後重跑三站 checker／完整跨站檢查，均 exit 0。證據 C:/Project/tmp/ig-f2-project-20261023-01，包含逐案結果、完整原始樹雜湊、CLI、final-audit 與校驗碼。
- 本輪未重跑其他完整測試／矩陣，沒有把歷史結果當本輪結果。遠端 CI/Linux/全新安裝/有權限 symlink 真負例/公司真服務仍未驗證。公司密鑰留雲端，不實作 CRUD/Storage、不啟服務/Tunnel、不部署/migration/seed/改正式資料/Commit/Merge/Push。


## 2026-10-23 Claude：ADMIN／API 各 59 個 F2 完整專案層案例獨立驗收（未發現新問題）

- 範圍：只重新驗證 ADMIN／API 的 118 個 F2 專案層案例與必要複驗。刺激以 AST／literal_eval 讀取（不執行來源腳本），SHA256 與前輪一致，每站 44 改寫＋15 無關。
- 方法：每站一份最新工作區專案外副本，使用副本自己的 checker，以完整 `check_project(copy_root)` 判定；每案前後核對整份檔案集合與 SHA256，在 finally 還原並再次確認零問題；最後再以副本 CLI 驗證 exit 0。
- 結果：InvoiceGuard-AI-ADMIN 改寫 44/44（只有 contract_drift 44/44）、無關零問題 15/15、還原 59/59、非預期 0、CLI exit 0；InvoiceGuard-AI-API 改寫 44/44（只有 contract_drift 44/44）、無關零問題 15/15、還原 59/59、非預期 0、CLI exit 0。
- 發現：沒有新的專案問題；未修改程式、測試、PROJECT_CHECKS 或契約快照，只追加三站兩份紀錄。
- 未執行：全套 pytest、Ruff、djLint、H1–H4、T1、F3、六份副本（程式未改）；遠端 CI、Linux、全新安裝、有權限的 symlink 真負例、真實雲端服務。
- 邊界：未讀取實際 .env 或公司密鑰、未執行 vercel env pull、未連正式服務；不實作 CRUD／Storage；未啟動服務或 Tunnel；沒有部署、migration／seed、正式資料修改、Commit／Merge／Push／reset，也沒有修改 Git 全域設定。證據在 C:\Project\tmp\ig-claude-f2p-20261023。

## 2026-10-23 Claude：三站 AGENTS.md 共同規則「本機入口」對齊 START 直接開 /login（使用者指示）

- 問題：共同規則區塊仍寫「只修改啟動器 PROJECT_ROOT」「手機 HTTPS 模式 START.cmd --mobile，與日常模式擇一」「手機須使用臨時 HTTPS URL 與存取碼」，與現行 START（SETUP 記錄根目錄、預設電腦／手機共用 HTTPS /login、不需 --mobile 或開發存取碼）衝突，可能讓 AI 依舊描述恢復 Basic／存取碼流程。
- 修正：只改共同區塊的「本機入口」段落：SETUP.cmd 初次設定（START.cmd setup 為相容指令）、START.cmd 日常啟動並自動開啟當次 HTTPS /login、原有 Email／密碼表單、不需開發存取碼且無額外瀏覽器帳密視窗、網站登入／部門權限／API 驗證照舊、三個本機別名僅供開發電腦。區塊外內容逐位元組未變；三站區塊逐字相同（區塊 SHA256 前 12 碼 0c8bdd68f0c5）。
- 核定版本：check_project 以 contracts/project-contract.json 的 agent_rules_sha256 鎖定共同規則；經使用者同意後，只把該欄位由 ba7fa5fe…改為 fe415bc3df35b6be8f1a849564c620624f8e89d41d6e0c7358bf89d9e82a74c5，契約其他內容未變，三站契約檔仍相同。
- 驗證：三站 check_project 單站與 --project-root 跨站皆 PASS（修改契約前三站皆因 agent_rules_drift FAIL，證明檢查仍有效）；test_project_governance：前台 126 passed／54 skipped、ADMIN 171 passed／9 skipped、API 166 passed／14 skipped（skip 為既有前置條件，不算通過），合成規則漂移測試仍通過。程式、樣板、業務測試未改，未重跑業務 pytest。
- 邊界：未讀 .env、未部署、未 migration、未修改正式資料、未 Commit／Stage；branch／HEAD／index 不變。

## 2026-10-23：Codex 獨立驗收 Claude 最新規範與原有 /login 啟動流程

- 結論：本輪重新執行檢查及真實啟動，沒有發現需修改的專案問題。未修改程式、測試、AGENTS、契約或發行套件；只在三站及 STARTUP 的 TEST_REPORT／REVIEW_FIX_LOG 追加本節，更新 STARTUP 完整性清單。
- 三站規範：逐站獨立擷取共同區塊，以 checker 的 strip／UTF-8 方法計算 SHA256，三站與三份 agent_rules_sha256 均為 fe415bc3df35b6be8f1a849564c620624f8e89d41d6e0c7358bf89d9e82a74c5。三份契約逐位元組一致，AGENTS 為 LF、無 BOM／行尾空白。以保存的前輪基準重建舊共同區塊後逐站比對完整檔案雜湊，證明只改本機入口段落；契約只有核定雜湊欄位變動。
- 漂移反例：三站各建立專案外非機密副本，原版零 issue；只加入一行合成共同規則，均恰好回報 agent_rules_drift，CLI exit 1；還原後零 issue，列入副本的檔案雜湊完全還原。沒有修改實際工作區或核定快照以取得通過。
- 實際離線結果：前台完整 pytest 343 passed／54 skipped（包含前台治理測試）；ADMIN 治理 171 passed／9 skipped；API 治理 166 passed／14 skipped；STARTUP 完整 276 passed／1 skipped、155 subtests。skip 為原有站別／環境前置條件及 symlink 權限，不算通過。三站 check_project 單站及跨站共六次 exit 0。前台 Ruff check／format 37 檔、STARTUP 19 檔通過；前台 djLint 14 模板 0 錯誤。保留既有 Starlette/httpx 棄用警告。
- 封裝：從目前維護來源獨立 build 兩次，兩檔與 ZIP 都逐位元組相同，等於根 SETUP／START 及 dist；ZIP 只有兩檔。原 auth.py、login.html、app.main、deps.py、security.py 雜湊與先前保存的原有版本相符，沒有更換網站登入或授權實作。
- 真實入口：直接使用 C:\InvoiceGuard_project\InvoiceGuard-STARTUP\SETUP.cmd／START.cmd，隔離 LOCALAPPDATA、TEMP／TMP，以 SETUP --reuse --skip-tools 沿用 venv，不跑 pip、不修改使用者實際設定。START 使用隔離測試埠與 --run-seconds 90，不加 --mobile／--no-browser；ADMIN 約 7.4 秒、前端約 79.7 秒各一次成功請求系統瀏覽器開啟，終端先顯示 /login，再開相同網址；等待期間持續顯示進度，沒有輸出內部帳號／存取碼。
- HTTP：同一次真 HTTPS 的首頁、/login、CSS、JS、favicon 各重複 3 次為 200，沒有 WWW-Authenticate；原 form action、Email／密碼欄位正確，沒有開發導覽或額外 CSS。未登入 /invoices 回 303 至網站 /login，診斷路徑回 403 且不發送帳密挑戰；三個別名正確，前端別名 /login 轉到同一次 HTTPS /login。
- 瀏覽器目視：內建瀏覽器實際開啟同一個公開 /login，AX 與截圖確認標題「登入 | InvoiceGuard AI」、原有登入表單，沒有額外帳密視窗或開發導覽；重新整理及 390×844 手機尺寸、1280×800 桌面尺寸皆成立。瀏覽 /invoices 實際導回 /login?next=%2Finvoices。未輸入任何帳號密碼、未提交登入；已還原 viewport 並關閉本次內建瀏覽器分頁。系統預設瀏覽器的開啟由真實 webbrowser 呼叫驗證，目視則在內建瀏覽器完成，未冒稱已檢視系統瀏覽器或手機實機。
- 清理：上述限時正常結束、另兩次真 HTTPS 的 Ctrl+C／WM_CLOSE 都實際經由根 START 執行。每次先確認所有觀察到的本次程序結束、Job 歸零及 IPv4／IPv6 listener 復原，再關閉外層 safety Job；未靠兜底清理取得通過。控制事件由程式送出，並非人工按鍵／點 X。本輪一般預設三站沒有既有 health=ok 服務，因此不宣稱驗證了持續運作中的三站 health；有比對埠與程序清理，沒有停止任何 Job 外程序。
- 生命週期嘗試：WM_CLOSE 首輪在就緒前達驗收工具的 180 秒上限，未送出關閉事件，不算通過；當次未保存階段資訊，無法確認原因，不推測為產品或網路問題。已保存失敗摘要，第二次在外部控制器加上固定階段觀察，保留相同產品程式、180 秒上限及全部清理斷言重跑；最終 WM_CLOSE 結果以上述重跑證據為準，沒有放寬驗收或把首輪失敗刪掉。
- 稽核：三站 branch／HEAD／完整 status／index 與本輪基準一致，逐檔雜湊證明執行期間沒有其他修改；git diff --check 與未追蹤文字檔行尾空白檢查通過。報告追加後再次核對，只有本節報告與 STARTUP/SHA256SUMS.txt 改動；三站規範／契約及全部業務程式保持原樣。兩份 MOBILE_DEVELOPMENT.md 仍逐位元組一致，根目錄分類保留。
- 執行環境紀錄：第一次 Ruff 未指定專案外 cache，沙盒因 STARTUP/artifacts 寫入權限回 exit 2，不算通過；改用 --no-cache 重跑 check／format 全部通過，未修改產品設定或放寬檢查。其他驗收皆使用專案外 TEMP／cache。
- 未驗證：手機實機／相機、真實帳號登入／部門資料／DB／Storage／模型／Vercel、新機安裝、人工 Ctrl+C／點 X、API／ADMIN 業務完整 pytest。本輪沒有發現問題，故未任意擴張修改或重複未受影響的業務測試。
- 邊界與證據：公司密鑰留雲端，未讀實際 .env、不部署、migration、正式資料寫入、CRUD／Storage、Commit／Stage／Merge／Push；未修改 Git 全域設定。證據在 C:\Project\tmp\ig-independent-login-y90kb09z，包括規範核對、獨立反例、JUnit、瀏覽器觀察、真實生命週期與稽核 JSON；不保存臨時碼、Authorization 或原始子程序輸出。截圖／AX 位於本次工具對話，未另外寫入證據目錄。

### 本輪操作設定修正：實際使用者的舊套件版本快取

完成隔離驗收後，另以實際使用者設定執行 START --check，發現 profile 的舊版本資訊造成 exit 1；這是實際日常入口的操作問題，已直接處理，並非程式或網站授權缺陷。先備份只有六個公開根目錄／版本欄位的 profile，再在根目錄執行 SETUP.cmd --reuse --skip-tools：exit 0，沿用原 venv、不跑 pip、不安裝工具；實際 profile 更新後的 START --check（使用已釋放的隔離埠）exit 0。只變動套件版本識別，project_root／package_dir 不變，沒有公司秘密或雲端設定。本輪因此另更新使用者 LOCALAPPDATA 中的公開版本設定及核定執行快取；上節「不修改使用者實際設定」僅描述先前的隔離驗收階段，不代表這項後續修正沒有發生。程式、規則、契約及發行檔仍保持原樣。前後設定與修正摘要存於證據目錄 actual-profile-*.json。

## 2026-10-23 Claude：最終獨立驗收（本站未修改）

- 未發現本站需修改的問題；共同規則雜湊、契約與跨站檢查一致，相關測試通過。只追加 TEST_REPORT／REVIEW_FIX_LOG 紀錄。

## 2026-10-25 Claude：自 ADMIN 複製 DB 與 Vercel（Storage）模組（不含 dev 功能）

- 原因：使用者要求把 ADMIN 已可用的 DB、Vercel 模組複製到 API。原 API 設定把本機 DATABASE_URL 視為公司機密並拒絕啟動，DB 能力檢查也要求 Vercel 雲端。
- 處理：
  - `app/core/config.py`：與 ADMIN 相同——`check_environment()`／`require_environment()` 允許本機合法 DATABASE_URL 並驗證格式；`check_configuration("database")` 不再要求 Vercel；`_database_issues()` 增加 required 與 libpq 不支援參數檢查；本機檢查不再把 DATABASE_URL 列為機密；新增 S3_ENDPOINT_URL、S3_REGION、S3_ACCESS_KEY_ID、S3_SECRET_ACCESS_KEY。
  - 新增 `app/db/repositories/db_connection_repository.py`、`app/services/db_connection_service.py`（ADMIN DB 模組的唯讀 SELECT 1，不含 ADMIN 的資料表盤點）；`app/integrations/supabase_storage.py` 與 ADMIN 位元組相同。`app/db/session.py` 說明文字與 ADMIN 一致。
  - `.env.example`、AGENTS.md（新增「API DB／Storage 核定更新」段，位於共同規範區塊之外）。
  - 未複製：ADMIN 的 /dev/accounts、/dev/files、dev service、remote_admin_client、db_inspection。未改 Schema／migration、未接正式 FileService。
- 測試：見 TEST_REPORT 同日小節。

## 2026-10-26 Claude：新增三站共用常數檔 app/core/constants.py

- 需求（使用者核定）：三站各一份同名、內容相同的全域常數檔，放平台內部與跨平台共用的公開網址／常數；正式網址固定，本機網址由開發者自行填寫；依目前環境自動取用。不覆蓋、也不與雲端環境變數同名。
- 新增 `app/core/constants.py`：`PRODUCTION`（前台 https://invoice-guard-ai.vercel.app、API https://invoice-guard-ai-api.vercel.app、ADMIN https://invoice-guard-ai-admin.vercel.app）、`LOCAL`（預設 START 的 8080 共用別名）與 `current()`（沿用 `settings.is_vercel`：Vercel 回傳正式、其餘回傳本機；回傳複本）。三站檔案逐位元組相同。
- 本站目前沒有程式引用；之後需要跨平台網址時直接 `from app.core.constants import current`。
- 新增 `tests/unit/test_constants.py`（三站相同）：正式網址值、兩區欄位一致、Vercel／本機判斷、回傳複本不改檔案值。`tests/unit/test_environment.py` 的暫存套件複製清單加入 `constants.py`（真正 `-m app.core.environment` 子程序測試需要；ADMIN 未加入前 3 案例因匯入失敗）。
- 未加入 check_project 的跨站快照：開發者需可自行修改本機網址，快照會把修改視為契約漂移。
- 驗證：本站 `scripts/check_project.py`（含 `--project-root` 三站模式）PASS；`pytest -q` 481 passed、14 skipped；`ruff check app tests scripts`、`ruff format --check app tests scripts` 通過；`python -m app.core.environment --check` exit 0。未改雲端環境變數、environment.py、STARTUP、DB／登入程式；未部署、migration、Commit、Merge 或 Push。

## 2026-10-26 Claude：網站名稱、圖示與禁止搜尋引擎收錄集中到 app/core/constants.py

- 需求（使用者核定）：三站可互相連結，但不能出現在 Google 等搜尋結果；網站名稱、圖示與避免搜尋引擎的設定放在平台共用檔案。
- `app/core/constants.py`（三站相同）新增 `SITE_NAMES`、`SITE_ICON`（icons/favicon.svg）、`ROBOTS_POLICY`（noindex, nofollow）、`ROBOTS_TXT`。
- robots.txt 刻意不封鎖抓取（Allow）：搜尋引擎須讀得到頁面的 noindex 才會排除；以 Disallow 封鎖時讀不到 noindex，被其他網站連結時仍可能列出網址。
- 本站：新增 `app/routers/robots.py`（與兩站相同）並在 `app/main.py` 掛載；`vercel.json` 新增全站 X-Robots-Tag。本站只回 JSON，沒有網頁與圖示。
- 新增／更新 `tests/unit/test_constants.py`（三站相同）：共用值、vercel.json 的 X-Robots-Tag 等於 ROBOTS_POLICY、/robots.txt 內容、網頁 /login 帶 noindex、共用圖示與站名（API 確認沒有網頁）。
- 驗證：`check_project.py`（單站與 `--project-root` 三站）PASS；`pytest -q` 485 passed、14 skipped；Ruff check／format 通過；`python -m app.core.environment --check` exit 0。
- vercel.json 的標頭需部署後才生效；本輪未部署、未改雲端環境變數、未 Commit／Merge／Push。

## 2026-10-26 Codex：網站名稱、圖示與 noindex 獨立驗收及測試補強

- 本輪直接閱讀三站現行規範、常數、路由、模板、Vercel 設定及測試，重新實跑檢查；沒有沿用前次通過結果。未發現本次網站程式的功能錯誤，未修改 constants.py、robots.py、模板、main.py、vercel.json 或契約快照。
- 發現兩項測試精度缺口：原站名斷言只要求名稱屬於任一平台，誤用 API 站名仍通過；原 robots 測試只排除 Disallow 並比較同一常數，將 ROBOTS_TXT 清空仍通過。只補強三站同一份 tests/unit/test_constants.py：依 Settings 的 APP_NAME 預設值辨識平台並核對該站名稱、精確核對核定 robots 內容、驗證 text/plain；API 分支明確要求沒有 templates/static。未新增業務限制或 middleware。
- 反例證據：專案外公開來源副本中，舊斷言漏掉前台／ADMIN 各兩個反例、API 一個空白 robots 反例。最新版正向控制三站通過，錯誤 meta、Vercel 標頭、robots 路由／空白內容及站名共 13 個負例均在對應 assertion 失敗，沒有收集／fixture error；副本逐檔 SHA256 完整還原。另行刪除 UI 目錄的副本會在建立 app 時失敗，未將該情境算入上述 13 個斷言證據。
- 本次實測：前台完整 pytest 350 passed／54 skipped；ADMIN 636 passed／9 skipped；API 485 passed／14 skipped。skip 為原有站別不適用及一個 symlink 權限不足，不算通過，數量與本次修改前基準相同。三站 check_project 單站及跨站、Ruff check／format、environment --check 全部 exit 0；環境檢查沒有連線、輸出未含設定值。新增比較斷言初次觸發 SIM300，調換比較左右順序後複驗通過；未將初次 lint 失敗列為通過。
- 模板：前台自身 djLint 因 Windows 應用程式控制阻擋 T001 DLL 而 exit 2，不算通過；未變更安全設定，改以 ADMIN 現有同版本 djLint 1.46.6 檢查前台 14 個模板零錯誤，ADMIN 自身 16 個模板零錯誤。完整 HTML 文件均繼承 base.html，沒有其他自帶 head 的頁面遺漏；API 無 templates/static。保留既有 Starlette/httpx 棄用警告。
- 官方文件：Google 說明 noindex 需能被爬取讀到，被 robots.txt Disallow 阻擋時無法讀取 noindex；因此 Allow 加 HTML meta／Vercel X-Robots-Tag 的搭配正確。三份 vercel.json 通過本次下載的官方 JSON schema 驗證；functions／crons、原有 UI 安全標頭及靜態快取規則與 HEAD 比對不變。官方來源：https://developers.google.com/search/docs/crawling-indexing/block-indexing 、https://vercel.com/docs/project-configuration/vercel-json#headers 、https://openapi.vercel.sh/vercel.json 。尚未部署，未驗證線上 edge 標頭或搜尋結果的實際移除／重新爬取。
- 一致性與邊界：三站 constants.py、robots.py 及 test_constants.py 分別逐位元組一致（UTF-8、LF、無 BOM）；branch／HEAD／index／完整 status 與本輪基準相同。只修改三站測試與本紀錄，未修改 STARTUP。TestClient 在沙盒內的未完成嘗試另存 partial，清理後以同一測試在核定權限下完成；不把等待異常宣稱為已查明的產品缺陷。未讀實際 .env／Token／DB URL／Storage Key，未呼叫公司 DB／Storage／模型、未安裝套件、未部署、migration、正式資料寫入或 Commit／Merge／Push。證據：C:\Project\tmp\igs-1144。

## 2026-10-26 Claude：三站說明文件稽核（任何 AI 都能了解三站架構並自行開發）

- 問題：文件仍寫「本機直接建立 DB Engine 會被阻擋」「開發者不持有 DB 密鑰」「本階段／本輪不…」等過期或一次性限制，與 2026-10-25 核定的 START 注入 Production DATABASE_URL／S3_* 不符；缺少三站架構總覽；APP_ENV 不一致寫成 401／500（實際拒絕啟動）；REMOTE_* 寫成待接線（實際沒有消費端）；目錄樹缺 environment.py、integrations、開發路由等。
- 原因：多輪任務只更新當輪文件，共同區塊與站內文件沒有一起對齊程式。
- 處理（三站共同）：AGENTS.md 共同區塊新增「三站架構」（角色、正式網址、`app/core/constants.py`、noindex、三站相同檔清單），改寫 CRUD 未接線、機密與本機例外、migration 授權、前台目錄、API 無樣板等規則；三站 `contracts/project-contract.json` 的 `agent_rules_sha256` 由 fe415bc3… 更新為 d0759774…（共同規則變更，需維護者審查）。ENVIRONMENT_ISOLATION、PROJECT_CHECKS、CLAUDE_REVIEW_PROMPT（標為歷史）、GIT_WORKFLOW 三站逐位元組相同；README、DEVELOPMENT_STATUS、ARCHITECTURE、CODING_CONVENTIONS 逐站對齊；`tests/unit/test_environment.py` 一行註解改為「config.py 可能引用 constants.py（目前 ADMIN 有）」。
- 處理（本站）：AGENTS「API 現況」；MODULE_CONTRACT（SELECT 1 實測、APP_ENV、REMOTE_API_BASE_URL 無消費端、S3_* 列、Engine 不限執行位置、Alembic 執行需授權、待完成清單）；`app/db/README.md`（Engine 不限位置；Alembic 未設 UNPOOLED 時沿用 DATABASE_URL，本機帶 START 注入值執行即作用於正式 DB；v1.3 身分表本站尚無 Model／migration；建立 migration 檔屬一般開發）；ARCHITECTURE（目錄樹、Storage 現況、Cron 本機無法以標頭呼叫、環境變數表）；CODING_CONVENTIONS 提交清單補 ADMIN Model 與契約快照。
- 驗證：`check_project.py` 單站與 `--project-root` 皆 PASS（0 issues）；pytest 485 passed、14 skipped、1 warning；`ruff check`／`ruff format --check app tests scripts` 通過；`python -m app.core.environment --check` issues 為空；API 沒有樣板，不跑 djlint。
- 一致性：三站 environment.py、constants.py、robots.py、test_constants.py、check_project.py 與上述共同文件逐位元組一致；ADMIN／API supabase_storage.py 相同；branch／HEAD／index 與稽核開始前基準相同。
- 未處理（回報使用者決定）：程式內過期註解未改（ADMIN deps.py:89「本機沒有 DATABASE_URL」、ADMIN／API storage_client.py:4「本階段沒有 Supabase 實作」、API migrations/env.py:9「本機阻擋」、API routers/v1/auth.py:3「前台與後台共用」、API scripts/run_job.py:9「本階段不執行」）；conftest 不清除 S3_*；AGENTS.md／CLAUDE.md 未納入 Git；GIT_WORKFLOW 的 develop 分支與目前 feature/python-web 待確認。
- 邊界：只改文件、契約雜湊與一行測試註解；未讀實際 .env／Token／DB URL／Storage Key，未連公司 DB／Storage／模型，未部署、migration、正式資料寫入或 Commit／Merge／Push。

## 2026-10-26 Claude：文件依使用者確認的三站架構修正（/dev 示範與模組）

- 問題：文件把 Vercel 模組 `app/integrations/supabase_storage.py` 寫成「只供開發頁使用」「低階 S3 用戶端」，把 `/dev` 稱為「開發頁」，共同規則又要求「依契約接線」，讓人誤以為開發時要另用一套模組；三站架構也沒寫明只有 ADMIN／API 能串聯雲端。
- 依據（使用者確認）：能串聯雲端 DB／Storage 的只有 ADMIN、API；ADMIN 直接串聯、不經 API，前台經 API 串聯；`/dev` 是示範檔案，不是串聯路徑；示範用的就是開發者使用的 DB 模組（`app/db`）與 Vercel 模組（`app/integrations/supabase_storage.py`）；API 也可有 `/dev` 示範，但本機開發與前台不串接。
- 處理：三站 AGENTS 共同區塊「三站架構」寫入上述各點，共同規則改為「第一階段契約 DataService／FileService／get_storage_client() 尚未接線」（`agent_rules_sha256` 更新為 a617e5f6…）；ADMIN／API AGENTS 現況、DEVELOPMENT_STATUS、MODULE_CONTRACT、ARCHITECTURE、ENVIRONMENT_ISOLATION（三站相同）、ADMIN DB_READONLY_PROBE 用語一致；前台 `pages/dev/` 改稱手機診斷頁，避免與 `/dev` 示範檔案混淆。
- 驗證：`check_project.py` 單站與 `--project-root` PASS；pytest 前台 350 passed／54 skipped、ADMIN 636 passed／9 skipped、API 485 passed／14 skipped（各 1 warning）；ruff check／format --check、`app.core.environment --check`、djlint（前台 14、ADMIN 16 個模板）通過。
- 未改：程式碼（含 `supabase_storage.py` 第 5 行註解「只供本機開發檔案頁使用」）與歷史文件。

## 2026-10-26 Claude：程式註解改為「示範與正式功能共用同一個 Vercel 模組」

- 問題：程式註解把 Vercel 模組 `app/integrations/supabase_storage.py` 寫成「只供本機開發檔案頁使用」，把未接線的 `storage_client` 寫成正式檔案流程，`/dev/files` 寫成「非正式範例」，形成「示範一套、正式一套」的錯誤說法。
- 處理（只改註解與文件，不改程式行為）：`supabase_storage.py`（ADMIN／API 相同，加使用方式與 `from_settings` 的 Raises）、`storage_client.py`（ADMIN／API 相同，註明為未接線的第一階段契約）、`file_utils.py`（三站相同，留存檔案改指 Vercel 模組，前台交給 API）、ADMIN `routers/dev_files.py`、`services/dev_file_service.py`、API `services/invoice_service.py`；ADMIN／API `docs/MODULE_CONTRACT.md`「匯入方式」補上 `from app.integrations.supabase_storage import S3StorageClient`。
- 驗證：三站 check_project（單站與 `--project-root`）PASS；pytest 前台 350／ADMIN 636／API 485 passed；ruff check／format --check、`app.core.environment --check`、djlint 通過；相同檔逐位元組一致。


## 2026-10-26 Codex：三站說明文件與程式註解獨立驗收（文字修正）

- 本輪範圍只有現行說明、程式註解與契約雜湊；直接閱讀程式並重新執行檢查，不沿用歷史通過結果。歷史 TEST_REPORT、REVIEW_FIX_LOG 舊條目、CLAUDE 檢驗文件及討論稿保留原語境，不據此要求新功能。
- A：三站 AGENTS 共同區塊逐字相同，strip 後 SHA256 與三份 agent_rules_sha256 均為 a617e5f6713d622dc03d3ef86a3c817a0dd3877b9d35219f704aa72f5546a6f7。符合 ADMIN／API 自有 DB 與 Vercel 模組、ADMIN 不經 API、前台不直接連 DB／Storage、/dev 為同一模組示範等核定架構。沒有修改共同區塊或契約快照。
- B：修正 MODULE_CONTRACT／ARCHITECTURE 中把 SUPABASE_URL／SUPABASE_SECRET_KEY 標成實際 S3 用戶端必填的混淆；兩者是第一階段靜態設定檢查的欄位，S3StorageClient 不讀取它們。Bucket 由兩者共同使用，靜態 storage 檢查也會驗證 Bucket，不只是 URL 與 Secret。設定檢查已實作，不能把此說明解讀成另一套 Storage 模組或未接線的 vercel.py。
- C：ADMIN／API supabase_storage.from_settings 的 Raises 補足 hostname、非空 userinfo／query、空白必要值及 urlsplit 的 ValueError；範例 put 方法與參數符合實際簽章。FileService 工廠說明改為未整合的第一階段契約，不再暗示現有 S3 模組不存在。其餘本站修正檔案如下。
- D：前台與 STARTUP 的 MOBILE_DEVELOPMENT.md 位元組一致；STARTUP SHA256SUMS 81 筆全部相符，CRLF、兩空格、原 UTF-8 位元組排序、無 BOM；未修改 STARTUP 或其清單。file_utils 三站相同，storage_client／supabase_storage／file_service 各在 ADMIN／API 相同。
- E：本次完整 pytest：前台 350 passed／54 skipped、ADMIN 636 passed／9 skipped、API 485 passed／14 skipped；另重點測試為 7／42／14 passed。Skip 是既有站別差異及每站一個 symlink 權限不足，不算通過；數量與開始前文件基準一致。三站 check_project 單站與 --project-root ..、Ruff check／format --check、environment --check 全部 exit 0；環境 CLI 無設定值，connectivity_checked=false。本次前台與 ADMIN 各用自己的 djLint，14／16 個模板零錯誤，未遇 DLL 阻擋、不需 fallback。ADMIN venv 執行 STARTUP unittest tests.test_project_layout：4 tests、OK。最後一批註解修改後，ADMIN／API 全套再次完成同樣數字與檢查。每站唯一 warning 為既有 Starlette/httpx 棄用警告。
- 合成驗證：從現行來源 AST 載入 S3 程式，但以合成 Settings 取代業務設定，不匯入實際 config；每站 14 個建構／解析案例符合實作，put 範例參數可綁定；另用原 Settings 方法驗證 27 組 dev_pages_enabled 條件。不發網路、不建立 DB Engine、不執行 migration。這些不是雲端連線驗證。
- F：三站 branch、HEAD、index SHA256 與 index entries 保留開始前狀態；status 新增的未暫存修改只涉及本輪核定的文字修正，沒有其他新增或移除的狀態。全體 app／tests／scripts 的 AST（去除 docstring）與基準一致；程式只改 docstring／註解，測試程式、執行流程與契約檔未變。只寫入下列文字與本節追加紀錄，不覆蓋他人修改。最初沙盒不允許唯讀 Git -C 操作，後在核定權限下建立基準；當次失敗未列為產品問題或通過。
- 未驗證：實際公司 DB／Storage／模型、Vercel 線上部署、真實登入、手機／Tunnel 與生命週期；它們不在本輪範圍。未讀 .env／VERCEL_TOKEN.txt／任何實際機密，未安裝套件、改安全設定、部署、migration、正式資料寫入或 Git Commit／Merge／Push／Reset。沒有啟動網站、Tunnel 或可見視窗。
- 證據：C:\Project\tmp\igdoc-1338，包含實際指令／exit code、JUnit、Skip 原因、合成探測、文字差異與 Git／AST 稽核。

本站問題與修正：

- invoice_service 與 auth router 都仍是 TODO 骨架，改明示尚未實作及預計相依；ADMIN 使用自己的登入，不經此 API。
- Alembic env 的註解刪除已不存在的『app.db.session 本機阻擋』；應用 Engine 在 session.py，既有 migration Engine 則由 Alembic 自己建立，屬同一 DB 管理範圍，未另建業務模組、更未執行 SQL。
- 本站修改檔案：`app/integrations/supabase_storage.py`、`docs/MODULE_CONTRACT.md`、`docs/ARCHITECTURE.md`、`app/services/invoice_service.py`、`app/services/file_service.py`、`app/routers/v1/auth.py`、`app/db/migrations/env.py`；另追加本紀錄。


### 本輪最終稽核補充：驗收期間的並行修改與 ADMIN 重跑

- 原先文字修正與首輪稽核完成後，13:48–13:49 偵測 ADMIN 另有行為修改：app/routers/dev_accounts.py、app/routers/dev_files.py、tests/unit/test_dev_accounts.py、tests/unit/test_dev_files.py。其中 dev_files.py 與本輪路由條件註解位於同檔；本輪修正句仍被保留。這些表單原地回應及測試變更不是本輪文件檢驗所寫入，未覆蓋、回復或修改它們。
- 因此上節「AST 與開始前相同」只描述當時的文字修正檢查點，不能代表加入並行修改後的整份工作區。範圍外的行為變更未列為本輪文件修正，也未以舊測試結果冒充新版本通過。
- 對並行修改後的固定版本重新實跑 ADMIN：638 passed／9 skipped／1 個既有 warning；單站與跨站 checker、Ruff check／format、environment --check、16 個模板 djLint 全部 exit 0。比原先 636 多出的 2 個案例來自並行修改。前台 350／54、API 485／14 仍為本輪各站實跑結果，兩站執行來源未受並行修改。
- ADMIN 重跑開始／結束的來源與 Git 快照完全相同，沒有再發生驗收中的來源異動；三站 branch、HEAD、index SHA256／entries 仍與最初基準相同。實際例外與雜湊記錄在 concurrent-changes.json、concurrent-retest-before.json／after.json、concurrent-admin-results.json。

- 最終版本註記：13:57 他方再次更新 tests/unit/test_dev_accounts.py 後，本輪又以新快照重新執行 ADMIN 全部指定檢查；仍為 638 passed／9 skipped，checker、Ruff、environment、djLint 全 exit 0，latest-retest-before／after 完全一致。另有他方同步的 DEVELOPMENT_STATUS.md 與 main.js 變更，均保留；以 latest-admin-results.json 與 latest-retest-after.json 作為最後實測版本證據，不把之前的檢查點當成同一版本。

- F 項最終例外：最後觀察三站 branch、HEAD 與 index entries 仍與開始前完全相同；但 ADMIN 的 .git/index SHA256 由 a2a8f8d6099e98b03223d88d090e604f374106dae9b4889b2044e7ee8736c852 變成 e883bcba66cc32051c429240bb08ebb78dc142999d939f1a44f806b227257b72。這代表暫存內容沒變、索引位元組卻有變化，發生來源未確認；不能把上方早先檢查點的「index SHA 相同」當成最後狀態。本輪沒有執行 Git 寫入，也不覆寫／還原索引；F 不宣稱位元組完全不變。詳見 git-final-observation.json。
