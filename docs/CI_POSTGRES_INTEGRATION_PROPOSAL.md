# 提案：CI 執行 PostgreSQL 整合測試與 Alembic 線上模式驗證

> 2026-11-03。已依本提案在 `.github/workflows/project-checks.yml` 新增獨立 `integration` Job（**待 CI Runner 驗證**：本機只能用相同指令模擬，尚未在 GitHub Actions 實際執行）。與提案草稿的差異：容器密碼為每次執行產生的臨時值並遮罩；就緒檢查用 TCP；設定 `ISOLATED_REQUIRE_INTEGRATION=1` 與 `ISOLATED_REQUIRE_ALEMBIC_ONLINE=1`；最後以 JUnit 檢查必要測試確實通過、只允許已知的占位測試被略過。

## 現況

- `project-checks.yml` 只有一個 job：`check_project`、`pytest`、`ruff`。沒有 PostgreSQL，`tests/integration` 在 CI 全部略過（沒有任何環境變數）。
- Alembic `env.py` 強制 TLS（`resolve_ssl_mode`），GitHub Actions 的 `services: postgres` 預設沒有 TLS，所以線上模式測試在那種服務上會被略過（或在 `ISOLATED_REQUIRE_ALEMBIC_ONLINE=1` 時失敗）。

## 實際做法

以 `.github/workflows/project-checks.yml` 的 `integration` Job 為準（不在此文件重複範例，避免過期）：臨時隨機密碼並遮罩、TLS 容器僅綁 `127.0.0.1`、TCP 就緒檢查、`ISOLATED_REQUIRE_*` 變數、JUnit 必要測試驗證。

## 影響（請先確認）

| 項目 | 影響 |
|---|---|
| 共用檔案 | 只改 API 的 `.github/workflows/project-checks.yml`（新增 job）；ADMIN、前台的 CI 不受影響。 |
| 執行時間 | 約多 1 分鐘（拉映像＋測試）。 |
| 外部下載 | CI 會拉 Docker Hub 的 `postgres:15`（固定標籤；要更嚴格可改固定 digest）。 |
| 機密 | 不需要任何 GitHub Secret；密碼為每次執行以 `openssl rand` 產生並遮罩的一次性值，容器只綁 `127.0.0.1`，job 結束即銷毀。 |
| 分支保護 | 若要把 `integration` 設為必要檢查，需 Repo 管理者設定；建議先觀察幾次穩定後再設。 |
| 失敗模式 | `ISOLATED_REQUIRE_ALEMBIC_ONLINE=1` 讓「沒有 TLS 所以沒驗到」變成失敗，避免靜默跳過。 |
| 範圍限制 | 驗證的是 v1.8 衍生**測試基線**＋重送 Migration；**不是**正式 DB 驗證，也不是 Alembic baseline。 |
