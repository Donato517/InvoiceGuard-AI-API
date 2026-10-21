# API 設計規範 — InvoiceGuard-AI-API

> 前台網站（InvoiceGuard-AI）在**伺服器端**依此規範呼叫 API；瀏覽器不直接呼叫 API。
> 後台（InvoiceGuard-AI-ADMIN）以自有 DB 模組直接存取資料庫，不經過 API。修改格式前需先通知前台。

## 1. 路徑規劃

| 前綴 | 用途 | 呼叫者 | 驗證 |
|---|---|---|---|
| `/health` | 健康檢查 | 監控 / 部署驗證 | 無 |
| `/api/v1/auth/*` | 登入 / 登出 / 目前使用者 | 前台伺服器 | 部分需登入 |
| `/api/v1/*` | 前台功能（只能存取自己的資料） | 前台伺服器 | Bearer token |
| `/api/cron/*` | 排程觸發（不公開、不列入文件） | Vercel Cron | `CRON_SECRET` |

## 2. URL 命名

| 規則 | ✓ 正確 | ✗ 錯誤 |
|---|---|---|
| 資源用**複數名詞** | `/invoices` | `/invoice`、`/getInvoices` |
| 多個單字用 **kebab-case** | `/audit-logs` | `/auditLogs`、`/audit_logs` |
| 用路徑參數指定單筆 | `/invoices/{id}` | `/invoices?id=1` |
| 巢狀最多兩層 | `/invoices/{id}/items` | `/users/{id}/invoices/{id}/items` |
| 非 CRUD 動作用子路徑動詞 | `POST /invoices/{id}/analyze` | `POST /analyzeInvoice` |
| 篩選 / 排序 / 分頁用 query | `/invoices?status=flagged&page=2` | `/invoices/flagged/page/2` |

## 3. HTTP 方法與狀態碼

| 方法 | 用途 | 成功狀態碼 |
|---|---|---|
| `GET` | 查詢 | `200` |
| `POST` | 新增 / 執行動作 | `201`（新增）/ `200`（動作） |
| `PATCH` | 部分更新 | `200` |
| `PUT` | 整筆取代（少用） | `200` |
| `DELETE` | 刪除 | `204`（無內容） |

| 狀態碼 | 意義 |
|---|---|
| `400` | 業務規則不允許（例：狀態不可轉換） |
| `401` | 未登入 / token 無效 |
| `403` | 已登入但沒有權限 |
| `404` | 資源不存在（或無權存取時也回 404，避免洩漏資源存在） |
| `409` | 資料衝突（例：重複上傳同一張發票） |
| `422` | 請求參數格式錯誤 |
| `500` | 系統未預期錯誤 |
| `502` | 外部服務（AI、財政部平台）呼叫失敗 |

## 4. 資料格式

| 項目 | 規則 | 範例 |
|---|---|---|
| 編碼 | UTF-8 JSON | |
| 欄位命名 | **snake_case**（與 Python 命名一致，前台直接使用） | `invoice_number` |
| 時間 | ISO 8601，含時區，以 UTC 回傳 | `"2026-10-21T02:00:00Z"` |
| 日期 | `YYYY-MM-DD` | `"2026-10-21"` |
| 金額 | **字串**（避免浮點誤差），前台顯示時再格式化 | `"1234.50"` |
| 列舉 | 小寫英文代碼，前台自行對應中文 | `"flagged"` |
| 空值 | 回傳 `null`，不省略欄位 | `"tax_amount": null` |

## 5. 回應格式

### 5.1 成功 — 直接回傳資料本體

```json
{ "id": 1, "invoice_number": "AB12345678", "status": "pending" }
```

### 5.2 分頁

查詢參數：`page`（預設 1）、`page_size`（預設 20，上限 100）

```json
{
  "items": [{ "id": 1, "invoice_number": "AB12345678" }],
  "total": 125,
  "page": 1,
  "page_size": 20
}
```

### 5.3 錯誤 — 一律使用此格式（由 `app/core/exceptions.py` 統一產生）

```json
{
  "error": {
    "code": "INVOICE_NOT_FOUND",
    "message": "找不到這張發票",
    "details": null
  }
}
```

- `code`：給程式判斷用，UPPER_SNAKE_CASE，**一經發布不可更改**
- `message`：給使用者看的中文訊息，可直接顯示
- `details`：額外資訊（例如 422 時的欄位錯誤清單），可為 `null`

## 6. 錯誤代碼

### 6.1 通用代碼

| code | HTTP | 說明 |
|---|---|---|
| `BAD_REQUEST` | 400 | 一般業務錯誤 |
| `UNAUTHORIZED` | 401 | 未登入 / token 無效 / 排程驗證失敗 |
| `FORBIDDEN` | 403 | 沒有權限 |
| `NOT_FOUND` | 404 | 資源或路由不存在 |
| `METHOD_NOT_ALLOWED` | 405 | HTTP 方法不支援 |
| `CONFLICT` | 409 | 資料衝突 |
| `VALIDATION_ERROR` | 422 | 參數格式錯誤，`details` 為欄位錯誤清單 |
| `INTERNAL_ERROR` | 500 | 系統未預期錯誤 |
| `EXTERNAL_SERVICE_ERROR` | 502 | 外部服務失敗 |

### 6.2 業務代碼

格式：`<模組>_<原因>`，新增時登記於此表。

| code | HTTP | 說明 |
|---|---|---|
| `INVOICE_NOT_FOUND` | 404 | 發票不存在（範例，實作時確認） |
| `INVOICE_DUPLICATED` | 409 | 同一使用者重複上傳同一張發票（範例，實作時確認） |

## 7. 驗證

- 前台伺服器在 `Authorization` 標頭帶 `Bearer <access_token>`
- access token 由前台存在使用者瀏覽器的 **httpOnly cookie**，瀏覽器端 JavaScript 讀不到
- token 過期回 `401`，前台清除 cookie 並導向登入頁

## 8. 版本管理

- 路徑以 `/api/v1` 標示版本
- **不相容變更**（刪欄位、改型別、改語意）才升 `v2`，並與 `v1` 並存一段時間
- **相容變更**（新增欄位、新增端點）直接在 `v1` 進行
