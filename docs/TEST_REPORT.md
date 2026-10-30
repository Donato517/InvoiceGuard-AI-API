# AI 協作規範測試報告

## 2026-10-23 範圍

本輪建立三站 AI 規範入口、文件對齊、標準函式庫契約／分層檢查與無密鑰測試。保留既有未提交變更；未實作 CRUD／Storage、未啟動服務／Tunnel、未部署／migration／操作正式資料、未 Commit／Merge／Push。

## 驗證方法

各站自己的 Python 3.12 venv；PYTHONDONTWRITEBYTECODE=1，pytest -p no:cacheprovider，TEMP/TMP及basetemp留在專案外。三站各自跑 scripts/check_project.py、pytest、Ruff lint/format；UI 另跑 djLint。跨站模式以 --project-root 比對完整三站；單站測試用不含 .env／venv／Git／兄弟站的來源副本，並阻擋 app import。

測試包含正／反例與實際副本突變，不用公司密鑰，不連真 DB／Storage／模型；既有測試阻擋器保留。具體執行結果在本節後追加；沒有執行的項目不能算通過。

## 未驗收與限制

本輪沒有 Push，GitHub Windows／Linux 工作流程未實際啟動，也未測全新 pip 安裝。靜態分析不能替代完整型別分析、秘密掃描、真授權或防惡意沙箱；單站 CI 只能比對核定快照，不能看到其他未 checkout 分支。應用／機密／真 DB／Supabase／Vercel 正式行為未由本輪驗證。

既有 Starlette/httpx 淘汰警告需另列；針對其他站專屬角色的案例可能合理 skip，不能算通過。後續發現與修正記在 [REVIEW_FIX_LOG.md](REVIEW_FIX_LOG.md)，檢驗指令見 [CLAUDE_REVIEW_PROMPT.md](CLAUDE_REVIEW_PROMPT.md)。

## 2026-10-23 實際 checkout 最終驗證

| Repository | 全套 pytest 實測 |
|---|---|
| InvoiceGuard-AI | 277 passed, 18 skipped, 1 warning in 7.68s |
| InvoiceGuard-AI-ADMIN | 344 passed, 7 skipped, 1 warning in 10.76s |
| InvoiceGuard-AI-API | 340 passed, 11 skipped, 1 warning in 8.24s |

三站規範檢查、Ruff check／format、UI 兩站各 14 份模板 djLint 全部 exit 0。三站跨站比對與從其他工作目錄用 -I 啟動檢查器亦 exit 0。使用各站原有 Python 3.12 venv，子程序只接收 OS 環境白名單；未下載公司變數或安裝新套件。

新增規範測試共 79 案例／站：前台 61 passed／18 skipped、ADMIN 72 passed／7 skipped、API 68 passed／11 skipped。skip 只涵蓋本站沒有的後端、手機或靜態資源層；不算通過。每站只有既有 Starlette/httpx 淘汰警告。新增測試驗證相對／別名／巢狀 import、設定來源、精確組裝例外、合法 set.add、DB Session 操作拒絕、Repository commit／rollback、AST 相依閉包、Vercel metadata、Model 集合／註冊、單站無 app import、快照與跨站漂移。

外部副本突變測試：分層控制組 17 passed，停用相依拒絕後 17 failed；契約控制組 5 passed，停用檔案群組摘要比對後 2 failed／3 passed，實際上傳大小與 ORM 約束退化會被抓到。共同型別與 Vercel 子集仍由其他獨立檢查保護。真正來源檢查器雜湊為 `979817e4ddb75d2d97460c33c0227fbf854bcc470105e79ddfd31e0972250bfe`，突變僅在專案外副本，不在實際專案改壞後還原。

原始命令、exit、輸出與突變 patch 留在 `C:/Project/tmp/invoiceguard-ai-governance-20261023/validation-results.json`、`governance-unit-review.json` 與 `mutations/result.json`；完整範圍／Git／雜湊核對見同目錄 `final-audit.json`、`evidence-manifest.json`。初版突變只改 docstring 的錯誤已另記，沒有視為完整通過。

本輪總計 51 個核定檔案（新增 32、修改 19），其中業務 Python、Schema、SQLAlchemy／安全設定、依賴版本、vercel.json、migration 與 STARTUP 全部未變。兩份前台手機模板只增加不輸出至瀏覽器的 Jinja 檔頭註解。三站 HEAD／branch／index 與既有未提交內容保留。新增 CI 尚未 Push，GitHub Linux／Windows runner 未實際執行，不能以本機 Windows 結果宣稱 Linux 通過；測試本身仍以固定 Repository 名稱組織其臨時副本，生產檢查器角色由 Settings.APP_NAME 靜態辨識。


## 2026-10-23 Claude 獨立檢驗：規範入口、契約快照與分層檢查器

依 docs/CLAUDE_REVIEW_PROMPT.md 檢驗三站最新未提交工作。開始前保存三站 branch／HEAD／index／status 與全部檔案雜湊；結束時 HEAD、branch、index 雜湊、暫存區（0）與 status 筆數（前台 37、ADMIN 29、API 32）均與基準相同。

### 實際重跑（各站自己的 Python 3.12 venv、-B、-p no:cacheprovider、basetemp 在專案外）

| Repository | 修正前全套 pytest | 修正後全套 pytest | 修正後規範測試 |
|---|---|---|---|
| InvoiceGuard-AI | 277 passed, 18 skipped | **299 passed, 33 skipped** | 83 passed, 33 skipped |
| InvoiceGuard-AI-ADMIN | 344 passed, 7 skipped | **380 passed, 8 skipped** | 108 passed, 8 skipped |
| InvoiceGuard-AI-API | 340 passed, 11 skipped | **375 passed, 13 skipped** | 103 passed, 13 skipped |

- 三站 `scripts/check_project.py`、`--project-root ..`、從 C:\ 以 `-I` 與絕對路徑執行，均 PASS（0 issues）；Ruff check／format（app tests scripts）通過；前台與 ADMIN 各 14 份模板 djLint 0 errors。新增 skip 只是本站沒有的後端／前端專屬案例，不算通過；每站仍只有既有 Starlette/httpx 淘汰警告。
- 單站副本（只複製 Git 追蹤及未忽略的未追蹤檔，沒有 .env／venv／兄弟站）：修正前三站 pytest 各 **1 failed**（跨站測試讀不到兄弟 Repo，GitHub 單站 CI 會因此失敗）；修正後三站全數通過。資料夾改名的 Clone：修正前前台 7 failed、API 2 failed；修正後全數通過。
- 繞過探測（合成程式碼）：修正前 21 個案例全部漏判；修正後後端 21／21、前台 13／13 偵測，合法案例（後端 6、前台 2）無誤報。專案外副本突變：修正後 API 29／29、ADMIN 29／29、前台 10／10 符合預期；只改 docstring 中相同文字的案例不誤報。
- 有效性：把新測試放進修正前的檢查器副本，API 27 failed、前台 16 failed，證明測試確實攔得住退化。

### 修正內容與快照

- 檢查器補上：經匯入別名的屬性存取、importlib／runpy／pkgutil 載入器、http.client／urllib3／asyncio 等網路模組、pydantic.v1 或經 config 轉匯入的 BaseSettings、`.env` 路徑字串、os.getenvb／nt.environ；Router 不可直接操作注入的 Session；Repository 不可 begin 或綁定 commit；Service 以 self 屬性保存的 Session 同樣受限；`app/core/deps.py` 例外改成精確名稱清單；app 內無原始碼的可匯入模組與 `__pycache__` 內原始碼一律拒絕；共用子集摘要納入之後改寫核定名稱的頂層敘述。
- 規範測試改以 Settings.APP_NAME 判斷本站角色；單站 checkout 缺兄弟 Repository 時，完整跨站比對測試明確 skip（缺站必須失敗的測試仍執行）。
- 契約快照 `contracts/project-contract.json`、AGENTS.md 共同規則區塊及其雜湊都**未修改**：新摘要演算法對現有 common.py／vercel.py 的結果與核定快照相同，沒有為了變綠而重建快照。
- 修改檔案（三站同步、逐位元組一致）：scripts/check_project.py、tests/unit/test_project_governance.py、docs/PROJECT_CHECKS.md、本檔與 REVIEW_FIX_LOG.md；另 API 的 .env.example 只改 Blob 說明註解。業務程式、Schema、ORM、依賴、vercel.json、CI 工作流程與 STARTUP 都沒有改。

### CI 與未驗收

- 工作流程只有 contents:read、checkout 設 persist-credentials: false、無公司 secrets、無 pull_request_target、無部署或 migration；Windows／Linux 都用 Python 3.12。線上核對 actions/checkout 與 actions/setup-python 的 v7 tag 存在（2026-10-23）。
- **未執行**：GitHub 遠端 CI（本輪不 Push）、Linux runner（本機只有 Windows）、全新 pip 安裝、真 DB／Supabase／Vercel／登入。靜態檢查仍不是沙箱：getattr／globals 等反射、字串組出的路徑與完整資料流不在範圍；config.py 的設定驗證邏輯因站別不同不在快照內，由各站測試覆蓋。
- 證據：C:\Project\tmp\invoiceguard-claude-governance-20261023（probe-after-fix.txt、mutations-after-fix.txt、manifest.json 與 scripts）。突變只在專案外副本進行，實際專案沒有留下改壞的殘檔。

## 2026-10-23 Codex 獨立覆核 Claude G1–G6 後的補強

本節為後續獨立實測，不覆寫前節 Claude 的歷史結果。確認 G1 單站缺兄弟時 skip、明確跨站缺站失敗，以及 G2 以 APP_NAME 辨識角色均有效。另發現並修正 F1–F3，詳 REVIEW_FIX_LOG.md；不擴張到 CRUD／Storage 或正式服務。

### 最新整合版實際驗證

| Repository | 最新實際 checkout 全套 pytest |
|---|---|
| InvoiceGuard-AI | 308 passed, 38 skipped, 1 warning in 11.86s |
| InvoiceGuard-AI-ADMIN | 393 passed, 9 skipped, 1 warning in 18.27s |
| InvoiceGuard-AI-API | 388 passed, 14 skipped, 1 warning in 15.54s |

三站各自 Python 3.12 venv、OS 環境白名單、PYTHONUTF8=1、-B、pytest -p no:cacheprovider；TEMP/TMP/basetemp 全在專案外。三站 check_project.py、Ruff check/format 全部 exit 0；前台及 ADMIN 各 14 份模板 djLint 0 errors；完整三站 --project-root 比對及從其他 cwd 以 -I 執行 checker 都 exit 0。每站僅既有 Starlette/httpx 淘汰警告。skip 包含站別限定案例與沒有 Windows symlink 權限的案例，不能算通過。

### 針對性證據與限制

- G1/G2 與 UTF-8 最小修正：六份互不共用父目錄的無秘密單站副本（每站固定名稱及改名各一份），治理測試前台各 82 passed/34 skipped、ADMIN 各 107/9、API 各 102/14；單站 checker 均 exit 0，明確 --project-root 缺站均 exit 1。API 父程序 PYTHONUTF8=0 的編碼案例另有 1 passed。這組結果取得於整合本輪 F1/F2 新增測試之前，與上表最新整合版分開記錄；完整跨站測試在單站多出的 skip 是預期行為。
- F1/F2 的新增負例套用舊 checker：10 failed、6 passed、114 deselected（預期）；含真實 py_compile 產物可成功 import、卻未被舊 checker 擋下的兩例，以及 if/try 類別／函式／async 重定義四例。新版能拒絕這些配置，正常 CPython/opt-1/opt-2 來源快取及無關類別/docstring 正例仍通過。
- 外部舊版有效性 driver 在保存 pytest 結果後，列印大量中文到 CP950 主控台曾發生 UnicodeEncodeError；保留該限制，不把 driver 當 exit 0。預期的 pytest 10 failed 摘要與證據已保存，本輪實際 checkout 驗證則使用明確 UTF-8。
- 本輪只修改三站各自 checker、治理測試、PROJECT_CHECKS.md、TEST_REPORT.md、REVIEW_FIX_LOG.md 共 15 個既有檔；快照及 AGENTS 共同規則未變，無需重建快照。業務程式、Schema、ORM、依賴、CI、STARTUP、雲端設定均未改。
- 未執行 GitHub 遠端 CI、Linux runner、全新套件安裝、真登入／DB／Storage／Vercel；未啟動服務或 Tunnel。靜態檢查仍不是沙箱，快取驗證也不證明位元組碼內容與來源相符。

### 證據與版本

本輪命令、exit、輸出及 Git／檔案基準：C:/Project/tmp/invoiceguard-governance-followup-20261023（validation-results.json、baseline.json、final-audit.json）。F1/F2 外部副本與舊版測試：C:/Project/tmp/invoiceguard-independent-checker-fixes-20261023；G1/G2/編碼六份副本：C:/Project/tmp/ig-review-standalone-20261023/evidence-ab06aa994c374b76bf8075a3dc617a9d（results.json、fixed-results.json）。

本輪 checker SHA256：`ef0e5c0ec547f38558d093a75d3a6c62191a9208ede30c6effb4fbeb3dcef5ec`；治理測試 SHA256：`f3facce4f7de9c62babd606d143da6c806aa8355ebebdd0eb88ea18d77601039`。公司密鑰未讀取或下載，沒有部署、migration、正式資料修改、Commit／Merge／Push。


## 2026-10-23 Claude 獨立覆核：F1–F3、單站 CI 與改名 Clone

以磁碟上最新未提交內容為準。開始前保存三站 branch／HEAD／index 雜湊／完整 status（含未追蹤）與全部檔案雜湊；開始時的 checker／治理測試 SHA256 與前節紀錄一致（`ef0e5c0e…`／`f3facce4…`），全套 pytest 重跑為前台 308 passed／38 skipped、ADMIN 393／9、API 388／14，與前節相同。

### F1：__pycache__ 位元組碼

專案外副本以合成來源與 `py_compile`／`compileall` 產生檔案，再用隔離子程序（`-I -B -X utf8`）實際 import 證明負例可被執行；不讀取或執行專案既有 .pyc。三站各 12／12 符合預期：

- 拒絕（compiled_module）：`__pycache__/name.pyc`（可 import）、`__pycache__/__init__.pyc`（可 import 成套件）、無來源的標籤快取（不可 import，依規範仍拒絕）、`__pycache__/nested/` 巢狀快取（可 import）、來源旁的舊式 `name.pyc`（可 import）、大小寫不同的 `__PYCACHE__/name.pyc`（Windows 可 import）、`__pycache__` 內非位元組碼檔、`compileall -b` 整站舊式輸出（另有 source_location）。
- 通過：有對應來源的標準標籤快取 opt-0／opt-1／opt-2；以 `compileall -o 0 -o 1 -o 2` 為整個 app 產生的實際快取（API 165、ADMIN 153、前台 78 個 .pyc）。
- 符號連結負例：本機沒有建立 symlink 的權限（WinError 1314），三站皆明確 **skip，不算通過**；治理測試中的 symlink 案例同樣 skip。

### F2：條件區塊內重新定義契約

前節 F2 的 if／try 內 class PageQuery、def／async def reject_bool_and_float 與真實專案層級 contract_drift 均重現成功；else／finally、for／with／walrus／del／增量指定也會改變摘要。另發現 **6 個仍可重新綁定核定名稱的寫法**：if／try 內的 import、檔尾頂層 `from typing import Any as PageQuery`、`except ValueError as reject_bool_and_float`、`match … case PageQuery`，以及平台子集的頂層 `from os import getcwd as get_platform`。這些寫法的摘要不變，`if True: from typing import Any as PageQuery` 在專案層級也沒有 contract_drift。修正後 API／ADMIN 的探測都是 0 個非預期結果；無關定義、無關 import／except／match、備註與 docstring 不誤報。現有程式的 common／platform 摘要仍等於核定快照，**快照未修改**。

### F3：Windows 隔離子程序編碼

其他工作目錄測試保留 `-I`、使用 `-X utf8`，成功與失敗兩次 `subprocess.run` 都指定 `encoding="utf-8"`，沒有 `errors=`；exit 0、新增不合法目錄後 exit 1 與 source_location 斷言保留。三站分別以父程序 PYTHONUTF8=1、PYTHONUTF8=0，再加上中文路徑的 basetemp 執行，各 3 passed。

另發現 F1 新增的「可 import」證明測試，子程序有 `-I` 但沒有 `-X utf8`，讀取時也沒有指定 encoding。重現：父程序 PYTHONUTF8=1（CI 設定）時，子程序錯誤訊息含非 ASCII，讀取會 UnicodeDecodeError，stderr 變成 None，失敗診斷被 TypeError 取代。比照 F3 修正後，兩種模式皆通過。

### 單站 CI 與改名 Clone（六份隔離副本）

每份副本放在不同父目錄，只含 Git 追蹤與未忽略的未追蹤檔；已確認沒有 .git、.venv、__pycache__ 或 .env。使用原站 venv，子程序只傳 OS 環境白名單與 PYTHONUTF8=1。

| 副本 | 角色（APP_NAME） | checker | 治理測試 | 完整跨站測試 | 明確 --project-root 缺站 | 他處絕對路徑 -I | 全套 pytest |
|---|---|---|---|---|---|---|---|
| 前台 固定名／改名 | InvoiceGuard-AI | exit 0 | 92 passed, 45 skipped | 1 skipped | exit 1 peer_missing | exit 0 | 308 passed, 45 skipped |
| ADMIN 固定名／改名 | InvoiceGuard-AI-ADMIN | exit 0 | 127 passed, 10 skipped | 1 skipped | exit 1 peer_missing | exit 0 | 399 passed, 10 skipped |
| API 固定名／改名 | InvoiceGuard-AI-API | exit 0 | 122 passed, 15 skipped | 1 skipped | exit 1 peer_missing | exit 0 | 394 passed, 15 skipped |

改名副本的資料夾名稱為小寫加 `-renamed-clone`，角色仍由 Settings.APP_NAME 辨識。明確跨站模式在固定名副本回報 2 個缺站、改名副本 3 個（自身資料夾也不是固定名稱），兩者都是 exit 1。

### 三站實際專案完整檢查（OS 環境白名單）

| Repository | check_project | 全套 pytest | 完整跨站測試 | Ruff check／format | djLint | --project-root .. |
|---|---|---|---|---|---|---|
| InvoiceGuard-AI | exit 0 | **309 passed, 44 skipped** | 1 passed | exit 0／exit 0 | exit 0（14 檔） | exit 0 |
| InvoiceGuard-AI-ADMIN | exit 0 | **400 passed, 9 skipped** | 1 passed | exit 0／exit 0 | exit 0（14 檔） | exit 0 |
| InvoiceGuard-AI-API | exit 0 | **395 passed, 14 skipped** | 1 passed | exit 0／exit 0 | 不適用 | exit 0 |

與基準 308／38、393／9、388／14 的差異，就是本輪新增的 7 個測試：6 個 import／except／match 重新綁定案例只適用後端，在前台 skip；1 個無關綁定的摘要測試三站都會執行。單站副本比實際專案多 1 個 skip，是缺兄弟站時預期 skip 的完整跨站測試。每站仍只有既有 Starlette/httpx 淘汰警告。

### 有效性、CI 與未驗證

- 新測試放進含舊 checker 的專案外副本：7 failed（預期），新版全數通過。突變只在專案外副本進行。
- CI 工作流程未改：單站 checkout（persist-credentials: false）、Python 3.12、ubuntu／windows matrix、contents: read、PYTHONUTF8=1；不使用 secrets、pull_request_target、部署或 migration。
- **未執行**：GitHub 遠端 CI、Linux runner、symlink 負例（沒有權限）、全新 pip 安裝、真登入／DB／Storage／Vercel；未啟動服務或 Tunnel。快取檢查不驗證位元組碼內容是否與來源一致（依規範不要求）；反射與完整資料流仍不在靜態檢查範圍。
- 版本：checker `0b5379e35b360cd500dbbe024bf217898ff0904218a028b4106074787ee4d68a`；治理測試 `9df56dd83217b8eff61ced1d4ab72291b6d68a1a3ad1d5888863d94a002fc538`；PROJECT_CHECKS `0f91a4f84c37664c4ba120bb9f0f3dee70834a55fa4225bb8fed1077519ae2aa`；契約快照 `b9512b51b6d8c2977add4ba9758efddcc49e1f052ed124275a5aa4cfe24efc03`（未變）。三站逐位元組一致。
- 證據：C:\Project\tmp\invoiceguard-claude-governance-followup-20261023（f1-final.txt／f1-*.json、f2-prefix-observed.txt、f2-final.txt、f2-api（修正前探測用的專案外突變副本）、section34-results.json、scripts）。

## 2026-10-23 Codex：最新版獨立實際驗收（含六份隔離 Clone）

本節為重新執行的結果，沒有以 Claude 報告替代實測。保存 branch／HEAD／完整 status（含未追蹤）／索引檔案雜湊與 entries，以及三站和 STARTUP 的非機密來源基準；排除 .env／密鑰、Git／venv／快取及暫存。複製清單來自 Git 追蹤及未忽略的未追蹤檔，僅取核定非機密文字來源／設定／文件；不讀公司環境值，不執行 Git Clone 或下載秘密。

### 修正前驗證與本輪發現

獨立重跑 Claude 最新版原始三站為前台 309 passed/44 skipped、ADMIN 400/9、API 395/14，與其報告一致。六份無兄弟站副本也完整通過（前台各 308/45、ADMIN 各 399/10、API 各 394/15）。F1、F3 及已報告的條件式／import／except／match 重新綁定均符合預期。

另有 **中 R1：條件區塊內的 from … import * 可重新綁定核定名稱，子集摘要卻不變**。用完全合成模組及隔離 Python 子程序，實證 Entry 被換成 synthetic-replacement；舊 ast_digest 仍相同。修正為對條件區塊內無法靜態確定名稱的星號匯入，保守保留整個敘述。頂層星號匯入原有保護保留，無關明確匯入仍不改摘要。增加 6 個回歸案例（後端專案 DTO/Vercel 三例、所有站可執行的子集摘要三例）；對舊 checker 為 5 failed/1 passed（預期），新 checker 為 6 passed。沒有刪測試、放寬規則或重建快照。

### 修正後最終版：三站完整實測

| Repository | 最終版原始專案完整 pytest |
|---|---|
| InvoiceGuard-AI | 312 passed, 47 skipped, 1 warning in 25.76s |
| InvoiceGuard-AI-ADMIN | 406 passed, 9 skipped, 1 warning in 39.05s |
| InvoiceGuard-AI-API | 401 passed, 14 skipped, 1 warning in 34.12s |

三站 checker、Ruff lint/format、前台/ADMIN 各 14 份模板 djLint 均 exit 0，完整三站 --project-root 比對 exit 0。使用各站原有 Python 3.12 venv、OS 環境白名單、PYTHONDONTWRITEBYTECODE=1、-B、pytest -p no:cacheprovider；TEMP/TMP/basetemp 全在專案外。每站仍只有既有 Starlette/httpx 淘汰警告。相較修正前新增 6 個測試：前台多 3 passed/3 skipped，ADMIN/API 各多 6 passed。

### 修正後最終版：六份隔離副本

| 隔離副本 | 完整 pytest | 其中治理案例 |
|---|---|---|
| InvoiceGuard-AI-canonical | 311 passed, 48 skipped | 95 passed, 48 skipped |
| InvoiceGuard-AI-renamed | 311 passed, 48 skipped | 95 passed, 48 skipped |
| InvoiceGuard-AI-ADMIN-canonical | 405 passed, 10 skipped | 133 passed, 10 skipped |
| InvoiceGuard-AI-ADMIN-renamed | 405 passed, 10 skipped | 133 passed, 10 skipped |
| InvoiceGuard-AI-API-canonical | 400 passed, 15 skipped | 128 passed, 15 skipped |
| InvoiceGuard-AI-API-renamed | 400 passed, 15 skipped | 128 passed, 15 skipped |

每份副本在不同父目錄，無 .git、venv、.env 或預存快取；固定名與小寫加 -clone 改名各一份，角色均依 APP_NAME。六份完整 pytest 均 exit 0；單站 checker 與其他 cwd 的絕對路徑 -I -B -X utf8 均 exit 0。完整跨站比對測試因無兄弟站各 1 skipped；明確 --project-root 均 exit 1，固定名回報 2 個 peer_missing、改名回報 3 個，不靜默跳過。表中 skipped 只為站別不適用、缺兄弟站與無 symlink 權限，未計入通過。

### 修正後最終版：獨立 F1–F3 與重新綁定探測

- F1：每站 14 案例，13 符合預期、1 symlink 案例因 WinError 1314 明確 skip。合成 py_compile 產物中的一般/套件/巢狀/來源旁舊式/大小寫快取及快取內 .py，另經隔離子程序成功匯入再確認拒絕。無來源標記快取、非快取文字、compileall -b 均拒絕；標準 opt-0/1/2 與整站 compileall 快取正常。只編譯副本來源，不讀或執行既有 .pyc。
- F2：ADMIN/API 各 22 個案例全符合預期（17 重新綁定/改寫負例、5 無關變更正例）。包含 if/try class、def/async、if/try/頂層 import、except as、match 擷取/star/rest、for/with 目標、walrus、del、Vercel 子集及本輪 if 星號匯入。全部只做 AST/快照分析，不執行 app。R1 的實際執行證據另使用完全合成類別與模組。
- F3：每站父程序 PYTHONUTF8=0/1、中文暫存路徑，各重跑 3 個目標案例，共 18 個通過；另 6 次合成中文 RuntimeError 正確回傳 exit 1，stderr 維持可解碼字串，診斷不被 TypeError 取代。AST 確認兩個隔離測試的 command 都保留 -I -X utf8，全部 subprocess.run 明確 encoding='utf-8' 且無 errors=。

### 稽核、證據與未驗證

本輪只改三站各自 scripts/check_project.py、tests/unit/test_project_governance.py、docs/PROJECT_CHECKS.md、docs/TEST_REPORT.md、docs/REVIEW_FIX_LOG.md，共 15 個既有檔。共用檔逐位元組相同，契約快照與 AGENTS 規則保持原版；業務程式、Schema/ORM、依賴、CI 工作流程、STARTUP 及其校驗碼未動。Git branch/HEAD/index/status 保留。git diff --check 外另核對非機密未追蹤檔的空白，含能抓出故意行尾空白的正向控制。

證據根目錄：C:/Project/tmp/invoiceguard-independent-acceptance-20261023-01。baseline.json、actual-results.json、copies-results.json、f1/f2/f3-results.json 為修正前；final/ 同名檔是修正後最終版（含新的隔離副本）。wildcard-runtime-proof/result.json、regression-control-results.json 留存重現與新舊對照；final-audit.json、evidence-manifest.json 為最終範圍/版本紀錄。原始命令、exit、stdout/stderr 與 JUnit 結果均留存。初次外部 probes.py 有括號語法錯誤，未執行任何案例即失敗；修正後重新實跑，不將那次當通過或當專案缺陷。

GitHub CI 僅唯讀檢查設定：單站 checkout、Python 3.12、Windows/Linux matrix、contents:read、persist-credentials:false，無公司 secrets/pull_request_target/部署/migration。**未執行**遠端 CI、Linux runner、全新 pip 安裝、真登入/DB/Storage/Vercel、symlink 真負例（權限不足）。未啟服務/Tunnel，不實作 CRUD/Storage；公司密鑰留雲端，沒有部署、migration、正式資料修改、Commit/Merge/Push。AST/快取規則仍不是安全沙箱或完整資料流/位元組碼內容驗證。

- scripts/check_project.py SHA256：`10606142544faecc593666bb1f3a22042d323c3d950854215e468f4265062641`
- tests/unit/test_project_governance.py SHA256：`731babcbf5354a698d5422054b599d567d2576c28a72a485d44f6538ef5daffa`
- docs/PROJECT_CHECKS.md SHA256：`c4715b295d4ffbf56aef644c1fe958a93158d4d8145c3d8845d314617061d514`
- contracts/project-contract.json SHA256：`b9512b51b6d8c2977add4ba9758efddcc49e1f052ed124275a5aa4cfe24efc03`

稽核方法補註：未追蹤檔以單次 Git -c 選項避免全域 LF/CRLF 轉換警告，並將 CR 視為合法行尾；不改使用者 Git 設定。--no-index 因檔案內容不同可回傳 1，須連同診斷、LF/CRLF 乾淨控制、故意行尾空白控制及逐行檢查判斷。初次稽核腳本曾將此回傳碼/換行警告誤判，已校正；另移除本輪報告追加時產生的結尾空行，不視為應用缺陷。


## 2026-10-23 Claude 獨立覆核：R1 條件式星號匯入、F1–F3 與六份 Clone

以磁碟上最新未提交內容為準。開始前保存三站 branch／HEAD／index 雜湊／完整 status（含未追蹤）與全部檔案雜湊；開始時 checker `10606142…`、治理測試 `731babcb…`、PROJECT_CHECKS `c4715b29…`、契約 `b9512b51…`，與 Codex 前節紀錄一致。

### R1：條件式 `from … import *`

- 實際執行證據：專案外完全合成的 `synthetic_overrides.py`（`Entry = "synthetic-replacement"`）與含 `class Entry` 的目標模組，在隔離子程序（`-I -B -X utf8`）匯入。if／try／頂層星號匯入三種寫法，`Entry` 都被換成字串；無星號與 if 內無關明確匯入時仍是原類別。
- 摘要：修正前 checker（`0b5379e3…`）對 if／try 星號匯入摘要不變，只有頂層星號匯入會變；R1 版三種寫法都會改變。無關明確匯入、無關定義、備註、docstring 不改變摘要。
- 專案層級（API／ADMIN 專案外副本）：common.py 的 if／try／頂層，以及 vercel.py 的 if／try 星號匯入，R1 版皆產生 contract_drift（修正前只有頂層會）；無關明確匯入與無關函式不誤報。現有三站來源的 common／platform 摘要仍等於核定快照，**快照未重建**。
- 新舊對照（專案外副本替換 checker）：後端 `-k wildcard` 對修正前為 5 failed／1 passed、R1 版為 6 passed，與 Codex 回報相同。唯一在舊版仍通過的案例是頂層星號匯入（原本就有保護）。前台因契約案例不適用，為 2 failed／1 passed／3 skipped 與 3 passed／3 skipped。

### F2：其他重新綁定（含本輪新發現 F2-b）

API／ADMIN 各 59 個 AST 案例（common／platform 子集），只做 AST 分析，不執行 app。R1 版對既有規則列出的寫法全部正確：if／try class、def／async def、if／try／頂層 import、except as、match 擷取／star／mapping rest／關鍵字擷取、for／with 目標、海象、del、增量、屬性／索引指定、type 別名、鏈式指定與星號匯入。無關變更正例（無關 class／async／import／except／match、只讀取核定名稱的函式／子類別／別名、備註、docstring）不改變摘要。

另發現 **中 F2-b：重新綁定藏在「無關的頂層定義」裡時不會進入摘要**（R1 版每站 13 個非預期結果）。例如 `_synthetic = (PageQuery := dict)`、`_x: object = (…)`、模組層推導式或 lambda 預設值中的海象、`def _f(v=(PageQuery := dict))`、`@(PageQuery := …)` 裝飾器、`class _C((PageQuery := dict))`、class 本體 `global PageQuery; PageQuery = dict`、class 本體 `PageQuery.model_config = {}`，以及含 `global`／索引指定的函式在頂層被呼叫。合成模組在隔離子程序匯入時，11 種寫法都實際改寫或修改了 `Entry`；R1 版摘要不變，在 API／ADMIN 副本加入 common.py 與 vercel.py 的代表案例後，整個專案檢查沒有任何 issue。修正後所有案例符合預期（非預期結果 0），代表案例產生 contract_drift，現有摘要與快照不變。

### F1：快取配置

專案外副本，以合成來源及 `py_compile`／`compileall` 產生；可匯入的負例先在隔離子程序成功匯入，再確認 checker 拒絕。不讀取或執行專案既有 .pyc。前台 13 案例符合預期、1 個 skip；ADMIN 13 案例符合預期、1 個 skip；API 13 案例符合預期、1 個 skip：

- 拒絕：`__pycache__/name.pyc`、`__pycache__/__init__.pyc`、巢狀快取、來源旁舊式 `name.pyc`、大小寫不同的 `__PYCACHE__`、`__pycache__` 內的 `.py` 原始碼（皆已實證可匯入）；無來源的標籤快取（不可匯入，依規則仍拒絕）；快取內非位元組碼文字檔；`compileall -b` 整站輸出。
- 通過：有來源的標準標籤快取 opt-0／1／2，以及乾淨副本 `compileall -o 0 -o 1 -o 2` 整站輸出。
- symlink：本機無建立權限（WinError 1314），明確 **skip，不算通過**，未提升權限。

### F3：隔離子程序編碼

- AST 檢查三站兩個隔離測試：命令皆保留 `-I` 並有 `-X utf8`，全部 `subprocess.run` 明確 `encoding="utf-8"`，沒有 `errors=`。
- 三站以父程序 PYTHONUTF8=0／1，各搭配 ASCII 與中文 TEMP／basetemp，目標 3 案例每次皆 3 passed（三站共 12 次執行）；exit 0、新增不合法目錄 exit 1 與 source_location 斷言保留。
- 中文失敗可讀性（專案外副本注入中文 RuntimeError 到 checker 與合成匯入模組）：兩種模式下，失敗訊息皆完整可讀，沒有 UnicodeDecodeError／TypeError。對照組移除 `-X utf8` 與 encoding 後，PYTHONUTF8=1 會重現 UnicodeDecodeError 與 TypeError，中文訊息被遮蔽，證明此驗證能分辨。
- **低 F3-b**：絕對路徑測試的成功斷言訊息只帶 stdout；子程序崩潰時中文 stderr 只出現在 pytest 截斷的 CompletedProcess repr 中，不是獨立訊息行。已改為附上 stderr 尾端；修正後兩則中文訊息都以獨立的 `E` 行出現。

### 六份隔離副本（每份不同父目錄，無兄弟站）

只含 Git 追蹤與未忽略的未追蹤檔，已確認沒有 .git、.venv、__pycache__、.env；共用檔與原站逐位元組相同。使用原站 venv，子程序只傳 OS 環境白名單、PYTHONUTF8=1，TEMP／TMP／basetemp 為本輪新的專案外目錄。

| 副本 | 角色（APP_NAME） | checker | 治理測試 | 完整跨站測試 | 明確 --project-root | 他處絕對路徑 -I -X utf8 | 全套 pytest |
|---|---|---|---|---|---|---|---|
| 前台 固定名（`InvoiceGuard-AI`） | InvoiceGuard-AI | exit 0 | 106 passed, 53 skipped | 1 skipped | exit 1（peer_missing=True） | exit 0 | 322 passed, 53 skipped |
| 前台 改名（`invoiceguard-ai-renamed-clone`） | InvoiceGuard-AI | exit 0 | 106 passed, 53 skipped | 1 skipped | exit 1（peer_missing=True） | exit 0 | 322 passed, 53 skipped |
| ADMIN 固定名（`InvoiceGuard-AI-ADMIN`） | InvoiceGuard-AI-ADMIN | exit 0 | 149 passed, 10 skipped | 1 skipped | exit 1（peer_missing=True） | exit 0 | 421 passed, 10 skipped |
| ADMIN 改名（`invoiceguard-ai-admin-renamed-clone`） | InvoiceGuard-AI-ADMIN | exit 0 | 149 passed, 10 skipped | 1 skipped | exit 1（peer_missing=True） | exit 0 | 421 passed, 10 skipped |
| API 固定名（`InvoiceGuard-AI-API`） | InvoiceGuard-AI-API | exit 0 | 144 passed, 15 skipped | 1 skipped | exit 1（peer_missing=True） | exit 0 | 416 passed, 15 skipped |
| API 改名（`invoiceguard-ai-api-renamed-clone`） | InvoiceGuard-AI-API | exit 0 | 144 passed, 15 skipped | 1 skipped | exit 1（peer_missing=True） | exit 0 | 416 passed, 15 skipped |

### 三站實際專案完整檢查（OS 環境白名單、專案外 TEMP／basetemp）

| Repository | check_project | 全套 pytest | 完整跨站測試 | Ruff check／format | djLint | --project-root .. |
|---|---|---|---|---|---|---|
| InvoiceGuard-AI | exit 0 | **323 passed, 52 skipped** | 1 passed | exit 0／exit 0 | exit 0 | exit 0 |
| InvoiceGuard-AI-ADMIN | exit 0 | **422 passed, 9 skipped** | 1 passed | exit 0／exit 0 | exit 0 | exit 0 |
| InvoiceGuard-AI-API | exit 0 | **417 passed, 14 skipped** | 1 passed | exit 0／exit 0 | 不適用 | exit 0 |

與 Codex 基準（前台 312／47、ADMIN 406／9、API 401／14）的差異，就是本輪新增的 16 個測試：5 個專案層級案例只適用後端（前台 skip），10 個合成摘要案例與 1 個只讀正例三站都執行。因此前台多 11 passed／5 skipped，ADMIN／API 各多 16 passed。單站副本比實際專案多 1 個 skip，是缺兄弟站時預期 skip 的完整跨站測試。skip 只代表站別不適用、缺兄弟站或無 symlink 權限，未計入通過。每站仍只有既有 Starlette／httpx 淘汰警告。

### 有效性、CI 與未驗證

- F2-b 新測試對 R1 版 checker：後端 15 failed／7 passed（7 passed 為一併執行的 6 個 R1 星號匯入案例與 1 個只讀正例），前台 10 failed／4 passed／8 skipped；修正版後端 22 passed、前台 14 passed／8 skipped。突變與新舊對照只在專案外副本進行。
- CI 只做靜態審查，工作流程未改：單站 checkout、persist-credentials: false、Python 3.12、ubuntu／windows matrix、contents: read、PYTHONUTF8=1；沒有 secrets、pull_request_target、部署或 migration。
- **未執行**：GitHub 遠端 CI、Linux runner、symlink 負例（權限不足）、全新 pip 安裝、真登入／DB／Storage／Vercel；未啟動服務或 Tunnel。仍不在範圍：`getattr`／`setattr`／`globals` 等反射，以及無關定義內用方法呼叫（例如 `.update()`）間接修改核定物件；快取檢查不驗證位元組碼內容。
- 版本：checker `823eee6b5980cbe6ef3f8182f570c6b7ebad875d7cd13985a71aa5e301ca359c`；治理測試 `3f411940be134beadc5d7e4b821521e110185c74eda5b0d61922e0c1d5d09953`；PROJECT_CHECKS `3ed47346f094629ac238ab742662f406e737a0bb6c1e06336be90a9c18b635eb`；契約快照 `b9512b51b6d8c2977add4ba9758efddcc49e1f052ed124275a5aa4cfe24efc03`（未變）。三站逐位元組一致。
- 證據：C:\Project\tmp\invoiceguard-claude-governance-r1-20261023（r1-results.json、controls-*.json、f2-*.json、gap-proof-*.json、f1-*.json、f3-results.json、copies-results.json、final-audit.json、scripts）。

## 2026-10-23 Codex：F2-b／F3-b 最新版完整獨立驗收

本節實際重新執行完整驗收，取代前次僅聚焦 23 個案例的覆核範圍，沒有以 Claude 結果代替實測。先保存三站 branch／HEAD／status（含未追蹤）／索引檔 SHA256 與 entries，以及三站／STARTUP 非機密來源基準；公司環境值及 .env／秘密檔未納入。測試使用各站原有 Python 3.12 venv、OS 環境白名單、-B、PYTHONDONTWRITEBYTECODE=1、pytest -p no:cacheprovider，TEMP/TMP/basetemp 與突變全部留在專案外。

修正前獨立全套結果與 Claude 一致：前台 323 passed/52 skipped、ADMIN 422/9、API 417/14；六份隔離副本各為前台 322/53、ADMIN 421/10、API 416/15。R1、F1–F3、F2-b 的已報告改寫與 F3-b 診斷都重現有效。

### 本輪發現與修正：低 R2，只讀 global 宣告誤報

合成模組證明 `def build(): global Entry; return Entry()` 及只讀 class 本體不改寫 Entry，但 `_rebound_in_definition` 只看見 global 宣告便將整個定義納入摘要，產生契約漂移誤報。修正為 global 名稱必須同時有實際寫入／刪除或字串名稱綁定；海象與屬性／索引寫入保護保留。import、class/def、except/match 的綁定也納入，不以僅有 Name(Store) 的規則漏掉它們。不是完整作用域／資料流分析。

新增 7 個回歸案例：2 個只讀 global 摘要正例、3 個 global import／class 定義／del 負例、2 個後端 DTO/Vercel 專案只讀 helper 正例。外部 API 新舊對照為舊版 4 failed/3 passed（誤報重現）、新版 7 passed；既有改寫測試維持有效。快照沒有重建。前台新增 5 passed/2 skipped；ADMIN/API 各新增 7 passed。

### 修正後原始三站完整結果

| Repository | 本輪最終版完整 pytest |
|---|---|
| InvoiceGuard-AI | 328 passed, 54 skipped, 1 warning in 28.24s |
| InvoiceGuard-AI-ADMIN | 429 passed, 9 skipped, 1 warning in 40.76s |
| InvoiceGuard-AI-API | 424 passed, 14 skipped, 1 warning in 36.66s |

三站 checker、Ruff check/format 與完整 --project-root 跨站比對皆 exit 0；UI 兩站各 14 份模板 djLint exit 0。每站仍只有既有 Starlette/httpx 淘汰警告。

### 修正後六份單站／改名 Clone

| 隔離副本 | 完整 pytest | 治理子集（由 JUnit 計數） |
|---|---|---|
| InvoiceGuard-AI-canonical | 327 passed, 55 skipped | 111 passed, 55 skipped |
| InvoiceGuard-AI-renamed | 327 passed, 55 skipped | 111 passed, 55 skipped |
| InvoiceGuard-AI-ADMIN-canonical | 428 passed, 10 skipped | 156 passed, 10 skipped |
| InvoiceGuard-AI-ADMIN-renamed | 428 passed, 10 skipped | 156 passed, 10 skipped |
| InvoiceGuard-AI-API-canonical | 423 passed, 15 skipped | 151 passed, 15 skipped |
| InvoiceGuard-AI-API-renamed | 423 passed, 15 skipped | 151 passed, 15 skipped |

每份為最新非機密來源副本，固定名稱／小寫加 -clone 各一份，分置不同父目錄，沒有兄弟 Repository、.git、venv、.env 或預存快取。角色均由 APP_NAME 判斷；單站 checker、他處絕對路徑 -I -B -X utf8 均 exit 0，完整 pytest 均 exit 0。缺兄弟時完整跨站測試各 1 skipped；明確 --project-root 為 exit 1，固定名各 2 個 peer_missing、改名各 3 個。skip 另含站別不適用與 WinError 1314 symlink 權限不足，均不計通過。

### R1、F1–F3、F2-b／F3-b 獨立證據

- R1：完全合成模組的 if／try／頂層星號匯入都在隔離子程序實際改寫 Entry。修正前 checker 只抓到頂層，最新版三種皆抓到。三站外部舊版控制重跑：後端 5 failed/1 passed、前台 2 failed/1 passed/3 skipped（預期）；現版由全套回歸驗證通過。
- F1：三站各 14 個獨立配置案例，13 符合預期、1 symlink 因 WinError 1314 skip。有效合成 .pyc 在隔離子程序證明可匯入後再確認拒絕；正常 opt-0/1/2 與整站 compileall 快取通過，舊式／無來源／巢狀等配置拒絕。不讀取或執行專案既有 .pyc。
- F2：ADMIN/API 各 22 個獨立案例全符合預期，含 if/try 定義、import、except/match/star/rest、for/with、walrus、del、平台子集，以及無關變更控制。
- F2-b：11 種合成寫法實際匯入後確實替換或修改 Entry，最新版摘要皆變；7 個不改寫控制（含本輪只讀 global 兩例）維持摘要。ADMIN/API 各 5 個真實來源副本改寫案例都產生 contract_drift，R1 舊版會漏判。三站外部舊版對照重新執行，後端 15 failed/1 passed、前台 10 failed/1 passed/5 skipped（預期）。
- F3：父程序 UTF8=0/1、ASCII 與中文 TEMP/basetemp，三站每組 3 passed，共 36 次目標案例通過；AST 確認 -I -X utf8、encoding='utf-8' 保留，無 errors= 忽略／替換。另以合成中文錯誤確認 stderr 是可讀字串。
- F3-b：三站外部副本故意讓 checker 與合成匯入模組拋中文 RuntimeError，在 UTF8=0/1 的 6 組 pytest 各 3 failed（預期），兩則中文訊息都能在獨立 E 行讀取，沒有 UnicodeDecodeError/TypeError。改回只附 stdout 的控制看不到 checker 的獨立訊息；移除 UTF-8 保護的控制會重現解碼錯誤與 TypeError。這些故意失敗控制依預期核對，不當成正式測試失敗。

### 修改範圍、證據與限制

本輪只改三站各自 checker、治理測試、PROJECT_CHECKS、TEST_REPORT、REVIEW_FIX_LOG 共 15 個既有檔；共用副本逐位元組相同。契約快照、AGENTS、業務、Schema/ORM、依賴、CI、STARTUP 與其校驗碼未動。Git branch/HEAD/index/status 與原基準一致；另檢查 55 個非機密未追蹤檔，使用 LF/CRLF 乾淨控制、故意行尾空白控制與逐行掃描。單次 Git -c 選項僅避免換行警告，沒有修改全域設定；no-index 回傳 1 與空白診斷分開判斷。

證據：C:/Project/tmp/invoiceguard-full-acceptance-f2b-20261023-01。根目錄 baseline.json、actual/copies/f1/f2/f3-results.json、definitions-results.json、f3b-results.json 為修正前；final/ 同名檔是修正後重跑的最終版。readonly-control-results.json 為本輪 R2 新舊控制。final-audit.json／evidence-manifest.json 留存最終範圍、Git 與 SHA256。外部故障控制器初版誤把其他 write_text 的 encoding 算入安全斷言而中止；改為只限兩個目標函式、使用新副本重跑，未視為專案缺陷，舊的局部證據保留於 f3b/。

未執行 GitHub 遠端 CI、Linux runner、全新 pip 安裝、真登入/DB/Storage/Vercel，以及需 symlink 權限的負例。CI 僅本機唯讀解析 YAML 確認原有安全設定。靜態分析仍不涵蓋完整反射、資料流與無關定義中的方法呼叫間接改寫，也不驗證快取位元組碼內容。未啟服務/Tunnel、不實作 CRUD/Storage，不部署、migration、正式資料修改或 Commit/Merge/Push；公司密鑰留雲端。

- scripts/check_project.py SHA256：`c7a4aff63ee91435a522f911e40868ad550019f3ad449264d04ef138639ca6cb`
- tests/unit/test_project_governance.py SHA256：`453e9b4813211c26d8aca694225ea989a1131cd502f0cbba648441ea0be27fe4`
- contracts/project-contract.json SHA256：`b9512b51b6d8c2977add4ba9758efddcc49e1f052ed124275a5aa4cfe24efc03`


## 2026-10-23 Claude 獨立驗收：R2 只讀 global、R1、F1–F3、F2-b／F3-b 與六份 Clone

以磁碟上最新未提交內容為準，全部實際重跑，未以既有報告或 JSON 代替。開始前保存三站 branch／HEAD／index 雜湊／完整 status（含未追蹤）及全部檔案雜湊；開始時 checker `c7a4aff6…`、治理測試 `453e9b48…`、PROJECT_CHECKS `dab52fc2…`、契約 `b9512b51…`，與 Codex 前節紀錄一致。舊版 checker 先核對雜湊再使用：修正前 `0b5379e3…`、R1 `10606142…`、F2-b `823eee6b…`，與上一輪 Claude 證據的 SHA256SUMS 及 Codex 證據 before-fix 副本一致，沒有缺失。

### R2：只讀 global 誤報修正

完全合成的 `Entry` 模組在隔離子程序（`-I -B -X utf8`）實際匯入，以物件身分、屬性值判斷「未變／被替換／被刪除」：

- 只讀 6 例（函式 `global Entry` 後回傳 `Entry()` 並在頂層呼叫、讀 `Entry.value`、class 本體只讀、方法讀取、巢狀內層只讀、`global Entry, _counter` 只寫 `_counter`）：物件皆未變。R2 版摘要不變；F2-b 版 6 例全部誤判為改變（重現 R2 原問題）。
- 寫入 23 例：global 賦值、tuple 解包、`|=`、del、from-import、import 模組、class、def、async def、except as（離開 handler 時刪除）、match 擷取／star／mapping rest、for、with、海象、巢狀內層賦值、class 本體 global import／def／賦值，以及既有 F2-b 的無 global 海象、屬性、索引改寫。物件皆確實被替換、刪除或修改。R2 版摘要全部改變。
- 合成案例非預期結果：修正前 23、R1 23、F2-b 6（只讀誤報）、R2 0。
- 專案層級（API／ADMIN 專案外副本）：common.py／vercel.py 的只讀 def 與 class 本體 helper，R2 版完全沒有 issue，F2-b 版 8 例（API／ADMIN 各 4 例）產生 contract_drift；global except as、match 擷取、import、del、def 及 class 本體 global 賦值，R2 版皆產生 contract_drift，全部符合預期。現有來源仍等於原快照，**未重建快照**。
- 7 個 R2 回歸案例的新舊對照：API F2-b 版 4 failed／3 passed、R2 版 7 passed，與 Codex 回報相同；ADMIN 相同；前台因專案層級案例不適用，為 2 failed／3 passed／2 skipped 與 5 passed／2 skipped。

### 本輪發現與修正

- **低 T1｜match star／mapping rest 及「global 搭配 except／match」沒有回歸測試**：checker 行為正確（上述探測已驗證），但在 API 專案外副本做突變測試，拿掉 MatchStar 綁定、拿掉 MatchMapping rest 綁定，或讓 global 忽略 except／match 綁定，這 3 個突變在現有治理測試下全部存活（M1 drop MatchStar binding、M2 drop MatchMapping rest binding、M3 global ignores except/match bindings）。新增 `test_match_star_and_mapping_rest_rebindings_change_subset_digest`（2 例），在 R2 負例測試加入 global except as 與 match 擷取（2 例），並在無關綁定正例加入無關的 star／rest 擷取。修正後 9 個突變全部被殺（9／9）。
- **低 F3-c｜絕對路徑測試第二次執行的斷言沒有附 stdout／stderr**：在專案外副本讓 checker 只在偵測到未核定目錄時拋中文 RuntimeError。未捕捉例外也是 exit 1，所以 `failed.returncode == 1` 照樣通過，接著 `"source_location" in failed.stdout` 失敗，但中文診斷只出現在 pytest 截斷的 repr 中（還被從字中間截斷），不是獨立訊息行（三站兩種模式皆重現）。兩個斷言改為附上 stdout 與 stderr 尾端，修正後三站兩種模式都以獨立 `E` 行顯示中文診斷。

### R1、F2、F2-b 重跑

- R1：合成模組 if／try／頂層星號匯入都實際把 `Entry` 換成字串；R2 版三種都改變摘要，common／vercel 專案層級皆 contract_drift，無關明確匯入、無關定義、備註、docstring 不誤報，全部符合預期。
- F2：API／ADMIN 各 59 個 AST 案例，R2 版非預期 0，涵蓋 if／try class、def、async def，if／try／頂層 import，except as，match 擷取／star／mapping rest，for／with，海象，del，屬性／索引，type 別名，星號匯入，以及無關變更正例。
- F2-b：11 種合成寫法實際匯入後確實改寫或修改 `Entry`，R2 版摘要全部改變，只讀函式、子類別、別名控制不變；專案層級代表案例產生 contract_drift，無關 DTO 子類別不誤報。
- 舊版控制（R1＋F2-b 共 22 個測試）：後端修正前 20 failed／2 passed、R1 版 15 failed／7 passed、R2 版 22 passed；前台 12 failed／2 passed／8 skipped、10 failed／4 passed／8 skipped、14 passed／8 skipped。

### F1：快取配置

專案外副本以合成來源及 `py_compile`／`compileall` 產生；可匯入負例先在隔離子程序證明可匯入，再確認拒絕。不讀取或執行專案既有 .pyc。前台 13 案例符合預期、1 個 skip；ADMIN 13 案例符合預期、1 個 skip；API 13 案例符合預期、1 個 skip。拒絕：一般 `name.pyc`、`__init__.pyc`、巢狀快取、來源旁舊式 `.pyc`、`__PYCACHE__`、快取內 `.py`、無來源標籤快取（不可匯入，依規則拒絕）、快取內文字檔、`compileall -b`。通過：有來源的 opt-0／1／2 標準快取及乾淨副本整站 compileall。symlink 因 WinError 1314 明確 **skip，不算通過**，未提升權限。

### F3／F3-b：編碼與失敗診斷

- AST：兩個隔離測試保留 `-I` 並有 `-X utf8`，全部 `subprocess.run` 指定 `encoding="utf-8"`，沒有 `errors=`；絕對路徑測試修正後三個子程序結果斷言都附 stdout 與 stderr（`"PASS" in passed.stdout` 緊接在已附訊息的成功斷言之後）。
- 父程序 PYTHONUTF8=0／1 × ASCII／中文 TEMP 與 basetemp：三站共 12 次，每次皆 3 passed。
- 注入中文 RuntimeError（故意失敗，依預期核對，不當成正式測試失敗）：checker 啟動失敗與合成位元組碼匯入失敗，兩則訊息在兩種模式下都是獨立 `E` 行，沒有 UnicodeDecodeError／TypeError。
- 控制：改回只附 stdout 後，checker 診斷不再是獨立行；移除 UTF-8 保護後，重現 UnicodeDecodeError 與 TypeError。兩者都與預期相符，證明檢查能分辨。

### 六份隔離副本（每份不同父目錄，無兄弟站）

只含 Git 追蹤與未忽略的未追蹤檔，確認沒有 .git、.venv、__pycache__、.env；共用檔與原站逐位元組相同。使用原站 venv，子程序只傳 OS 環境白名單與 PYTHONUTF8=1，TEMP／TMP／basetemp 皆為本輪新的專案外目錄。

| 副本 | 角色（APP_NAME） | checker | 治理測試 | 完整跨站測試 | 明確 --project-root | 他處絕對路徑 -I -X utf8 | 全套 pytest |
|---|---|---|---|---|---|---|---|
| 前台 固定名（`InvoiceGuard-AI`） | InvoiceGuard-AI | exit 0 | 115 passed, 55 skipped | 1 skipped | exit 1（peer_missing=True） | exit 0 | 331 passed, 55 skipped |
| 前台 改名（`invoiceguard-ai-renamed-clone`） | InvoiceGuard-AI | exit 0 | 115 passed, 55 skipped | 1 skipped | exit 1（peer_missing=True） | exit 0 | 331 passed, 55 skipped |
| ADMIN 固定名（`InvoiceGuard-AI-ADMIN`） | InvoiceGuard-AI-ADMIN | exit 0 | 160 passed, 10 skipped | 1 skipped | exit 1（peer_missing=True） | exit 0 | 432 passed, 10 skipped |
| ADMIN 改名（`invoiceguard-ai-admin-renamed-clone`） | InvoiceGuard-AI-ADMIN | exit 0 | 160 passed, 10 skipped | 1 skipped | exit 1（peer_missing=True） | exit 0 | 432 passed, 10 skipped |
| API 固定名（`InvoiceGuard-AI-API`） | InvoiceGuard-AI-API | exit 0 | 155 passed, 15 skipped | 1 skipped | exit 1（peer_missing=True） | exit 0 | 427 passed, 15 skipped |
| API 改名（`invoiceguard-ai-api-renamed-clone`） | InvoiceGuard-AI-API | exit 0 | 155 passed, 15 skipped | 1 skipped | exit 1（peer_missing=True） | exit 0 | 427 passed, 15 skipped |

### 三站實際專案完整檢查

| Repository | check_project | 全套 pytest | 完整跨站測試 | Ruff check／format | djLint | --project-root .. |
|---|---|---|---|---|---|---|
| InvoiceGuard-AI | exit 0 | **332 passed, 54 skipped** | 1 passed | exit 0／exit 0 | exit 0 | exit 0 |
| InvoiceGuard-AI-ADMIN | exit 0 | **433 passed, 9 skipped** | 1 passed | exit 0／exit 0 | exit 0 | exit 0 |
| InvoiceGuard-AI-API | exit 0 | **428 passed, 14 skipped** | 1 passed | exit 0／exit 0 | 不適用 | exit 0 |

與 Codex 基準（前台 328／54、ADMIN 429／9、API 424／14；副本 327／55、428／10、423／15）相比，三站各多 4 passed：T1 新增的 2 個 match star／rest 案例與 2 個 global except／match 案例都是合成摘要測試，三站都會執行。單站副本多 1 個 skip，是缺兄弟站時預期 skip 的完整跨站測試。skip 只代表站別不適用、缺兄弟站或無 symlink 權限，未計入通過。每站仍只有既有 Starlette／httpx 淘汰警告。

### CI、未驗證與限制

- CI 僅本機唯讀檢查，工作流程未改：單站 checkout、persist-credentials: false、Python 3.12、ubuntu／windows matrix、contents: read、PYTHONUTF8=1；沒有 secrets、pull_request_target、部署或 migration。
- **未執行**：GitHub 遠端 CI、Linux runner、symlink 負例（權限不足）、全新 pip 安裝、真登入／DB／Storage／Vercel；未啟動服務或 Tunnel。
- 仍不在範圍（依既有文件）：`getattr`／`setattr`／`globals` 等反射、無關定義內以方法呼叫間接修改、完整作用域／資料流分析；global 判斷以整個定義為單位，巢狀作用域中同名的區域寫入會保守視為改寫。快取檢查不驗證位元組碼內容。
- 版本：checker `c7a4aff63ee91435a522f911e40868ad550019f3ad449264d04ef138639ca6cb`（本輪未改）；治理測試 `0ea3bfda51ed983a078ba045bf8c80a1dcee4041c01692191bad60160aaf4ff5`；PROJECT_CHECKS `eaafee65482dfc2550c270379a0d4c35017aa61472132acdf0fd3a439067db13`；契約快照 `b9512b51b6d8c2977add4ba9758efddcc49e1f052ed124275a5aa4cfe24efc03`（未變）。三站逐位元組一致。
- 證據：C:\Project\tmp\invoiceguard-claude-governance-r2-20261023（r2-results.json、controls-*.json、mutants-*.json、r1-results.json、f2-*.json、gap-proof.json、f1-*.json、f3-before／f3-after、copies-results.json、final-audit*.json、checkers、scripts、baseline）。

## 2026-10-23 Codex：R1／R2、T1／F3-c 最新版完整獨立驗收

本節使用目前磁碟來源重新執行，沒有以 Claude 的 JSON 或前輪測試當成本輪結果。未發現需要新增修正的專案缺陷；Claude 的 T1 回歸測試與 F3-c 診斷修正均有效。本輪專案內僅追加三站 TEST_REPORT.md／REVIEW_FIX_LOG.md，共 6 檔。

### 執行環境與完整測試

Windows／既有三站 Python 3.12 venv；子程序使用 OS 環境白名單，沒有承接公司設定。使用 -B、PYTHONDONTWRITEBYTECODE=1、pytest -p no:cacheprovider；TEMP/TMP/basetemp、JUnit、日誌及合成突變來源全部置於 C:/Project/tmp/invoiceguard-full-acceptance-t1-20261023-01。

| Repository | 實際三站完整 pytest | 固定名單站副本 | 改名單站副本 |
|---|---|---|---|
| InvoiceGuard-AI | 332 passed / 54 skipped | 331 passed / 55 skipped | 331 passed / 55 skipped |
| InvoiceGuard-AI-ADMIN | 433 passed / 9 skipped | 432 passed / 10 skipped | 432 passed / 10 skipped |
| InvoiceGuard-AI-API | 428 passed / 14 skipped | 427 passed / 15 skipped | 427 passed / 15 skipped |

以上 9 份完整 pytest 均 exit 0。三站 checker、Ruff check/format、完整 --project-root 跨站檢查與 UI 兩站 djLint 均 exit 0；模板各 14 份。原三站完整跨站測試實際執行通過。每站完整 pytest 仍只有既有 Starlette/httpx 淘汰警告。

六份副本分置獨立父目錄，固定名稱／小寫加 -clone 各一份，不含 .git、venv、.env、預存快取或兄弟站，以各站原 venv 執行。APP_NAME 角色識別、單站 checker、他處絕對路徑 -I -B -X utf8 均通過；缺兄弟的完整跨站測試明確 skipped，明確 --project-root 則 exit 1 並回報 peer_missing（固定名 2 筆、改名 3 筆）。略過包含站別不適用、單站缺兄弟及 symlink 權限不足，不計為通過。

### R1／R2、F1–F3 與 F2-b／F3-b

- R1：完全合成模組在隔離 Python 實際匯入，if／try／頂層星號匯入都替換 Entry；現版摘要三種皆變。重跑歷史控制並核對 checker 雜湊：修正前只能抓頂層；舊版回歸測試後端各 5 failed/1 passed、前台 2 failed/1 passed/3 skipped（預期），現版由完整測試驗證。
- R2：獨立建立 29 種合成模組並逐一實際匯入。6 種只讀 global 的物件與摘要均不變，23 種賦值、增量／解構、刪除、import、class/def/async、except、match/capture/star/rest、for/with、海象、巢狀與 class global／屬性／索引寫入均確實改寫或刪除，摘要均變。舊 F2-b checker 對 6 種只讀全部誤報，現版 0 個非預期。ADMIN/API 各 10 個專案來源副本案例（只讀 helper 與真改寫）亦符合預期。舊版回歸控制後端各 4 failed/5 passed、前台 2 failed/5 passed/2 skipped；本次選取 9 例，包含 T1 新增的 except/match 2 例，因此不沿用先前 7 例的數字。
- F1：每站 14 種配置，13 符合預期、1 symlink 因 WinError 1314 明確 skip。可匯入負例先以合成來源編譯，再在隔離子程序實際 import：一般／套件 init／巢狀／舊式／大寫目錄 bytecode 與藏於快取的 .py 均被拒絕。正常 opt-0/1/2 及 compileall 快取通過，無來源／舊式配置拒絕；未讀取或執行既有 .pyc 內容。
- F2／F2-b：ADMIN/API 各 22 個重新綁定與無關變更控制皆符合預期。另 11 種藏在無關定義的改寫經合成模組實際匯入確認、摘要皆變；7 種只讀／無關控制保持不變。兩站各 5 個來源副本負例都產生 contract_drift；R1 舊版會漏判。外部舊版回歸控制後端各 15 failed/1 passed、前台 10 failed/1 passed/5 skipped（預期）。
- F3／F3-b：三站、父程序 PYTHONUTF8=0/1、ASCII／中文 TEMP/basetemp 共 12 組，每組 3 passed。AST 確認兩個目標函式保留 -I -X utf8、encoding='utf-8'，不使用 errors= 忽略或替換。外部故意讓第一輪 checker 與合成 bytecode 匯入拋中文 RuntimeError：每站兩種模式各 3 failed（預期），兩則訊息皆為獨立 E 行，沒有解碼錯誤。只附 stdout 控制會遺失 checker 診斷；移除 UTF-8 保護控制會重現 UnicodeDecodeError／TypeError。

### T1：九種突變與舊測試控制

只在外部來源副本修改 checker，先確認每個改動語法有效、替換位置唯一；每個突變執行整份 test_project_governance.py，使用 JUnit 確認失敗為 assertion 且來自對應回歸案例，排除其他錯誤。每份副本先跑未突變控制，全部 exit 0。三站各 9/9 被測試抓到，共 27/27；並非單看非零結束碼。

突變涵蓋：M1 移除 MatchStar、M2 移除 mapping rest、M3 global 忽略 except/match 字串綁定、M4 還原只讀 global 誤報、M5 完全忽略 global、M6 忽略 Store/Del、M7 移除 except as、M8 移除 match capture、M9 移除條件式星號匯入保護。另取前輪保存且雜湊吻合的 API 舊測試做同樣 9 個控制：M1–M3 確實存活，其他 6 個被抓到；最新版全部抓到，重現 T1 修補前後的差異。

### F3-c：第二次執行崩潰的失敗診斷

每站外部副本的 checker 只在測試第二次建立 app/unapproved_layer 時拋中文 RuntimeError，第一次仍通過。未捕捉例外同樣 exit 1，所以測試在 source_location 斷言失敗；本輪確認失敗點正確。三站 × PYTHONUTF8=0/1 × ASCII／中文路徑共 12 組，每組 1 failed/2 passed（預期），中文訊息全部獨立顯示為 E 行，無 UnicodeDecodeError／TypeError。移除第二個斷言診斷的 3 站控制均重現訊息不再獨立顯示。正常 3 案例仍由上述 F3 驗證通過；故意失敗的控制不計入正式測試失敗。

### 範圍稽核、證據與未執行項目

保存 branch／HEAD／完整 status／索引 SHA256 與 entries，及明列的非機密追蹤／未追蹤程式、設定中繼檔與文件基準；排除 .env／秘密、ignored runtime／cache／tmp、Git、venv 與未支援二進位檔，不聲稱雜湊覆蓋所有磁碟內容。核對實際測試來源仍吻合基準；三站共用來源／測試／文件與快照逐位元組相同。只更新 6 份報告，checker、契約快照、業務、Schema/ORM、依賴、CI、AGENTS、STARTUP 與其校驗碼完全未動。追加記錄後，重跑三站 checker 及完整跨站檢查均 exit 0。Git branch/HEAD/index/status 保留；git diff --check 與 55 個非機密未追蹤檔空白檢查通過，另有 LF/CRLF 乾淨及故意行尾空白控制。未變更 Git 全域設定。

證據目錄：C:/Project/tmp/invoiceguard-full-acceptance-t1-20261023-01。baseline.json、actual-results.json、copies-results.json、f1/f2/f3-results.json、definitions-results.json、r2-results.json、t1-verified-results.json、f3b-results.json、f3c-results.json 保留命令、結果與控制；final-audit.json、evidence-manifest.json、SHA256SUMS.txt 記錄最終範圍與校驗。歷史對照 checker 和舊測試已與保存基準核對 SHA256，見 historical-versions.json。

驗收器首輪 T1 暫存路徑過長，讓部分 py_compile atomic 暫存檔在 Windows 因路徑而失敗，不能作為突變被抓到的證據。第二次準備未建立 basetemp 父目錄，未突變控制即阻止後續測試。原 t1-mutations/、t1-results.json 與 t1-verified/ 保留但排除最終判定；改用已建立父目錄的短 basetemp，在 t1-verified-v3/ 重新執行全部 36 組突變及 4 組未突變控制，並強制檢查對應 assertion failure。這是外部驗收器條件修正，未改專案程式。

未執行 GitHub 遠端 CI、Linux runner、全新 pip 安裝、需權限的 symlink 負例、真登入／DB／Storage／Vercel。CI 僅本機唯讀解析 YAML，不能視為遠端已通過。靜態規則仍不涵蓋完整反射／作用域／資料流、方法呼叫間接改寫或 bytecode 內容一致性；本輪沒有擴張其保證。未啟服務或 Tunnel，不實作 CRUD/Storage，不部署、不執行 migration/seed、不修改正式資料、不 Commit/Merge/Push；公司密鑰留在雲端。


## 2026-10-23 Claude 獨立驗收：F1-c symlink 誤標、R1／R2、F1–F3、T1 突變、F3-c 與六份 Clone

以磁碟上最新未提交內容為準，全部實際重跑，未以前輪報告或既有 JSON 代替。開始前保存三站 branch／HEAD／完整 status／索引 entries 與索引檔 SHA256，以及檔案雜湊（含非機密未追蹤檔與 `.env.example`；排除 .git、.venv、__pycache__、.pytest_cache、.ruff_cache、tmp/pytest 與 `.env`／其他 `.env.*`，不宣稱涵蓋整個磁碟）。開始時 checker `c7a4aff6…`、治理測試 `0ea3bfda…`、PROJECT_CHECKS `eaafee65…`、契約 `b9512b51…`，與前節紀錄一致。歷史版本先依 historical-versions.json 重新核對：修正前 checker、R1、F2-b 與 T1 前的 API 舊測試全部吻合，目前 R2 checker 也吻合（5／5）。

### 修正前三站完整檢查（短 basetemp，先建立父目錄）

| Repository | check_project | 全套 pytest | 完整跨站測試 | Ruff check／format | djLint | --project-root .. |
|---|---|---|---|---|---|---|
| InvoiceGuard-AI | exit 0 | **332 passed, 54 skipped** | 實際執行 | exit 0／exit 0 | exit 0 | exit 0 |
| InvoiceGuard-AI-ADMIN | exit 0 | **433 passed, 9 skipped** | 實際執行 | exit 0／exit 0 | exit 0 | exit 0 |
| InvoiceGuard-AI-API | exit 0 | **428 passed, 14 skipped** | 實際執行 | exit 0／exit 0 | 不適用 | exit 0 |

與前輪基準 332／54、433／9、428／14 相同。skip 原因只有站別不適用，以及 symlink 權限不足。

### 本輪發現與修正：低 F1-c，symlink 測試把路徑錯誤記成權限不足

- 重現：`test_symlink_in_bytecode_cache_is_rejected` 對任何 OSError 都 skip 並寫「本機未提供建立符號連結的權限」。Windows 在檢查權限前，會先回報路徑過長（WinError 3）或連結已存在（WinError 183）。在專案外副本還原修正前的測試（SHA256 與 `0ea3bfda…` 完全一致），basetemp 長度 150／160（連結 266／276 字元）時，實際錯誤是 `FileNotFoundError winerror=3`，測試卻仍 skip 成權限不足；長度 120 時才是真正的 WinError 1314。
- 原因：`except OSError` 範圍過寬，沒有區分權限不足與其他檔案系統錯誤。
- 修正：新增 `symlink_or_skip`，只有 Windows 1314 或 POSIX EPERM 才 skip，其他 OSError 原樣拋出。新增 `test_symlink_helper_does_not_report_path_errors_as_missing_privilege`（路徑過長、已存在 2 例）與 `test_symlink_helper_skips_only_without_privilege`（EPERM，以及只在 Windows 執行的 1314，共 2 例）。
- 回歸證據：把 helper 改回捕捉所有 OSError，新測試為 2 failed／2 passed（失敗訊息為「路徑或檔案錯誤被誤判為權限不足而 skip」）；修正版 4 passed。修正後 basetemp 150／160 會以 `FileNotFoundError [WinError 3]` 失敗並顯示原因，120 仍是正當的權限 skip。PROJECT_CHECKS 已補註此規則。checker 未修改。

### R1／R2、F2、F2-b（只做 AST 與合成模組，不執行 app）

- R1：合成模組 if／try／頂層星號匯入，在隔離子程序實際把 `Entry` 換成字串；R2 版三種都改變摘要，common／vercel 專案副本 contract_drift，無關明確匯入、無關函式、備註、docstring 不誤報，全部符合預期。現有來源仍等於原快照，未重建快照。
- R2：29 例（6 只讀、23 實際改寫），以物件身分、屬性值與名稱是否刪除判斷，全部符合預期。合成案例非預期：修正前 23、R1 23、F2-b 6（只讀誤報）、R2 0。ADMIN／API common.py 與 vercel.py 專案副本共 20 例，R2 版 20 例符合；F2-b 版重現 8 個只讀誤報。
- F2：API／ADMIN 各 59 例，R2 版非預期 0。
- F2-b：11 種藏在無關頂層定義內的寫法，實際匯入後確實改寫或修改 `Entry`，R2 版摘要全部改變，只讀控制不變；專案代表案例 contract_drift，無關 DTO 子類別不誤報。方法呼叫、反射與完整資料流維持 PROJECT_CHECKS 已揭露的限制。

### F1：快取與來源配置

前台、ADMIN、API 各 13／13 符合預期。可匯入負例（一般 `name.pyc`、`__init__.pyc`、巢狀、大寫 `__PYCACHE__`、來源旁舊式 `.pyc`、快取內 `.py`）都先以合成來源編譯並在隔離子程序實際 import，再確認 checker 拒絕；無來源標籤快取、快取內文字檔、`compileall -b` 拒絕；opt-0／1／2 與乾淨副本整站 compileall 通過。不讀取或執行專案既有 .pyc。symlink 本輪記錄實際錯誤碼：前台 no symlink privilege (OSError winerror=1314 errno=22 link_len=126)；ADMIN no symlink privilege (OSError winerror=1314 errno=22 link_len=138)；API no symlink privilege (OSError winerror=1314 errno=22 link_len=134)，皆明確 **skip，不算通過**，未提升權限。

### F3／F3-b／F3-c

- 靜態：兩個隔離測試保留 `-I` 並有 `-X utf8`，所有 `subprocess.run` 指定 `encoding="utf-8"`，沒有 `errors=`；第二次執行的 returncode 與 source_location 兩個斷言都附 stdout／stderr。
- 正常：三站 × PYTHONUTF8=0／1 × ASCII／中文 TEMP 與 basetemp，共 12 組，每組 3 案例皆 passed。
- F3-b（故意失敗，與正式結果分開）：checker 啟動失敗與合成位元組碼匯入失敗的中文 RuntimeError，12 組中兩則訊息皆為獨立 `E` 行，沒有 UnicodeDecodeError／TypeError。
- F3-c（故意失敗）：checker 只在第二次掃到 `app/unapproved_layer` 時崩潰。12 組中，JUnit 皆顯示失敗是 source_location 斷言那一行的 AssertionError（不是 returncode），中文訊息獨立顯示，沒有解碼錯誤。
- 控制：只附 stdout 時，checker 訊息不再獨立；移除 UTF-8 保護後，重現 UnicodeDecodeError／TypeError；移除第二次斷言的診斷後，訊息只剩截斷 repr。三者都依預期退化，證明檢查分辨得出來。

### T1：九種突變（只改專案外副本）

每份副本先跑未突變控制（全部通過），每個突變都確認替換位置唯一、可通過 `ast.parse` 與 `compile`，再跑整份 test_project_governance.py 並解析 JUnit。只有「對應回歸案例出現 assertion failure、指定的參數案例有命中、沒有 error 或收集錯誤」才算抓到。最新版：前台 9／9、ADMIN 9／9、API 9／9。

以 SHA256 吻合的 T1 前 API 舊測試做控制：M1、M2、M3 存活，M4、M5、M6、M7、M8、M9 被抓到，重現 T1 補測前的缺口。驗收器首次判定時，把 T1 新增參數的名稱當成 M7／M8 的必要案例，舊測試沒有這些參數，因此誤判為 INVALID。改依實際案例（except as／match 擷取）重新判讀同一批 JUnit 後結果如上；這是驗收器條件錯誤，不是專案缺陷，原始輸出保留。

### 六份隔離副本（最新工作區來源，各自獨立父目錄）

複製 Git 追蹤及未忽略的未追蹤檔，從磁碟讀取，所以含未提交修改；逐檔與工作區比對 SHA256，必要的 AGENTS／CLAUDE、契約、scripts、設定中繼檔與規範文件都在，且沒有 .git、.venv、.env、快取或兄弟站，全部符合。

| 副本 | 角色（APP_NAME） | 檔案數 | 單站 checker | 他處 -I -B -X utf8 | 完整跨站測試 | 明確 --project-root | 全套 pytest |
|---|---|---|---|---|---|---|---|
| 前台 固定名（`InvoiceGuard-AI`） | InvoiceGuard-AI | 91（未追蹤 24） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 2） | 335 passed, 55 skipped |
| 前台 改名（`invoiceguard-ai-renamed-clone`） | InvoiceGuard-AI | 91（未追蹤 24） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 3） | 335 passed, 55 skipped |
| ADMIN 固定名（`InvoiceGuard-AI-ADMIN`） | InvoiceGuard-AI-ADMIN | 119（未追蹤 16） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 2） | 436 passed, 10 skipped |
| ADMIN 改名（`invoiceguard-ai-admin-renamed-clone`） | InvoiceGuard-AI-ADMIN | 119（未追蹤 16） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 3） | 436 passed, 10 skipped |
| API 固定名（`InvoiceGuard-AI-API`） | InvoiceGuard-AI-API | 106（未追蹤 15） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 2） | 431 passed, 15 skipped |
| API 改名（`invoiceguard-ai-api-renamed-clone`） | InvoiceGuard-AI-API | 106（未追蹤 15） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 3） | 431 passed, 15 skipped |

### 修正後三站完整檢查

| Repository | check_project | 全套 pytest | 完整跨站測試 | Ruff check／format | djLint | --project-root .. |
|---|---|---|---|---|---|---|
| InvoiceGuard-AI | exit 0 | **336 passed, 54 skipped** | 實際執行 | exit 0／exit 0 | exit 0 | exit 0 |
| InvoiceGuard-AI-ADMIN | exit 0 | **437 passed, 9 skipped** | 實際執行 | exit 0／exit 0 | exit 0 | exit 0 |
| InvoiceGuard-AI-API | exit 0 | **432 passed, 14 skipped** | 實際執行 | exit 0／exit 0 | 不適用 | exit 0 |

與前輪基準相比，三站各多 4 passed，是 F1-c 新增的 4 個 helper 測試（其中 1314 案例只在 Windows 執行；Linux 上會是 3 passed／1 skipped，尚未實測）。副本多 1 個 skip，是缺兄弟站的完整跨站測試。skip 不計為通過；每站仍只有既有 Starlette／httpx 淘汰警告。

### CI、未驗證與限制

- CI 僅本機唯讀檢查，工作流程未改：單站 checkout、persist-credentials: false、Python 3.12、ubuntu／windows matrix、contents: read；沒有 secrets、pull_request_target、部署或 migration。
- **未執行**：GitHub 遠端 CI、Linux runner、全新 pip 安裝、有權限時的 symlink 真負例、真登入／DB／Storage／Vercel。未啟動服務或 Tunnel。
- 限制：靜態分析不涵蓋反射、方法呼叫間接修改與完整作用域／資料流；快取檢查不驗證位元組碼內容。
- 驗收器備註：STARTUP 的 SHA256SUMS.txt 是 CRLF 行尾，GNU `sha256sum -c` 直接讀取會把 CR 當成檔名一部分而全數「讀取失敗」；改為只在讀取時去除 CR 後驗證通過，檔案本身未修改。基準掃描時 ADMIN／API 的 tmp/pytest 無法讀取，該目錄本就在排除範圍內。ADMIN／API 的 app/ 內有 2026-10-22 即存在的既有 `__pycache__`（45／32 個 .pyc，皆早於本輪基準，非本輪產生）；本輪未讀取、執行或刪除，checker 視為有來源的標準快取。
- 版本：checker `c7a4aff63ee91435a522f911e40868ad550019f3ad449264d04ef138639ca6cb`（未改）；治理測試 `523d2b8c93900a8645dcb7916eeb79fcb8a6d6896796dd05eca3391027178b13`；PROJECT_CHECKS `8525b85dd16612f0a3cdafcd45ca4dde49290d106ce6f29b305ff180484a6d19`；契約 `b9512b51b6d8c2977add4ba9758efddcc49e1f052ed124275a5aa4cfe24efc03`（未變）。三站逐位元組一致。
- 證據：C:\Project\tmp\invoiceguard-claude-acceptance-r6-20261023（baseline；full：修正前後完整檢查的 JSON、JUnit 與日誌；historical-check.json；probes：r1／r2／f2／gap 與 f1；f3：矩陣結果、JUnit 與日誌；m：突變 JUnit、日誌與 m78-rejudge.json；sym：F1-c 重現與控制；cl：六份副本；checkers：歷史 checker 與舊測試；final-audit.json；scripts；SHA256SUMS.txt）。

## 2026-10-23 Codex：F1-c 修正後最新版完整獨立驗收

實際重新執行三站完整測試、F1-c、R1/R2、F1–F3、F2-b/F3-b、T1 與 F3-c，以及六份單站／改名副本。沒有以 Claude 的結果或前輪 JSON 當作本輪通過證據。未發現本輪範圍內需要新增修正的專案缺陷；F1-c 修正有效，本輪專案僅追加三站各自 TEST_REPORT／REVIEW_FIX_LOG，共 6 檔。

### 環境、完整結果與六份副本

Windows、原三站 Python 3.12 venv；測試子程序只使用 OS 環境白名單，不承接公司設定。使用 -B、PYTHONDONTWRITEBYTECODE=1、pytest -p no:cacheprovider，TEMP/TMP/basetemp/JUnit/日誌均在專案外。本輪使用短暫存路徑並預先建立父目錄。

| Repository | 原三站完整 pytest | 固定名單站副本 | 改名單站副本 |
|---|---|---|---|
| InvoiceGuard-AI | 336 passed / 54 skipped | 335 passed / 55 skipped | 335 passed / 55 skipped |
| InvoiceGuard-AI-ADMIN | 437 passed / 9 skipped | 436 passed / 10 skipped | 436 passed / 10 skipped |
| InvoiceGuard-AI-API | 432 passed / 14 skipped | 431 passed / 15 skipped | 431 passed / 15 skipped |

以上全部 exit 0。每站比前輪多 4 passed，為 F1-c 的 2 個路徑錯誤負例與 2 個權限正例。三站 checker、Ruff check/format、UI 兩站各 14 份模板 djLint，以及明確 --project-root 完整跨站檢查全部 exit 0。三站齊全時完整跨站測試實際執行通過；每站完整 pytest 仍只有既有 Starlette/httpx 淘汰警告。

六份最終副本為最新非機密工作區來源，固定名／小寫加 -clone 各一份、分置獨立父目錄，含必要未追蹤檔及公開 .env.example，不含實際 .env、.git、venv 或預存快取。每份所有列入副本建立時基準的來源檔均逐位元組核對相符，tested-copy-baseline.json 保存此版本；其後僅有驗收紀錄補充，所測程式／測試未改。APP_NAME 角色識別、單站 checker、他處絕對路徑 -I -B -X utf8 均通過；缺兄弟的完整跨站案例明確 skip。明確指定 --project-root 時均 exit 1 並有 peer_missing（固定名 2 筆、改名 3 筆）。skip 是站別不適用、缺兄弟或真實 symlink 權限不足，未計入通過。

### F1-c：錯誤分類、真實 Windows 與新舊控制

- 三站各以 AST 單獨載入 symlink_or_skip，不 import 應用程式。10 種錯誤分類皆符合預期：ENOENT、EEXIST、ENAMETOOLONG、EINVAL、EIO、EACCES、Windows 3/206 都原樣拋出；EPERM 與 Windows 1314 才 skip。非權限錯誤另確認為同一例外物件。
- 真實 Windows：三站短連結皆為 WinError 1314，helper 明確 skip；已存在目標實際 WinError 183，helper 原樣失敗；275 字元連結實際 WinError 3，helper 原樣失敗。沒有把路徑錯誤當成缺權限。
- 各站實際 symlink 治理測試：basetemp 長度 120 為真正權限 skip；150/160 各 1 failed/0 skipped，錯誤為 FileNotFoundError [WinError 3]，堆疊確認到 symlink_or_skip(target, outside)。這些是故意長路徑的預期失敗控制，不計為正常測試失敗。
- 各站最新 helper 回歸 4 passed；外部副本還原捕捉所有 OSError 的舊行為後，各 2 failed/2 passed，兩個失敗均為路徑錯誤負例。證明新增測試能抓到退化，沒有放寬測試或改 checker／快照。

### R1/R2、F1–F3、T1 與 F3-c

- R1：合成模組的頂層／if／try 星號匯入實際替換 Entry，現版摘要皆變。歷史版本與保存基準 SHA256 相符；修正前只抓到頂層。舊版控制後端各 5 failed/1 passed、前台 2 failed/1 passed/3 skipped（預期），現版完整測試通過。
- R2：29 個合成模組實際匯入，6 種只讀 global 物件與摘要不變，23 種真實寫入／綁定／刪除或物件修改均被偵測。舊 F2-b checker 重現 6 種只讀誤報，現版 0 個非預期。ADMIN/API 各 10 個來源副本案例符合預期。9 個既有回歸的舊版控制後端各 4 failed/5 passed，前台 2 failed/5 passed/2 skipped；含 T1 新增 except/match，不沿用更早 7 例的計數。
- F1：每站 14 種配置，13 符合預期、1 真實 WinError 1314 skip。可 import 的負例先由合成來源編譯並在隔離子程序證明可匯入，再確認拒絕。正常 opt-0/1/2 與 compileall 通過；一般／init／巢狀／舊式／大寫目錄 bytecode、無來源快取、快取中的 .py／文字皆拒絕。未執行既有 .pyc。
- F2/F2-b：ADMIN/API 各 22 個改寫／無關控制符合預期；另 11 種藏在無關定義的實際改寫全部被抓到、7 個只讀／無關控制不誤報。兩站各 5 個來源副本改寫皆產生 contract_drift，R1 舊版漏判。歷史回歸控制後端各 15 failed/1 passed、前台 10 failed/1 passed/5 skipped（預期）。
- F3/F3-b：三站 × PYTHONUTF8=0/1 × ASCII/中文 TEMP/basetemp，共 12 組正常測試，每組 3 passed。AST 確認隔離命令 -I -X utf8 與 encoding='utf-8'，無 errors= 忽略或替換。首輪 checker／合成匯入注入中文 RuntimeError 時，每站兩模式各 3 failed（預期），中文訊息獨立 E 行可讀。只附 stdout 與移除編碼保護的控制均重現退化／解碼錯誤。
- T1：四份副本（新版三站及 API 舊測試）先跑整份未突變治理測試全部通過。九種突變為移除 MatchStar、mapping rest、global except/match、還原只讀 global 誤報、忽略 global、忽略 Store/Del、移除 except as、match capture、條件式星號匯入。各突變語法有效、替換位置唯一；新版三站各 9/9 被抓到，共 27/27。JUnit 確認對應案例 assertion failure，且沒有其他例外或收集錯誤；不只看非零結束碼。保存且雜湊吻合的 API 舊測試重現 M1–M3 存活、其餘 6 種被抓到。
- F3-c：只讓第二次掃到 app/unapproved_layer 時拋中文 RuntimeError，第一次正常。三站 × 兩模式 × 兩種路徑，共 12 組各 1 failed/2 passed（預期），確認因 exit 1 的第一個判斷仍通過、實際失敗落在 source_location 斷言，中文訊息獨立成行且無解碼錯誤。兩個第二次執行斷言均有 stdout/stderr；移除第二個診斷的三站控制皆重現退化。故意失敗控制與正常測試分開記錄。

### 基準、執行期間文件更新與最終稽核

保存初始 branch/HEAD/status/index SHA256/entries，以及明列非機密追蹤／未追蹤來源與 STARTUP 檔案雜湊。公開 .env.example 另行明確補入基準，初始基準保留；實際 .env／秘密、Git、venv、ignored runtime/cache/tmp 及未支援二進位檔不讀取或納入，不宣稱覆蓋全部磁碟。

Claude 在本輪執行期間完成前輪六份報告追加，複製防護偵測到差異並安全中止一組副本準備及部分歷史控制；核對只有這六份報告改變，程式與 Git 均不變，保留原始及更新後基準、未覆寫 Claude 紀錄。以最新既有報告和公開範本重新建立六份副本、重跑全部副本完整測試及整組歷史控制；最終採 copies-final-results.json／definitions-results.json。較早結果及中止副本保留，不當最終證據。寫入前防護又偵測到三站 TEST_REPORT 的補充而阻止寫入；確認至少 20 秒穩定且只有紀錄變更後，分開保存副本測試基準與最後追加基準，接續最新內容。未變動的程式不重複測試，寫入後另重跑 checker／跨站檢查。

本輪只追加三站各兩份紀錄，沒有更改 checker、治理測試、PROJECT_CHECKS、契約快照、AGENTS、CI、依賴、業務／Schema/ORM、STARTUP 或其 SHA256SUMS。Git branch/HEAD/index/status 保留。追蹤與非機密未追蹤檔的空白檢查通過，具 LF/CRLF 乾淨與故意行尾空白控制；未改 Git 全域設定。報告寫入後三站 checker 與完整跨站檢查重跑通過。

STARTUP 原校驗清單只在讀取時以 splitlines 去除 CRLF，逐筆確認路徑在 STARTUP 內、檔案存在與 SHA256 相符；沒有改動原始清單或換行。外部證據另存 SHA256SUMS，使用 PowerShell 再核對。

證據：C:/Project/tmp/ig-accept-f1c-20261023-01。actual-results、copies-final-results、f1c/f1/f2/f3-results、definitions-results、r2-results、t1-verified-results、f3b/f3c-results.json 記錄實際命令與結果；historical-versions、public-template-extension、peer-report-refresh、copy-source-audit、startup-manifest-check、final-audit、evidence-manifest 與 SHA256SUMS 保留版本／範圍證據。failed 控制為明確的預期結果，不算成正式測試通過或未解決失敗。

未執行遠端 GitHub CI、Linux runner、全新 pip 安裝、有建立權限的 symlink 真負例、真登入/DB/Storage/Vercel。CI 只本機靜態解析，不視為遠端通過；既有反射／完整作用域及資料流／方法間接改寫／bytecode 內容等限制不擴張。本輪不啟服務/Tunnel、不實作 CRUD/Storage、不部署、不執行 migration/seed、不修改正式資料、不 Commit/Merge/Push；公司密鑰留雲端。

- scripts/check_project.py SHA256：`c7a4aff63ee91435a522f911e40868ad550019f3ad449264d04ef138639ca6cb`
- tests/unit/test_project_governance.py SHA256：`523d2b8c93900a8645dcb7916eeb79fcb8a6d6896796dd05eca3391027178b13`
- contracts/project-contract.json SHA256：`b9512b51b6d8c2977add4ba9758efddcc49e1f052ed124275a5aa4cfe24efc03`


## 2026-10-23 Claude 獨立驗收：F1-d helper 回歸補強、F1-c、R1／R2、F1–F3、T1 與六份 Clone

以磁碟上最新未提交內容為準，全部實際重跑，未以 Codex 或前輪報告代替。開始前保存三站 branch／HEAD／完整 status／索引 entries 與索引檔 SHA256，以及檔案雜湊；公開範本 `.env.example` 納入雜湊與副本，實際 `.env`／其他 `.env.*`、.git、.venv、各種快取與 tmp/pytest 排除，不宣稱涵蓋整個磁碟。開始時 checker `c7a4aff6…`、治理測試 `523d2b8c…`、PROJECT_CHECKS `8525b85d…`、契約 `b9512b51…`，與前節紀錄一致；本輪執行期間沒有其他工具改動程式或測試。歷史 checker 與 T1 前舊測試依 historical-versions.json 重新核對 SHA256，全部吻合（5／5）。

### 修正前三站完整檢查

| Repository | check_project | 全套 pytest | 完整跨站測試 | Ruff check／format | djLint | --project-root .. |
|---|---|---|---|---|---|---|
| InvoiceGuard-AI | exit 0 | **336 passed, 54 skipped** | 實際執行 | exit 0／exit 0 | exit 0 | exit 0 |
| InvoiceGuard-AI-ADMIN | exit 0 | **437 passed, 9 skipped** | 實際執行 | exit 0／exit 0 | exit 0 | exit 0 |
| InvoiceGuard-AI-API | exit 0 | **432 passed, 14 skipped** | 實際執行 | exit 0／exit 0 | 不適用 | exit 0 |

與前輪基準 336／54、437／9、432／14 相同。skip 原因只有站別不適用與真實 WinError 1314。

### F1-c：symlink_or_skip 獨立驗證

- 分類：三站各自從測試檔以 AST 單獨取出 helper（不 import 應用程式），以替身連結拋出 10 種錯誤：ENOENT、EEXIST、ENAMETOOLONG、EINVAL、EIO、EACCES、Windows 3／206 原樣拋出，且確認是同一個例外物件；只有 EPERM 與 Windows 1314 才 skip，全部符合預期。另查 Python 3.12 的 winerror 對 errno 對照，沒有任何 Windows 錯誤碼會被轉成 EPERM。
- 真實 Windows：短連結實際為 `OSError winerror=1314 errno=22`，helper 明確 skip；連結名稱已存在為 `FileExistsError winerror=183 errno=17`，helper 原樣拋出；父目錄存在、連結路徑 271 字元為 `FileNotFoundError winerror=3 errno=2`，helper 原樣拋出。
- 刻意長 basetemp（三站外部副本）：長度 120 是真正的權限 skip；150／160 以 `FileNotFoundError [WinError 3]` 失敗，JUnit 堆疊確實到達 `symlink_or_skip(target, outside)` 與 `link.symlink_to(target)`，不是其他準備步驟失敗。
- 既有 4 個回歸案例：新版三站皆 4 passed；外部副本還原「捕捉所有 OSError 都 skip」後，三站皆 2 failed／2 passed，失敗的都是兩個路徑負例。
- 本機沒有建立 symlink 的權限，checker 拒絕真實 symlink 的負例 **未驗證**（不算通過）。

### 本輪發現與修正：低 F1-d，helper 回歸測試範圍太窄

- 重現：在三站專案外副本對 helper 做較細的突變，現有 4 個回歸案例全部通過、突變存活：H2 re-raise only ENOENT/EEXIST、H3 treat EINVAL as missing privilege、H4 wrap in a new exception。
- 原因：負例只有 ENOENT、EEXIST，而且只檢查例外型別，沒有檢查是不是同一個例外物件。
- 修正：路徑錯誤負例擴充為 ENOENT、EEXIST、ENAMETOOLONG、EINVAL、EIO、EACCES、WinError 3、WinError 206 共 8 例（加上可讀的案例 ID），並斷言拋出的就是原本的例外物件。PROJECT_CHECKS 同步補註。checker 未修改。
- 回歸證據：修正後三站 helper 測試皆 10 passed；H1–H4 四種 helper 突變在三站全部被抓到（12／12）。還原捕捉所有 OSError 時，補強後三站皆 8 failed／2 passed，兩個權限正例仍通過。

### R1／R2、F2、F2-b（只做 AST 與合成模組，不執行 app）

- R1：合成模組 if／try／頂層星號匯入，在隔離子程序實際把 `Entry` 換成字串；R2 版三種都改變摘要，common／vercel 專案副本 contract_drift，無關明確匯入、無關函式、備註、docstring 不誤報，全部符合預期；現有來源仍等於原快照，未重建快照。
- R2：29 例（6 只讀、23 實際改寫），以物件身分、內容與名稱是否刪除判斷，全部符合預期。合成案例非預期：修正前 23、R1 23、F2-b 6（只讀誤報）、R2 0。ADMIN／API common.py 與 vercel.py 專案副本 20 例，R2 版 20 例符合；F2-b 版重現 8 個只讀誤報。
- F2：API／ADMIN 各 59 例，R2 版非預期 0。
- F2-b：11 種藏在無關頂層定義內的寫法，實際匯入後確實改寫或修改 `Entry`，R2 版摘要全部改變、只讀控制不變；專案代表案例 contract_drift，無關 DTO 子類別不誤報。未擴張成反射、作用域或資料流分析。

### F1：快取與來源配置

前台、ADMIN、API 各 13／13 符合預期。可匯入負例都先以合成來源編譯並在隔離子程序實際 import，再確認 checker 拒絕；opt-0／1／2 與乾淨副本 compileall 通過；不讀取或執行專案既有 .pyc。symlink 案例實際錯誤為 WinError 1314，明確 **skip，不算通過**。

### F3／F3-b／F3-c

- 靜態：兩個隔離測試保留 `-I -X utf8`，所有 `subprocess.run` 指定 `encoding="utf-8"`，沒有 `errors=`；第二次執行的 returncode 與 source_location 斷言都附 stdout／stderr。
- 正常：三站 × PYTHONUTF8=0／1 × ASCII／中文 TEMP 與 basetemp，共 12 組，每組 3 案例皆 passed。
- F3-b（故意失敗，與正式結果分開）：首輪 checker 啟動失敗與合成位元組碼匯入失敗的中文 RuntimeError，12 組皆以獨立 `E` 行顯示，沒有解碼錯誤。
- F3-c（故意失敗）：checker 只在第二次掃到 `app/unapproved_layer` 時崩潰；12 組 JUnit 皆顯示失敗在 source_location 斷言行，中文訊息獨立顯示，沒有解碼錯誤。
- 控制：只附 stdout、移除 UTF-8 保護、移除第二次斷言診斷，三者皆依預期退化。

### T1：九種突變

只改專案外副本。每份先跑未突變控制（全部通過），每個突變確認替換位置唯一並通過 `ast.parse`／`compile`，跑整份 test_project_governance.py 並解析 JUnit：必須是預期回歸測試中的 assertion failure、指定類型的案例有命中，且沒有 error 或收集錯誤。新版：前台 9／9、ADMIN 9／9、API 9／9。

T1 前 API 舊測試（SHA256 吻合）：M1、M2、M3 存活，M4、M5、M6、M7、M8、M9 被抓到。本輪 M7／M8 的必要案例改用新舊版本通用的判定（任何 except as 綁定案例、任何 match 擷取案例），所以舊測試由其原本的 `except ValueError as reject_bool_and_float`、`case PageQuery:` 案例判定，不再需要事後重新判讀。

### 六份隔離副本（最新工作區來源，各自獨立父目錄）

逐檔與工作區比對 SHA256；包含 AGENTS／CLAUDE、文件、契約、scripts、CI、設定中繼檔與公開 `.env.example`，沒有實際 .env、.git、.venv、快取或兄弟站，全部符合。

| 副本 | 角色（APP_NAME） | 檔案數 | 單站 checker | 他處 -I -B -X utf8 | 完整跨站測試 | 明確 --project-root | 全套 pytest |
|---|---|---|---|---|---|---|---|
| 前台 固定名（`InvoiceGuard-AI`） | InvoiceGuard-AI | 91（未追蹤 24） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 2） | 341 passed, 55 skipped |
| 前台 改名（`invoiceguard-ai-renamed-clone`） | InvoiceGuard-AI | 91（未追蹤 24） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 3） | 341 passed, 55 skipped |
| ADMIN 固定名（`InvoiceGuard-AI-ADMIN`） | InvoiceGuard-AI-ADMIN | 119（未追蹤 16） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 2） | 442 passed, 10 skipped |
| ADMIN 改名（`invoiceguard-ai-admin-renamed-clone`） | InvoiceGuard-AI-ADMIN | 119（未追蹤 16） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 3） | 442 passed, 10 skipped |
| API 固定名（`InvoiceGuard-AI-API`） | InvoiceGuard-AI-API | 106（未追蹤 15） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 2） | 437 passed, 15 skipped |
| API 改名（`invoiceguard-ai-api-renamed-clone`） | InvoiceGuard-AI-API | 106（未追蹤 15） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 3） | 437 passed, 15 skipped |

### 修正後三站完整檢查

| Repository | check_project | 全套 pytest | 完整跨站測試 | Ruff check／format | djLint | --project-root .. |
|---|---|---|---|---|---|---|
| InvoiceGuard-AI | exit 0 | **342 passed, 54 skipped** | 實際執行 | exit 0／exit 0 | exit 0 | exit 0 |
| InvoiceGuard-AI-ADMIN | exit 0 | **443 passed, 9 skipped** | 實際執行 | exit 0／exit 0 | exit 0 | exit 0 |
| InvoiceGuard-AI-API | exit 0 | **438 passed, 14 skipped** | 實際執行 | exit 0／exit 0 | 不適用 | exit 0 |

與前輪基準相比，三站各多 6 passed，就是 F1-d 新增的 6 個負例。副本多 1 個 skip，是缺兄弟站的完整跨站測試。skip 不計為通過；每站仍只有既有 Starlette／httpx 淘汰警告。

### CI、未驗證與限制

- CI 僅本機唯讀檢查，工作流程未改：單站 checkout、persist-credentials: false、Python 3.12、ubuntu／windows matrix、contents: read；沒有 secrets、pull_request_target、部署或 migration。
- **未執行**：GitHub 遠端 CI、Linux runner（包括 1314 案例在 Linux 會 skip 的計數）、全新 pip 安裝、有權限時 checker 拒絕真實 symlink 的負例、真登入／DB／Storage／Vercel。未啟動服務或 Tunnel。
- 限制：靜態分析不涵蓋反射、方法呼叫間接修改與完整作用域／資料流；快取檢查不驗證位元組碼內容。STARTUP 的 SHA256SUMS.txt 只在讀取時去除 CR 後驗證，原檔未修改。ADMIN／API 的 app/ 內 2026-10-22 既有的 `__pycache__` 未讀取、執行或刪除。
- 版本：checker `c7a4aff63ee91435a522f911e40868ad550019f3ad449264d04ef138639ca6cb`（未改）；治理測試 `254b421ab27a53e5676e09d1dcbf61d88ee5ba063a6d8f650ed9a3a24afccec1`；PROJECT_CHECKS `4f86c1c6cfb368a4f3ed5d0acb0e316c0a16ab2add7f9cc60149e9f267750250`；契約 `b9512b51b6d8c2977add4ba9758efddcc49e1f052ed124275a5aa4cfe24efc03`（未變）。三站逐位元組一致。
- 證據：C:\Project\tmp\invoiceguard-claude-acceptance-r7-20261023（baseline；full：修正前後完整檢查 JSON、JUnit、日誌；historical-check.json；f1c／f1c-after：分類、真實 Windows、回歸、helper 突變與長路徑；probes：r1／r2／f2／gap 與 f1；f3：矩陣結果、JUnit、日誌；m：突變 JUnit 與日誌；cl：六份副本；checkers；final-audit.json；scripts；SHA256SUMS.txt）。

## 2026-10-23 Codex：F1-c／F1-d、H1–H4 最新版完整獨立驗收

本節實際重跑目前磁碟最新版，不沿用 Claude 或前輪結果。未發現本輪範圍內需新增修正的專案缺陷。F1-d 的六個新增負例與例外物件身分斷言有效；helper、checker 及快照不需更改。本輪專案只追加三站各自 TEST_REPORT／REVIEW_FIX_LOG，共 6 檔。

### 執行環境與完整結果

Windows、各站原有 Python 3.12 venv；子程序使用 OS 環境白名單，不承接公司設定。使用 -B、PYTHONDONTWRITEBYTECODE=1、pytest -p no:cacheprovider，TEMP/TMP/basetemp、JUnit、日誌與突變皆在 C:/Project/tmp/ig-accept-f1d-20261023-01；使用預建父目錄的短暫存路徑。

| Repository | 三站完整 pytest | 固定名副本 | 改名副本 |
|---|---|---|---|
| InvoiceGuard-AI | 342 passed / 54 skipped | 341 passed / 55 skipped | 341 passed / 55 skipped |
| InvoiceGuard-AI-ADMIN | 443 passed / 9 skipped | 442 passed / 10 skipped | 442 passed / 10 skipped |
| InvoiceGuard-AI-API | 438 passed / 14 skipped | 437 passed / 15 skipped | 437 passed / 15 skipped |

以上均 exit 0，三站數量與 Claude F1-d 報告一致，比 F1-c 舊版各多 6 passed。三站 checker、Ruff check/format（app/tests/scripts）、UI 兩站各 14 份模板 djLint、明確 --project-root 完整跨站檢查全部 exit 0；三站齊全時完整跨站測試實際執行。每站完整 pytest 仍只有既有 Starlette/httpx 淘汰警告。skip 不算通過。

六份來源副本固定名／小寫加 -clone 各一份、分置獨立父目錄，包含非機密未追蹤檔及公開 .env.example，不含實際 .env、.git、venv、預存快取或兄弟站。與建立時基準逐檔核對 SHA256；APP_NAME 角色識別、單站 checker、他處絕對路徑 -I -B -X utf8、完整 pytest 全部通過。缺兄弟時完整跨站案例明確 skip，明確 --project-root 則 exit 1 並回報 peer_missing（固定名 2 筆、改名 3 筆）。略過包含站別不適用、單站缺兄弟及真實 symlink 權限不足。

### F1-c／F1-d 與 H1–H4 新舊證據

三站逐一以 AST 單獨載入 helper，不 import 應用程式；10 種合成錯誤分類均符合預期。ENOENT、EEXIST、ENAMETOOLONG、EINVAL、EIO、EACCES、Windows 3/206 都原樣拋出同一例外物件，只有 EPERM／1314 skip。真實 Windows 短連結為 1314（skip），既有檔案為 183、275 字元長路徑為 3（原樣拋出）。實際 symlink 治理測試 basetemp 120 為權限 skip，150/160 則各 1 failed/0 skipped，以 WinError 3 失敗，堆疊確認到 symlink_or_skip(target, outside)，不是其他準備步驟。刻意失敗控制與正常測試分開記錄。

保存版本的五份歷史 checker／測試均重新與原基準完整 SHA256 核對，包含 F1-d 前測試 523d2b8c…。確認舊／新 helper AST 完全相同，變更僅為測試補強。每站分別對新版十例與歷史四例跑相同 H1–H4，且先跑未突變控制：

| helper 版本與測試 | 未突變 | H1 捕捉全部 | H2 只重拋 ENOENT/EEXIST | H3 EINVAL 當權限 | H4 重包例外 |
|---|---|---|---|---|---|
| 新版十例（三站相同） | 10 passed / 0 failed | 2 passed / 8 failed | 6 passed / 4 failed | 9 passed / 1 failed | 2 passed / 8 failed |
| 舊版四例（三站相同） | 4 passed / 0 failed | 2 passed / 2 failed | 4 passed / 0 failed | 4 passed / 0 failed | 4 passed / 0 failed |

新版三站共抓到 12/12；歷史測試只抓到 H1，H2–H4 在三站皆存活。JUnit 核對失敗均為預期非權限負例的斷言／明確 pytest.fail，沒有正例失敗、skip、收集錯誤或其他例外混入。H4 以新物件重包同型別例外，八例均被物件身分斷言抓到。不是僅以非零結束碼判定，也沒有把先前外部 helper 身分驗收誤當成專案永久回歸保護。

### R1/R2、F1–F3、T1、F3-c

- R1：完全合成模組的頂層／if／try 星號匯入實際替換 Entry，現版摘要均變；修正前歷史 checker 僅抓頂層。舊版回歸控制後端各 5 failed/1 passed，前台 2 failed/1 passed/3 skipped（預期）；現版完整測試通過。
- R2：29 種合成模組實際匯入，6 種只讀物件／摘要不變、23 種真改寫／刪除均被偵測；舊 F2-b checker 重現 6 種只讀誤報。ADMIN/API 共 20 個來源副本案例符合預期。舊版 9 例回歸控制後端各 4 failed/5 passed，前台 2 failed/5 passed/2 skipped（預期）。
- F1：每站 14 種配置，13 符合預期、1 真實 WinError 1314 skip。有效合成 bytecode 實際匯入後確認拒絕一般／init／巢狀／舊式／大寫快取及快取內 .py；無來源標籤／文字配置拒絕；正常 opt-0/1/2 與 compileall 保留。未讀取或執行專案既有 .pyc。
- F2/F2-b：獨立驅動器從已公開探測腳本以 AST literal_eval 取得 59 種刺激，不執行該腳本或採用其結果，重新編譯合法 Python 3.12 來源並判定；ADMIN/API 各 59/59 符合預期。另各 22 個獨立來源改寫／無關控制符合預期。11 種藏在無關定義的改寫經合成模組實際匯入與摘要驗證，7 個只讀控制不誤報；兩站各 5 個來源負例都產生 contract_drift，R1 舊版會漏判。歷史回歸後端各 15 failed/1 passed、前台 10 failed/1 passed/5 skipped（預期）。
- F3/F3-b：三站 × PYTHONUTF8=0/1 × ASCII/中文路徑共 12 組正常測試，每組 3 passed。AST 確認 -I -X utf8、encoding='utf-8'，不以 errors= 忽略／替換。首輪 checker／合成匯入注入中文 RuntimeError，在兩模式下三站各 3 failed（預期），訊息獨立 E 行可讀。只附 stdout／移除編碼保護的控制皆重現退化與解碼錯誤。
- T1：三站新版及 API 舊測試各先跑整份未突變治理測試，均通過。九種突變涵蓋 MatchStar、mapping rest、global except/match、只讀 global 誤報、忽略 global、忽略 Store/Del、except as、match capture、條件式星號匯入。新版各 9/9，共 27/27；JUnit 確認對應 assertion failure 且無其他錯誤。T1 前舊測試重現 M1–M3 存活、其餘六種被抓到；M7/M8 依實際版別案例核對，不因名稱誤配判錯。
- F3-c：第一次 checker 正常，僅第二次 app/unapproved_layer 觸發中文 RuntimeError。三站 × 兩模式 × 兩路徑共 12 組，各 1 failed/2 passed（預期）；確認 exit 1 的第一個判斷仍通過、失敗落在 source_location 斷言，中文診斷獨立成行且無解碼錯誤。第二次兩個斷言均帶 stdout/stderr；移除第二個診斷的三站控制重現退化。

### 稽核、證據與未驗證項目

初始 branch/HEAD/完整 status/index entries/索引 SHA256 與明列非機密來源基準均保存；公開 .env.example 明確納入，實際 .env／秘密、Git、venv、ignored runtime/cache/tmp、未支援二進位檔排除，不宣稱涵蓋所有磁碟內容。三站共用來源／測試／規範／紀錄／快照逐位元組一致。只追加本輪六份紀錄，程式、測試、PROJECT_CHECKS、AGENTS、CI、依賴、快照、業務／Schema/ORM、STARTUP 與其清單均不改。Git 分支、HEAD、index、status 保留；git diff --check 及非機密未追蹤檔空白檢查通過，另有 LF/CRLF 乾淨與故意行尾空白控制，不改全域 Git 設定。寫報告後再跑三站 checker／完整跨站檢查通過。

STARTUP 42 筆清單只在讀取時處理 CRLF 並核對路徑與雜湊，原檔未改。本輪外部證據另產生校驗清單並由 PowerShell 複驗。證據 C:/Project/tmp/ig-accept-f1d-20261023-01：actual-results、copies-final-results、f1c-results、helper-mutant-results、f1/f2/f3-results、f2-expanded-results、definitions-results、r2-results、t1-verified-results、f3b/f3c-results.json 保存命令／結果與控制；historical-versions、copy-source-audit、startup-manifest-check、final-audit、evidence-manifest、SHA256SUMS 保存版本與範圍。

未執行遠端 GitHub CI、Linux runner、全新 pip 安裝、有建立權限的 symlink 真負例、真登入/DB/Storage/Vercel。CI 僅本機唯讀解析；不擴張既有反射／作用域／資料流／方法間接改寫／bytecode 內容限制。公司密鑰留雲端；不啟服務/Tunnel、不實作 CRUD/Storage、不部署、不執行 migration/seed、不修改正式資料、不 Commit/Merge/Push。


## 2026-10-23 Claude 獨立驗收：H1–H4 新舊對照、F1-c／F1-d、R1／R2、F1–F3、T1 與六份 Clone

以磁碟上最新未提交內容為準，全部實際重跑，未以 Codex 或前輪報告代替。開始前保存三站 branch／HEAD／完整 status／索引 entries 與索引檔 SHA256、檔案雜湊（含公開 `.env.example`；排除實際 `.env`／其他 `.env.*`、.git、.venv、快取與 tmp/pytest，不宣稱涵蓋整個磁碟）。開始時 checker `c7a4aff6…`、治理測試 `254b421a…`、PROJECT_CHECKS `4f86c1c6…`、契約 `b9512b51…`，與前節紀錄一致；執行期間沒有其他工具改動程式、測試或報告。歷史版本依 historical-versions.json 核對完整 SHA256：修正前、R1、F2-b checker，T1 前舊測試（`453e9b48…`），F1-d 前舊測試（`523d2b8c…`），以及目前 R2 checker 全部吻合；F1-d 前後的 `symlink_or_skip` AST 完全相同，差異只在測試補強。兩種舊測試分開使用：H1–H4 只用 F1-d 前版本，T1 九種突變只用 T1 前版本。

**結論：本輪沒有發現新的專案問題，沒有修改程式、測試或 PROJECT_CHECKS，只追加三站各兩份紀錄。**

### 三站完整檢查（短 basetemp，先建立父目錄，JUnit 與日誌在專案外）

| Repository | check_project | 全套 pytest | 完整跨站測試 | Ruff check／format | djLint | --project-root .. |
|---|---|---|---|---|---|---|
| InvoiceGuard-AI | exit 0 | **342 passed, 54 skipped** | 實際執行 | exit 0／exit 0 | exit 0 | exit 0 |
| InvoiceGuard-AI-ADMIN | exit 0 | **443 passed, 9 skipped** | 實際執行 | exit 0／exit 0 | exit 0 | exit 0 |
| InvoiceGuard-AI-API | exit 0 | **438 passed, 14 skipped** | 實際執行 | exit 0／exit 0 | 不適用 | exit 0 |

與前輪基準 342／54、443／9、438／14 相同。skip 原因只有站別不適用與真實 WinError 1314，不計為通過；每站只有既有 Starlette／httpx 淘汰警告。

### F1-c／F1-d：helper 行為

- 分類：三站各自從測試檔以 AST 單獨取出 helper，不 import 應用程式。ENOENT、EEXIST、ENAMETOOLONG、EINVAL、EIO、EACCES、WinError 3／206 都原樣拋出同一例外物件，只有 EPERM 與 WinError 1314 才 skip，全部符合預期。
- 真實 Windows：短連結 `OSError winerror=1314 errno=22`，helper 明確 skip；連結名稱已存在 `FileExistsError winerror=183 errno=17`，helper 原樣拋出；父目錄存在、271 字元連結 `FileNotFoundError winerror=3 errno=2`，helper 原樣拋出。
- 刻意長 basetemp（三站外部副本）：120 為真正權限 skip；150／160 以 `FileNotFoundError [WinError 3]` 失敗，JUnit 堆疊到達 `symlink_or_skip(target, outside)` 與 `link.symlink_to(target)`，不是其他準備步驟失敗。與前輪相同。
- 最新 helper 回歸：三站皆 10 passed（8 個非權限負例、2 個權限正例）：符合。
- 本機沒有建立 symlink 的權限，checker 拒絕真實 symlink 的負例 **未驗證**，不算通過。

### H1–H4：最新十例與 F1-d 前四例（只改外部副本）

每份副本先跑整份未突變治理測試，再對每個突變跑整份 test_project_governance.py 並解析 JUnit。只有「失敗全在非權限負例、是 AssertionError 或明確 pytest.fail、兩個權限正例仍通過、沒有 error 或收集錯誤」才算抓到。表內為 helper 測試子集的 failed／passed。

| 副本 | 未突變控制 | H1 捕捉所有 OSError | H2 只重拋 ENOENT／EEXIST | H3 把 EINVAL 當權限不足 | H4 包成新的同型例外 |
|---|---|---|---|---|---|
| 前台 最新 10 例 | 通過（125 passed／55 skipped） | 抓到（8 failed／2 passed） | 抓到（4 failed／6 passed） | 抓到（1 failed／9 passed） | 抓到（8 failed／2 passed，身分斷言 8） |
| 前台 F1-d 前 4 例 | 通過（119 passed／55 skipped） | 抓到（2 failed／2 passed） | 存活（0 failed／4 passed） | 存活（0 failed／4 passed） | 存活（0 failed／4 passed） |
| ADMIN 最新 10 例 | 通過（170 passed／10 skipped） | 抓到（8 failed／2 passed） | 抓到（4 failed／6 passed） | 抓到（1 failed／9 passed） | 抓到（8 failed／2 passed，身分斷言 8） |
| ADMIN F1-d 前 4 例 | 通過（164 passed／10 skipped） | 抓到（2 failed／2 passed） | 存活（0 failed／4 passed） | 存活（0 failed／4 passed） | 存活（0 failed／4 passed） |
| API 最新 10 例 | 通過（165 passed／15 skipped） | 抓到（8 failed／2 passed） | 抓到（4 failed／6 passed） | 抓到（1 failed／9 passed） | 抓到（8 failed／2 passed，身分斷言 8） |
| API F1-d 前 4 例 | 通過（159 passed／15 skipped） | 抓到（2 failed／2 passed） | 存活（0 failed／4 passed） | 存活（0 failed／4 passed） | 存活（0 failed／4 passed） |

最新版三站共抓到 12／12；F1-d 前四例只抓到 H1，H2–H4 存活：符合預期。所有突變都沒有 error、收集錯誤或權限正例失敗。H4 在最新版的 8 個失敗都是例外身分斷言。

### R1／R2、F2、F2-b（只做 AST 與合成模組，不執行 app）

- R1：合成模組的頂層、if、try 星號匯入，在隔離子程序實際把 `Entry` 換成字串；R2 版三種都改變摘要，common／vercel 專案副本 contract_drift，無關明確匯入、無關函式、備註、docstring 不誤報。全部符合預期；現有來源仍等於原快照，未重建快照。
- R2：29 例（6 只讀、23 實際改寫），以物件身分、內容與名稱是否刪除判斷，全部符合預期。合成案例非預期：修正前 23、R1 23、F2-b 6（只讀誤報）、R2 0。ADMIN／API common.py 與 vercel.py 專案副本 20 例，R2 版 20 例符合；F2-b 版重現 8 個只讀誤報。
- F2：既有 59 種刺激（條件式定義、import、except／match、star／rest、for／with、海象、del、type 別名、平台子集與無關控制）。摘要層 API／ADMIN 非預期 0；本輪另把同一批刺激套到 ADMIN／API 的來源副本執行整個專案檢查（API 59 例、ADMIN 59 例），改寫負例都產生 contract_drift、無關正例都沒有，非預期 0，每個案例後還原檔案，副本前後皆乾淨。
- F2-b：11 種藏在無關頂層定義內的改寫，實際匯入後確實改寫或修改 `Entry`，R2 版摘要全部改變、只讀控制不變；專案代表案例 contract_drift，無關 DTO 子類別不誤報。全部符合預期。未擴張成反射、作用域或資料流分析。

### F1：快取與來源配置

前台、ADMIN、API 各 13／13 符合預期。可匯入負例都先以合成來源編譯，並在隔離子程序實際 import，再確認 checker 拒絕；opt-0／1／2 與乾淨副本 compileall 通過；不讀取或執行專案既有 .pyc。symlink 案例實際錯誤為 WinError 1314，明確 **skip，不算通過**。

### F3／F3-b／F3-c（故意失敗的控制與正式結果分開）

- 靜態：兩個隔離測試保留 `-I -X utf8`，所有 `subprocess.run` 指定 `encoding="utf-8"`，沒有 `errors=`；第二次執行的 returncode 與 source_location 斷言都附 stdout／stderr。符合。
- 正常：三站 × PYTHONUTF8=0／1 × ASCII／中文 TEMP 與 basetemp，共 12 組，每組 3 案例皆 passed：符合。
- F3-b：首輪 checker 啟動失敗與合成位元組碼匯入失敗的中文 RuntimeError，12 組皆以獨立 `E` 行顯示，沒有解碼錯誤：符合。
- F3-c：checker 只在第二次掃到 `app/unapproved_layer` 時崩潰；12 組 JUnit 皆顯示失敗在 source_location 斷言行，中文訊息獨立顯示，沒有解碼錯誤：符合。
- 控制：只附 stdout、移除 UTF-8 保護、移除第二次斷言診斷，三者皆依預期退化：符合。

### T1：九種突變

只改外部副本。每份先跑整份未突變治理測試（全部通過），每個突變確認替換位置唯一並通過 `ast.parse`／`compile`，跑整份 test_project_governance.py 並解析 JUnit：必須是預期回歸測試的 assertion failure、指定類型的案例有命中，且沒有 error 或收集錯誤。新版：前台 9／9、ADMIN 9／9、API 9／9。T1 前 API 舊測試：M1、M2、M3 存活，M4、M5、M6、M7、M8、M9 被抓到；M7／M8 依舊版本身的 `except ValueError as reject_bool_and_float`、`case PageQuery:` 案例判定。

### 六份隔離副本（最新工作區來源，各自獨立父目錄）

逐檔與工作區比對 SHA256；包含 AGENTS／CLAUDE、文件、契約、scripts、CI、設定中繼檔與公開 `.env.example`，沒有實際 .env、.git、.venv、快取或兄弟站。全部符合。

| 副本 | 角色（APP_NAME） | 檔案數 | 單站 checker | 他處 -I -B -X utf8 | 完整跨站測試 | 明確 --project-root | 全套 pytest |
|---|---|---|---|---|---|---|---|
| 前台 固定名（`InvoiceGuard-AI`） | InvoiceGuard-AI | 91（未追蹤 24） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 2） | 341 passed, 55 skipped |
| 前台 改名（`invoiceguard-ai-renamed-clone`） | InvoiceGuard-AI | 91（未追蹤 24） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 3） | 341 passed, 55 skipped |
| ADMIN 固定名（`InvoiceGuard-AI-ADMIN`） | InvoiceGuard-AI-ADMIN | 119（未追蹤 16） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 2） | 442 passed, 10 skipped |
| ADMIN 改名（`invoiceguard-ai-admin-renamed-clone`） | InvoiceGuard-AI-ADMIN | 119（未追蹤 16） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 3） | 442 passed, 10 skipped |
| API 固定名（`InvoiceGuard-AI-API`） | InvoiceGuard-AI-API | 106（未追蹤 15） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 2） | 437 passed, 15 skipped |
| API 改名（`invoiceguard-ai-api-renamed-clone`） | InvoiceGuard-AI-API | 106（未追蹤 15） | exit 0 | exit 0 | 1 skipped | exit 1（peer_missing 3） | 437 passed, 15 skipped |

與前輪基準 341／55、442／10、437／15 相同；多出的 1 個 skip 是缺兄弟站的完整跨站測試。

### CI、未驗證與限制

- CI 僅本機唯讀檢查，工作流程未改：單站 checkout、persist-credentials: false、Python 3.12、ubuntu／windows matrix、contents: read；沒有 secrets、pull_request_target、部署或 migration。
- **未執行**：GitHub 遠端 CI、Linux runner（含 1314 案例在 Linux 的 skip 計數）、全新 pip 安裝、有權限時 checker 拒絕真實 symlink 的負例、真登入／DB／Storage／Vercel。未啟動服務或 Tunnel。
- 限制：靜態分析不涵蓋反射、方法呼叫間接修改與完整作用域／資料流；快取檢查不驗證位元組碼內容。STARTUP 的 SHA256SUMS.txt 只在讀取時去除 CR 後驗證，原檔未改。ADMIN／API 的 app/ 內 2026-10-22 既有 `__pycache__` 未讀取、執行或刪除。
- 版本（本輪未改）：checker `c7a4aff63ee91435a522f911e40868ad550019f3ad449264d04ef138639ca6cb`；治理測試 `254b421ab27a53e5676e09d1dcbf61d88ee5ba063a6d8f650ed9a3a24afccec1`；PROJECT_CHECKS `4f86c1c6cfb368a4f3ed5d0acb0e316c0a16ab2add7f9cc60149e9f267750250`；契約 `b9512b51b6d8c2977add4ba9758efddcc49e1f052ed124275a5aa4cfe24efc03`。三站逐位元組一致。
- 證據：C:\Project\tmp\ig-claude-r8-20261023（baseline；full；historical-check.json；f1c；h：H1–H4 新舊 JUnit 與日誌；probes：r1／r2／f2／f2p／gap 與 f1；f3；m；cl；checkers 與兩種舊測試；final-audit.json；scripts；SHA256SUMS.txt）。

## 2026-10-23 Codex：ADMIN／API 各 59 個 F2 專案層案例獨立重跑

本節實際執行 118 個完整 check_project 案例，補足先前僅核對 Claude 第八輪專案層證據的範圍。獨立驅動器從既有 governance4_f2.py 以 AST literal_eval 取得相同 59 種刺激，不執行其腳本、不採用既有結果；逐站載入最新副本內的 checker，直接呼叫完整 check_project，並非只比較 ast_digest。沒有發現新的專案問題，本輪只同步追加三站 TEST_REPORT／REVIEW_FIX_LOG 共 6 檔。

| 專案 | 改寫案例觸發 contract_drift | 無關案例零問題 | 非預期 | 每案完整還原 |
|---|---|---|---|---|
| InvoiceGuard-AI-ADMIN | 44/44 | 15/15 | 0 | 59/59 |
| InvoiceGuard-AI-API | 44/44 | 15/15 | 0 | 59/59 |

每站只建立一份專案外非機密副本，含公開 .env.example 與必要未追蹤來源／規範／契約／中繼設定，不含實際 .env、.git、venv 或預存快取。初始所有檔案與來源基準 SHA256 完全相符，完整專案檢查為零問題。每案先確認上一案已還原，編譯確認刺激為合法 Python 3.12，只修改指定 common.py／vercel.py，核對恰好只有該檔改變，再跑完整專案檢查。

44 個改寫案例的 issue codes 都恰為 contract_drift，15 個無關案例的 issue codes 全部為空，沒有其他分層／格式誤報。每案 finally 還原原始 bytes，再核對整份副本的檔案集合及所有檔案 SHA256，並再次執行完整 check_project 確認零問題；最終整份副本亦完全還原。此處完整還原指檔案集合及內容。兩份副本最後另以 CLI scripts/check_project.py 驗證 exit 0，CLI 執行後再核對副本仍相符。

測試使用 Windows／既有 Python 3.12、-B、PYTHONDONTWRITEBYTECODE=1，驗收程序僅保留 OS 環境白名單，不 import app、不載入實際 .env、不使用公司設定或連網。實際命令為 API venv Python -B -X utf8 C:/Project/tmp/ig-f2-project-20261023-01/verify_f2_project.py；case group、名稱、來源檔、預期／實際 issue codes、單檔變更與逐案還原證據保存於 f2-project-results.json，刺激與來源 SHA256 保存於 stimuli.json。

本輪保存初始三站 branch/HEAD/status/index entries/索引 SHA256、明列非機密來源及 STARTUP 雜湊；未追蹤來源與公開 .env.example 納入，實際秘密、Git、venv、ignored runtime/cache/tmp 與未支援二進位檔排除，不宣稱覆蓋所有磁碟。最後確認程式、測試、PROJECT_CHECKS、契約、AGENTS、CI、依賴、業務及 STARTUP 均未改；只有六份紀錄追加，Git 分支/HEAD/index/status 保留。追蹤與非機密未追蹤檔另有空白檢查及 LF/CRLF 乾淨／故意空白控制；未改 Git 全域設定。報告更新後三站 checker 與完整跨站檢查 exit 0。

證據：C:/Project/tmp/ig-f2-project-20261023-01；baseline.json、stimuli.json、f2-project-results.json、results/、copy-cli-results.json、post-report-results.json、final-audit.json、evidence-manifest.json、SHA256SUMS.txt。外部證據校驗另以 PowerShell 核對，未改 STARTUP 清單。

本輪為 F2 專案層定向驗收，未重跑完整 pytest、R1/R2/F1/H1–H4/T1/F3 的其他矩陣，前輪結果仍是歷史結果。遠端 CI、Linux、全新安裝、有權限 symlink 真負例、真登入/DB/Storage/Vercel 仍未驗證。公司密鑰留雲端；未啟服務/Tunnel、不實作 CRUD/Storage、不部署、不執行 migration/seed、不修改正式資料、不 Commit/Merge/Push。


## 2026-10-23 Claude 獨立驗收：ADMIN／API 各 59 個 F2 完整專案層案例

**本輪實測範圍只有 ADMIN／API 的 118 個 F2 專案層案例與必要的複驗**（報告更新後三站 checker、完整跨站檢查、Git／檔案稽核）。本輪沒有修改程式或測試，因此沒有重跑全套 pytest、H1–H4、T1、F3 或六份副本；這些項目以前節為準，不寫成本輪執行。

### 刺激來源與版本

- 來源：前輪治理探測腳本 `governance4_f2.py` 的四組 literal 字典，以 `ast.literal_eval` 讀取，**沒有執行該腳本**。腳本 SHA256 `7bb749dc0f30eafeba7bf95a92e9d90dc958eaba406b0eb6811e76cdcc3b5816`，與前輪 stimuli.json 記錄的來源雜湊相同；四組字典（含順序）與前輪 stimuli.json 逐案相同。正規化內容（排序後的精簡 JSON）SHA256 `3746c43dab4e00cc62ed8fec80e0f9558b48659a1a66583f62cbab0d548cf733`。
- 數量：COMMON_MUST_CHANGE 39、COMMON_MUST_NOT_CHANGE 13、PLATFORM_MUST_CHANGE 5、PLATFORM_MUST_NOT_CHANGE 2。每站 44 個改寫、15 個無關變更，共 59 個，兩站 118 個；沒有增刪或替換案例。
- 版本：checker `c7a4aff6…`、治理測試 `254b421a…`、契約 `b9512b51…`，與前節相同；執行期間三站程式、測試、報告都沒有被其他工具改動。

### 方法與環境隔離

- 每站各建一份專案外副本，來源為最新工作區（Git 追蹤＋未忽略的未追蹤檔，從磁碟讀取，含合法未提交修改與 `.env.example`），沒有實際 .env、.git、.venv 或快取。副本完整檔案集合與每檔 SHA256 已保存，並與原始來源、本輪基準逐檔核對一致。
- 驗收程序以 `env -i` 只傳 SYSTEMROOT、WINDIR、PATH、TEMP、TMP、PYTHONUTF8、PYTHONDONTWRITEBYTECODE，Python 以 `-I -B -X utf8` 執行；各站使用副本自己的 `scripts/check_project.py`，不 import app、不載入環境設定、不執行刺激。
- 每案依序：核對整份副本與初始集合／SHA256 一致 → 保存目標檔 bytes → 以 `compile` 確認刺激是合法 Python 3.12（不執行）→ 寫入並確認只有目標檔改變 → 呼叫完整 `check_project(copy_root)` 記錄所有 issue → `finally` 還原 bytes → 再核對整份副本（檔案集合、目錄集合、每檔 SHA256）→ 再跑完整 check_project 必須零問題。案例出現例外時也會還原並記錄；副本未還原就停止使用。

### 結果

| 站 | 副本檔案數 | 副本 checker | 初始 issue | 改寫案例觸發 contract_drift | 無關案例零問題 | 每案還原且零問題 | 非預期 | 最終一致／issue／CLI |
|---|---|---|---|---|---|---|---|---|
| InvoiceGuard-AI-ADMIN | 119（未追蹤 16，含 `.env.example`） | `c7a4aff63ee9…` | 0 | 44/44（只有 contract_drift：44/44） | 15/15 | 59/59 | 0 | 一致／0 個 issue／CLI exit 0／CLI 後一致 |
| InvoiceGuard-AI-API | 106（未追蹤 15，含 `.env.example`） | `c7a4aff63ee9…` | 0 | 44/44（只有 contract_drift：44/44） | 15/15 | 59/59 | 0 | 一致／0 個 issue／CLI exit 0／CLI 後一致 |

- 44 個改寫案例的 issue 都恰好只有 1 個 `contract_drift`，且指向目標檔（common.py 或 vercel.py），沒有其他代碼需要追查。15 個無關案例完全零問題，不只是沒有 contract_drift。
- 每案的寫入前後完整性、只改目標檔、可編譯、還原後零問題皆成立；沒有例外、沒有提前停止。最終副本與初始基準完全一致，完整 check_project 零問題，以副本 CLI（站內 venv，`-B scripts/check_project.py`，cwd 為副本）執行 exit 0，CLI 執行後副本內容仍未變。整體符合預期。
- 與前輪比較基準（兩站各 44/44、15/15、59/59、0 非預期）相同。

### 發現與修改

本輪沒有發現新的專案問題，沒有修改程式、測試、PROJECT_CHECKS 或契約快照；只追加三站 docs/TEST_REPORT.md 與 docs/REVIEW_FIX_LOG.md（共用文件，三站同步）。

### 證據與未執行項目

- 證據：C:\Project\tmp\ig-claude-f2p-20261023（baseline；stimuli-from-ast.json；run/f2-project-results.json（每案 issue、完整性與還原）；run/manifest-ad.json、manifest-api.json（副本檔案集合與 SHA256）；run/cross-checks.json；post-report-checks.txt；final-audit.json；scripts；SHA256SUMS.txt）。
- **本輪未執行**：三站全套 pytest、Ruff、djLint、H1–H4、T1、F3、六份副本（程式未改，沒有重跑）；GitHub 遠端 CI、Linux runner、全新 pip 安裝、有權限時的 symlink 真負例、真登入／DB／Storage／Vercel。未啟動服務或 Tunnel。

## 2026-10-23 Claude：共同規則同步後的治理檢查

- 對象：AGENTS.md 共同區塊「本機入口」與 contracts/project-contract.json 的 agent_rules_sha256（使用者同意）。
- 指令：.venv\Scripts\python.exe -B scripts/check_project.py；同上加 --project-root C:\InvoiceGuard_project；.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider tests/unit/test_project_governance.py（basetemp 在專案外）。
- 結果：契約更新前單站 1 issue、跨站 3 issues（agent_rules_drift），治理測試多項失敗；更新後單站、跨站皆 PASS（0 issues），治理測試：前台 126 passed／54 skipped、ADMIN 171 passed／9 skipped、API 166 passed／14 skipped。
- 未執行：各站業務 pytest、Ruff（本次只改 Markdown 與 JSON 雜湊欄位）。

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

## 2026-10-23 Claude：最終獨立驗收（本站）

- 共同規則：共同區塊以 check_project 方法計算為 fe415bc3df35b6be8f1a849564c620624f8e89d41d6e0c7358bf89d9e82a74c5，等於本站契約 agent_rules_sha256，與另兩站相同；區塊外角色說明及契約其他欄位與修改前相同；LF、無 BOM、無行尾空白。專案外副本加一行合成共同規則時 agent_rules_drift、exit 1，還原後零 issue。
- check_project 單站與 --project-root 跨站皆 PASS（0 issues）。
- test_project_governance 166 passed／14 skipped；授權相關 tests/unit/test_cron_auth.py 10 passed（含 local 環境不繞過 cron 驗證）。API 別名在真 START 只供本機，/health 帶服務身分。
- 未修改本站任何程式、樣板、測試或契約；只追加本節。證據 C:\Project\tmp\ig-claude-final-20261023。

## 2026-10-25 Claude：DB／Storage 模組複製驗證

- 新增 `tests/unit/test_db_connection_check.py`（自 ADMIN）、`tests/unit/test_supabase_storage.py`（ADMIN 用戶端測試：SigV4 參考向量、簽章、列表分頁、下載／移動／刪除、錯誤代碼、缺設定）、`test_module_config.py` 新增本機 DB 與 Storage 設定案例；舊規則斷言（本機 DATABASE_URL 為機密、空字串為 invalid_postgres_url）依核定改寫。
- 完整 pytest 478 passed／14 skipped；check_project 單站與跨站 PASS（前台、ADMIN 跨站亦 PASS）；Ruff check／format 78 檔通過。
- 實測（API venv，使用 ADMIN 專案可讀取的同一組 DB／Bucket 設定）：本機環境檢查通過、`import app.main` 成功、SELECT 1 = 1；Storage 上傳／列表／下載（位元組相同）／移動／刪除成功，測試檔已刪除。真 START.cmd（exit 0）下 API `/health` 200、env=local；因 invoice-guard-ai-api 專案的 DATABASE_URL、S3_SECRET_ACCESS_KEY 為 Sensitive，START 依設計回報缺少並以無 DB 模式啟動 API。

## 2026-10-25 Claude：API 自己 Vercel 專案設定實測

- 真 START.cmd 注入 invoice-guard-ai-api 的設定後 API `/health` 200；API venv 以相同值實測 Storage 全流程成功（測試檔已刪除），DB SELECT 1 為 auth_failed：該專案 DATABASE_URL 的密碼欄以 [ ] 包住且不是目前可用的 DB 密碼。詳見 STARTUP TEST_REPORT 同日小節。

## 2026-10-25 Claude：API DATABASE_URL 密碼修改後複測

- invoice-guard-ai-api 的 DATABASE_URL 密碼內容已與 ADMIN 可用密碼相同，但仍以 [ ] 包住（18 字元，內層 16 字元相同）。API venv 以 START 相同方式取得的值實測：SELECT 1 為 auth_failed；記憶體中去掉 [ ] 後 SELECT 1 = 1。Storage 全流程再次成功，測試檔已刪除。未重跑真 START（結果與前次相同，待 Vercel 值去掉括號後再驗）。

## 2026-10-25 Claude：API DATABASE_URL 修正後最終驗收

- invoice-guard-ai-api 的 DATABASE_URL 已與 ADMIN 專案相同（無括號）；六個變數皆可讀取，S3／Bucket 與 ADMIN 相同。
- API venv 以 START 相同方式取得的 API 專案值：本機環境檢查通過、`import app.main` 成功、DB 模組 SELECT 1 = 1；Storage 上傳、列表、下載（位元組相同）、移動、刪除成功，測試檔已刪除。
- 真 `START.cmd --no-browser --run-seconds 30` exit 0：ADMIN 與 API 各自從自己的 Vercel 專案取得 DB／Storage 設定；執行中 ADMIN `/health`、`/dev/accounts`、`/dev/files` 200，API `/health` 200（env=local）。全程唯讀 DB，未寫入正式資料。

## 2026-10-28 Claude：Google Document AI／Gemini 模組實測

使用者授權各實際呼叫一次。以 START 的 fetch_vercel_environment 取得 invoice-guard-ai-api Production 設定、api_runtime_values 注入獨立 API 子程序（與 START 相同），只輸出摘要，不輸出金鑰。

| 項目 | 結果 |
|---|---|
| Document AI `describe_processor()` | OCR_PROCESSOR／ENABLED，預設版本 pretrained-ocr-v2.1-2024-08-07 |
| Document AI `process()`（前台 `app/static/img/reference_invoice.jpg`，969×595 JPEG） | 成功：1 頁、29 行、全文 200 字、平均信心 0.915；前幾行含「TL 28281500」「買受人:」「統一編號:」「一發票(三聯式)」「一〇八年九、十月份」 |
| Gemini（gemini-2.5-flash） | 404 NOT_FOUND：該模型已不開放給新使用者（未產生內容） |
| Gemini 免費確認（models.get、countTokens） | gemini-2.5-flash／gemini-3.8-flash 皆支援 generateContent；gemini-3.8-flash 的 countTokens 200 |
| Gemini（gemini-3.8-flash）`chat()` | 402 RESOURCE_EXHAUSTED：「Your prepayment credits are depleted」，AI Studio 預付額度用完（未產生內容）；模組當時歸為 gemini_failed，已改為 gemini_quota_exceeded |

結論：Document AI 模組端到端可用。Gemini 模組的 Key、模型與請求格式正確，對話成功回應尚未取得，需使用者在 AI Studio 儲值後再驗證一次。共送出 Document AI 辨識 1 次、Gemini generateContent 3 次（皆被拒、未產生內容）；未部署、未寫 DB、未重啟使用者的 START。
- 2026-10-28 使用者更換 Vercel 的 GEMINI_API_KEY 後重測：`chat()` 回 gemini_auth_failed（INVALID_ARGUMENT/API_KEY_INVALID），免費的列模型同樣 400 API_KEY_INVALID。唯讀格式檢查：新值 26 字元、無空白或引號，形式為 `gen-lang-client-<10 位數字>`（Google Cloud 專案 ID 的格式，且不同於 GOOGLE_CLOUD_PROJECT_ID），不是 API Key。需改填 AI Studio「API Keys」頁的金鑰字串。本次未產生內容、未計費。
- 2026-10-28 使用者新增 GEMINI_PROJECT_ID 後重測：GEMINI_API_KEY 與 GEMINI_PROJECT_ID 是同一個值（專案 ID `gen-lang-client-0026747147`），免費的列模型仍回 400 API_KEY_INVALID，所以沒有送出對話請求。Gemini API 以 API Key 驗證，專案 ID 不是憑證；程式不讀 GEMINI_PROJECT_ID，START 也不注入。GEMINI_API_KEY 須改填 AI Studio「API Keys」頁該專案的金鑰字串。
- 2026-10-28 使用者更正 GEMINI_API_KEY 後重測：新值為 `AQ.` 開頭 53 字元的金鑰，免費列模型 200（Key 有效）。`chat()` 回 gemini_quota_exceeded（RESOURCE_EXHAUSTED，分類正確）；診斷請求確認為 HTTP 402「Your prepayment credits are depleted」，此 Key 所屬專案的預付額度為 0。未產生內容、未計費；需在 AI Studio 為該專案儲值後再驗證。

## 2026-10-28 Claude：GROQ_API_KEY 實測

- Vercel：GROQ_API_KEY 為 Config 類型，設在 invoice-guard-ai-api 與 invoice-guard-ai-admin 的 Production。以 `vercel env run --project invoice-guard-ai-api` 讀取，只輸出摘要。
- Key：`gsk_` 開頭 56 字元、無前後空白；免費列模型 200，`qwen/qwen3.8-27b` 可用。
- 依使用者範例送出一次 chat.completions（`https://api.groq.com/openai/v1`、model qwen/qwen3.8-27b、system＋user、max_tokens 200）。API venv 沒有 openai 套件，改以既有 httpx 送出相同的 OpenAI 相容請求：200，回答「收到，API 測試成功。」，finish_reason stop，tokens 39＋8＝47，未附思考內容。
- 只做連線實測，尚未加入 API 模組、設定欄位或 START 注入；本機 START 目前不注入 GROQ_API_KEY。

## 2026-10-28 Claude：Document AI OCR → Groq gpt-oss-20b 發票 JSON 實測

以 `vercel env run --project invoice-guard-ai-api` 執行（Production 設定只在該次程序），只輸出摘要。

| 步驟 | 結果 |
|---|---|
| Document AI `process()`（前台 reference_invoice.jpg，空白三聯式樣張） | 1 頁、29 行、200 字、平均信心 0.915 |
| Groq `chat(purpose="recognition", json_output=True)` | 實際模型 openai/gpt-oss-20b，finish stop，tokens 718＋776＝1494 |
| 回傳內容 | 合法 JSON，欄位齊全（v1.3 invoices／invoice_items 欄位名）：is_triplicate true、invoice_track TL、invoice_number 28281500 正確；樣張空白欄位皆為 null、items 為空陣列；tax_period 回 202109，錯誤（「一〇八年九、十月份」應為 201909） |

結論：OCR → 20B 的 JSON 串接可用；民國年換算等需由程式驗證。樣張沒有填寫內容，尚未以實際開立的發票驗證金額與品項擷取。

## 2026-10-29 Claude：以 START 環境測試圖片與 AI 對話

- 以新版 SETUP.cmd 執行 `--reuse --skip-tools`（exit 0，STARTUP 內未新增檔案），安裝含 Groq 注入的 START runtime（runtime-c4896626…，與 repo launcher 相同）。用該 runtime 的 fetch_vercel_environment／api_runtime_values 取值，與 START 相同注入 API 子程序（12 項含 GROQ_API_KEY；APP_ENV=local，環境檢查有效）。只輸出摘要。
- 圖片：Document AI OCR（reference_invoice.jpg）1 頁、29 行、平均信心 0.915 → gpt-oss-20b（recognition、JSON 模式）1353 tokens：合法 JSON，字軌 TL、號碼 28281500、三聯式正確，tax_period 這次為 201909（前次同輸入回 202109），模型輸出前後不一致，民國年換算仍需程式驗證。
- AI 對話：default → gpt-oss-20b，273 tokens，回答通順；discussion → gpt-oss-120b，284 tokens，條列三點，但內容為一般性敘述，未對應營業稅法規定的不得扣抵項目，法規問答需以知識庫（RAG）內容為依據。
- 未啟動 START 的服務視窗與 Tunnel；Gemini 因預付額度為 0 未測。

## 2026-10-29 Claude：手機上傳發票（辨識、查重、送出）

- 範圍：`POST /api/v1/invoices/recognize`、`/check-duplicate`、`POST /api/v1/invoices`；新增 schemas/invoice_upload.py、services/invoice_upload_service.py、repositories/invoice_repository.py（取代 TODO）、recognition_repository.py、utils/invoice_format.py；requirements 加入 python-multipart==0.0.32（與前台、ADMIN 同版）；supabase_storage.from_settings 增加 bucket 參數（ADMIN 同步）。
- 離線測試 tests/unit/test_invoice_upload.py 50 案（repository、Storage、Document AI、Groq 皆為替身）：存圖鍵格式與台灣時間、欄位換算、PNG、無效／過大影像不寫資料、未登入／Session 失效、20B 失敗改 120B、Key 被拒不重試、OCR／Storage 失敗記 failed、無文字、模型未設定時不寫資料、檢核提醒、逾時影像清理與刪除失敗、查重、送出建立各表與差異、重複、逾時／已送出／未完成／非本人、請求格式驗證、日期／期別／金額／統編工具。
- repository 的 14 段 SQL 以 pglast（PostgreSQL 解析器）解析通過；未在資料庫執行。
- 驗證：check_project 單站與 --project-root PASS；pytest 652 passed、14 skipped；ruff check／format --check 通過。
- 未驗證：正式 DB／Storage／Document AI／Groq 的實際寫入與呼叫（需使用者以手機經 START 測試，會寫入正式資料）；Vercel 部署後的逾時與請求大小。

## 2026-10-29 Claude：Codex 檢驗修正＋使用者修改欄位標記

- tests/unit/test_invoice_upload.py 由 50 案增為 95 案：可選欄位 null／空白、修改紀錄（中間修改、順序、不一致的 7 種情形）、明細來源（依 source_line_no 比對、新增、刪除、重複／不存在）、與前台同形的修改紀錄、前後台比對規則 17 案、異常辨識值、後處理失敗、NaN 信心值、時限與備援、四捨五入。
- 驗證：check_project（單站與 --project-root）PASS；pytest 697 passed、14 skipped；ruff check／format --check、environment --check 通過。
- 未驗證：正式 DB／Storage／Document AI／Groq 實際寫入與呼叫；SQL 仍只做解析與靜態對照。

## 2026-10-29 Claude：Codex 第二輪檢驗修正

- 新增：Document AI 截止時間涵蓋換發權杖（2 案）；比對案例 7 案、高精度中間修改、501 筆修改紀錄。另以 node 對照前台 canonicalValue 17,325 組，差異 0（臨時腳本，不列入 pytest，因 CI 不保證有 node）。
- 驗證：check_project（單站與 --project-root）PASS；pytest 708 passed、14 skipped；ruff check／format --check、environment --check 通過。
- 未驗證：正式服務實際呼叫與寫入。

## 2026-10-29 Claude：辨識支援單頁 PDF（電腦上傳頁）

- 範圍：`invoice_format.INVOICE_FILE_EXTENSIONS` 加入 application/pdf（Storage 檔名 .pdf，與 invoice_files.mime_type 的 CHECK 一致）；`invoice_upload_service` 以檔頭 `%PDF-` 判斷、上限仍 4 MB，Document AI 回傳超過一頁時記 failed 並回 400 INVOICE_PDF_MULTIPAGE（不呼叫模型）；送出時 invoice_files.mime_type 為 application/pdf。影像流程不變。
- 測試：單頁 PDF 辨識、多頁 PDF 拒絕、影像不受頁數判斷影響、PDF 送出寫入 PDF 檔資訊、宣告類型不符、GIF、PDF 過大、Storage 鍵 .pdf。
- 驗證：check_project（單站與 --project-root）PASS；pytest 714 passed、14 skipped；ruff check／format --check、environment --check 通過。
- 未驗證：Document AI 對真實掃描 PDF 的辨識結果；正式 Storage／DB 寫入。

## 2026-10-29 Claude：ADMIN 使用同版 AI 模組（API 端配合）

- API 程式未修改；新增 tests/unit/test_shared_integrations.py（與 ADMIN 相同）：supabase_storage.py 與四個 AI 模組檔在兩站同目錄時逐位元組比對，單站 checkout 時 skip。共同規範（三站 AGENTS 共同區塊）改為 ADMIN 與 API 都由 START 注入 AI 設定，agent_rules_sha256 三站同步。
- 驗證：check_project（--project-root）PASS；pytest 726 passed、14 skipped；ruff、environment --check 通過。

## 2026-10-30 Claude：新增 Agent Platform 向量模組

- 使用者要求：ADMIN 測試通過後同步 API。新增 app/integrations/vertex_embedding.py 與 tests/unit/test_vertex_embedding.py，兩站逐位元組相同並列入 test_shared_integrations；Settings、.env.example、tests/conftest.py 加 VERTEX_EMBEDDING_MODEL、VERTEX_EMBEDDING_DIMENSIONS。未改 document_ai／gemini／groq，Vercel 與 START 不用改。
- Claude 回報的離線驗證（本輪結果另記 REVIEW_FIX_LOG）：check_project（--project-root）PASS；pytest ADMIN 1493 passed、9 skipped，API 961 passed、14 skipped；ruff check／format --check、environment --check 通過。
- Claude 回報的真實呼叫（本輪未重新驗證；兩站各以自己的 Vercel 設定，只送合成文字，不寫 DB）：gemini-embedding-2 回 1536 維；相關句相似度 0.7948、無關句 0.5795；100 段（每段 725 字）ADMIN 6.3 秒、API 4.48 秒；超過 8,192 token 回 embedding_invalid_input。
- 未驗證：長時間配額、真實文件的檢索品質、部署後的雲端執行。未接線功能、未改 DB、未 Commit。

## 2026-10-30 Claude：Codex 修正後複驗並新增 RAG 開發說明

- 新增 docs/RAG_DEVELOPMENT.md（ADMIN、API 內容相同），AGENTS.md 與 MODULE_CONTRACT.md 加入連結；API 的 KNOWLEDGE_API_CONTRACT.md 加註過期提示。程式未再修改。
- 離線複驗：check_project（--project-root）PASS；pytest ADMIN 1519 passed、9 skipped，API 987 passed、14 skipped；ruff check／format --check、environment --check 通過。
- 真實呼叫（Codex 修正後的模組，兩站各以自己的 Vercel 設定，只送合成文字，不寫 DB）：gemini-embedding-2 回 1536 維；相關句相似度 0.7948、無關句 0.5795；100 段（每段 725 字）ADMIN 4.25 秒、API 4.09 秒；超過 8,192 token 回 embedding_invalid_input。
- 未驗證：長時間配額、真實文件的檢索品質、部署後的雲端執行。未接線功能、未改 DB、未 Commit。