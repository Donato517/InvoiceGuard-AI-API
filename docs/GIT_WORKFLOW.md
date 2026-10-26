# Git 協作規範

先讀 [AGENTS.md](../AGENTS.md)／[CLAUDE.md](../CLAUDE.md)；本文件是團隊流程參考，
不是對目前任務執行 Commit、Push、Merge、migration 或部署的授權。
除非人類在當前任務明確授權，保留分支、索引與未提交修改，不自動執行上述動作。
開發狀態見 [DEVELOPMENT_STATUS.md](DEVELOPMENT_STATUS.md)，提交前檢查見 [PROJECT_CHECKS.md](PROJECT_CHECKS.md)。

> 三個專案（InvoiceGuard-AI / InvoiceGuard-AI-API / InvoiceGuard-AI-ADMIN）共用相同規範。

## 1. 分支策略

| 分支 | 用途 | Vercel 部署 | 規則 |
|---|---|---|---|
| `main` | 正式環境 | **Production** | 禁止直接 push，只接受來自 `develop` 或 `hotfix/*` 的 PR |
| `develop` | 整合測試 | Preview（可綁定固定測試網域） | 功能分支合併目標 |
| `feature/<issue>-<描述>` | 新功能 | Preview | 從 `develop` 建立 |
| `fix/<issue>-<描述>` | 錯誤修正 | Preview | 從 `develop` 建立 |
| `hotfix/<描述>` | 正式環境緊急修正 | Preview | 從 `main` 建立，合併回 `main` 與 `develop` |
| `chore/<描述>`、`docs/<描述>` | 設定 / 文件 | Preview | 從 `develop` 建立 |

分支名稱用小寫英文與 `-`，例：`feature/12-invoice-upload`、`fix/31-invoice-term`。

## 2. Commit 訊息（Conventional Commits）

格式：

```
<type>(<scope>): <摘要>

<詳細說明（選填）：為什麼要改、影響範圍>

<關聯 issue（選填）：Closes #12>
```

| type | 用途 |
|---|---|
| `feat` | 新功能 |
| `fix` | 修正錯誤 |
| `refactor` | 重構（不改變功能） |
| `perf` | 效能改善 |
| `style` | 格式調整（不影響邏輯） |
| `test` | 新增 / 修改測試 |
| `docs` | 文件 |
| `chore` | 建置、套件、設定 |
| `db` | 資料庫結構 / migration（API 專案） |

- `scope` 為模組名稱，例：`invoice`、`auth`、`cron`、`ui`
- 摘要用繁體中文或英文皆可，**一次 commit 只做一件事**，摘要不超過 50 字

範例：

```
feat(invoice): 新增發票上傳 API
fix(cron): 修正跨年度發票期別計算錯誤
db(invoice): invoices 新增 risk_score 欄位
docs: 補充排程規則說明
```

## 3. Pull Request

1. PR 標題沿用 commit 格式，例：`feat(invoice): 新增發票上傳 API`
2. 依 `.github/pull_request_template.md` 填寫說明與檢查清單
3. 至少 **1 位** 成員 review 通過才能合併
4. 確認 Vercel Preview 部署成功並實際操作過
5. 合併方式：功能分支 → `develop` 使用 **Squash merge**；`develop` → `main` 使用 **Merge commit**

## 4. 跨專案異動

| 異動類型 | 影響 | 順序 |
|---|---|---|
| API 回應格式 | 前台 | 1. API 專案完成並合併（保持向下相容）<br>2. 前台調整，PR 說明註明相依的 API PR<br>3. 不相容變更依 API 專案 `docs/API_CONVENTIONS.md` 升版 |
| 資料表結構 | 後台 | 1. API 專案修改 Model + migration，取得個別授權後由管理者在隔離測試庫驗證及安排受控 migration<br>2. 後台同步 `app/db/models/` 對應檔案<br>（詳見 API 專案 `app/db/README.md` 第 9 節） |

## 5. 禁止事項

- 提交 `.env`、金鑰、密碼、個資或真實發票資料
- 提交 `.venv/`、`__pycache__/`、`tmp/` 內容
- 對 `main` / `develop` 使用 `git push --force`
- 修改已合併的 migration 版本檔（API 專案）


## AI 交付前必查

1. 執行本站 `python -B scripts/check_project.py`、相關 pytest 與 Ruff；有三站 clone 時，以 `--project-root` 再比對共同契約與 ORM。
2. 檢查已追蹤及未追蹤檔案；`git diff --check` 不涵蓋未追蹤檔案，不得據此推定全部檔案已掃描。
3. 不提交 `.env`、含值的本機設定、連線字串、Token、驗收存取碼、資料庫匯出、真實發票或暫存證據。
4. 回報改動檔案、測試與限制；若依使用者授權修正檢驗問題，將原因與結果記錄在 `docs/REVIEW_FIX_LOG.md`。
