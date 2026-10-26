# 歷史檢驗指令：三站 AI 協作規範與自動檢查

> 這是過去一次檢驗任務的指令，保留作紀錄，不是現行規則；其中「本輪」的範圍限制只適用當時。現行規則以 AGENTS.md 為準。

本指令取代本站舊第一階段檢驗提示；歷史結果不得當成本次重跑證據。可將下方整段交給 Desktop Claude／Claude Code，並給予三站本機目錄存取權，不提供公司密鑰。

```text
請獨立檢驗 C:\InvoiceGuard_project 下的 InvoiceGuard-AI、InvoiceGuard-AI-ADMIN、InvoiceGuard-AI-API 最新未提交工作。實際根目錄不同時只調整根目錄；不要假定三站 Git branch 或未提交檔案可覆寫。

目標：驗證 AGENTS.md／CLAUDE.md 的共同規範入口、文件對齊、版本化契約與分層檢查可讓不同 AI 一致開發。本輪只處理這些規範／檢查問題，不實作 CRUD／Storage 或新增身分系統。

先讀三站 AGENTS.md、CLAUDE.md、README、docs/DEVELOPMENT_STATUS.md、PROJECT_CHECKS.md、TEST_REPORT.md、REVIEW_FIX_LOG.md，再讀 scripts/check_project.py、contracts/project-contract.json、tests/unit/test_project_governance.py 及對應來源。確認 CLAUDE.md 明確 @AGENTS.md；若目前 AI 產品沒有自動載入，請手動讀完，不宣稱工具一定已自動載入。

先保存唯讀 Git branch／HEAD／index／status 基準，保留全部既有修改。不讀、列印或下載實際密碼、連線字串、Token／私鑰；不做 vercel env pull。測試只用合成假值，保留現有網路／真 DB 阻擋器，暫存放專案外，禁用 bytecode 與 pytest／Ruff cache。不要新增管理員帳號或索取 Vercel／Supabase 管理權限。

每站使用自己的 Python 3.12 venv，從該站根目錄實際執行：
  .\.venv\Scripts\python.exe -B scripts/check_project.py
  .\.venv\Scripts\python.exe -B -m pytest -q -p no:cacheprovider --basetemp <該站專用的專案外暫存>
  .\.venv\Scripts\python.exe -B -m ruff check --no-cache app tests scripts
  .\.venv\Scripts\python.exe -B -m ruff format --check app tests scripts
UI 兩站另外執行：
  .\.venv\Scripts\python.exe -B -m djlint app/templates --lint
三站齊全後從任一站再執行：
  .\.venv\Scripts\python.exe -B scripts/check_project.py --project-root ..

驗證重點：
1. 只有單站副本也能通過，不需兄弟 Repo、app import、網路或公司密鑰。從其他工作目錄用檢查腳本絕對路徑也能使用。
2. 所有 app Python 都掃描，不能靠新檔、相對 import、別名、函式內／TYPE_CHECKING import、動態 import、額外 dotenv／BaseSettings 繞過規範。Router 不直連 DB，前台一般 Router 不直接 HTTP；Service 控交易但 Repository 不 commit；schemas／DB／integrations 不能向上相依。
3. 精確保留 core/deps DI、前端 core/exceptions 的 ApiError 及手機 loopback health httpx 例外，不能放寬成整層通行。既有安全／授權測試不能變弱。
4. 在專案外副本實際突變：DTO 大小／驗證器、common 常數、ORM 真正約束、共同規範、契約快照／缺檔、新未知目錄，確認檢查失敗；合法 docstring／格式差異不誤報。不在實際專案改壞後留下殘檔。
5. 快照必須保留驗證器函式體、SQL 常數及 ORM 約束，不能只查介面名字。同步修改 snapshot 不是安全保證；不得以重建快照、刪測試或放寬例外掩蓋失敗。若確為本輪基準錯誤，記錄原因與跨站實際差異，修正一致的基準而不弱化規則。
6. 三站 README 與架構以 START.cmd 與 Repository 全名別名作日常入口，內部埠只標診斷；Blob／Supabase 與 migration 流程不再矛盾。核對實作／契約／TODO 狀態，不將頁面、health、Protocol 當成業務完成。
7. CI 只 checkout 本站，以 Windows/Linux Python3.12 執行無密鑰檢查；contents:read，無公司 secrets、部署、migration 或 pull_request_target 權限提升。不自行觸發 GitHub CI 或建立PR/Push。
8. 原三站框架、ADMIN 自有 DB、API Schema ownership、公司機密雲端邊界與未實作工廠 fail closed 都維持。除兩份手機模板的 Jinja 檔頭註解，本輪不應更改業務程式。

如果發現本輪範圍內問題，請直接修正、補有效回歸測試並重跑受影響檢查，不必逐項再詢問。同步其他站的共同副本／文件；更新各受影響站 docs/TEST_REPORT.md 與 docs/REVIEW_FIX_LOG.md，逐項記錄日期、嚴重度、重現、原因、修正檔案、驗證指令與實際結果、未驗收項目。沒有發現問題也留下範圍與結果，不能只回聊天。

若改動核定契約快照，說明必要性與來源，不得無理由更新所有快照來變綠。STARTUP 本輪未修改；只有真的改到 STARTUP 內容，才須同步其 TEST_REPORT 與 SHA256SUMS，不可無故重產歷史文件。

禁止部署、執行 migration／seed／真實排程、修改正式資料、Commit／Merge／Push、reset 或覆寫既有工作。不要啟 Tunnel／服務或操作公司登入，本輪是規範／離線檢查驗收。無法在目前環境執行的 Windows/Linux/GitHub 測試明列未執行，不以文件或前次結果冒充通過。

完成後用繁體中文提供：發現與直接修正清單、實測結果、保留的限制、處理紀錄與測試報告的完整路徑、Git基準是否維持。
```
