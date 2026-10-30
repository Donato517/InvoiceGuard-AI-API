# RAG 開發說明

> 適用 ADMIN 與 API；兩站此檔內容相同，修改時手動同步。最後更新：2026-10-30。
> 資料規則以 `InvoiceGuard_AI_PostgreSQL_Schema_v1_5_PortableAuth_draft.sql` 為準。`KNOWLEDGE_API_CONTRACT.md` 與 `08_G` 需求單較早撰寫，表名與條件若不同，以 v1.5 為準。

## 目前狀態

| 項目 | 狀態 |
|---|---|
| 向量模組 `app/integrations/vertex_embedding.py` | 已完成，兩站相同，尚未接線功能 |
| 對話模組 `GroqClient`（`purpose="rag"`） | 已完成，RAG 尚未接線 |
| Storage 模組 | 已支援 `from_settings(bucket=...)`；RAG 專用 bucket 尚未確認 |
| RAG 資料表 | v1.5 已規劃；正式 DB 是否已套用 v1.5 尚未確認 |
| `rag_chunks.embedding` | 尚未固定維度，預定改為 1536 |
| 審核、部門選用、切段、索引、檢索、`/knowledge` 接 DB | 尚未開發 |

## 各步驟使用的模型

| 步驟 | 使用 | 說明 |
|---|---|---|
| 文字擷取 | 程式 | 尚未實作；ADMIN 目前沒有 PDF／DOCX 解析套件 |
| 切段 | 程式 | 不需要模型 |
| 文件與問題轉向量 | `gemini-embedding-2` | `VertexEmbeddingClient`，走 Agent Platform（原 Vertex AI） |
| 依檢索結果產生回答 | `openai/gpt-oss-120b` | `GroqClient.chat(..., purpose="rag")` |

- gpt-oss 是對話模型，不能產生向量。2026-10-30 實測 `gpt-oss-120b` 回 400 `does not support embeddings`，Groq 帳號也沒有 embedding 模型。
- RAG 回答不使用 `GeminiClient.chat`。

## 向量模組用法

```python
from app.integrations.vertex_embedding import EmbeddingError, VertexEmbeddingClient

with VertexEmbeddingClient.from_settings() as client:
    # 文件段落
    batch = client.embed_texts(chunks, task="document", title=file_title, timeout_seconds=20)
    # 使用者問題
    query = client.embed_texts([question], task="query", timeout_seconds=5)

batch.vectors     # tuple，順序與 chunks 相同
batch.model       # 寫入 rag_chunks.embedding_model
batch.dimensions  # 1536
```

| 參數 | 說明 |
|---|---|
| `texts` | 原文清單，不可為空，每筆不可空白。前綴由模組加上，呼叫端不要自己加 |
| `task` | `document`（文件段落）或 `query`（使用者問題）；索引和檢索要各用對應的值 |
| `title` | 文件標題，只用於 `document`；未傳時模組使用 `title: none` |
| `timeout_seconds` | 含取得權杖的總秒數；未傳時 25 秒。ADMIN 函式上限 30 秒 |

使用時要注意：

- **一筆失敗即整批失敗**：不回傳部分結果，也不自動重試。重試由 `rag_jobs` 處理。
- **超長文字直接報錯**：超過 8,192 token 回 `embedding_invalid_input`，不會截斷。切段要小於上限。
- **多筆處理**：此專案不能用 `batchEmbedContents`，模組以併發 `embedContent` 處理，同時最多 8 條。
- **重用用戶端**：同一個工作用同一個 client，權杖才能重用。
- **模型與維度要一致**：換模型或維度須全部重算，不可與舊向量混用。

### 錯誤代碼

| 代碼 | 意思 | 建議處理 |
|---|---|---|
| `embedding_not_configured` | 專案、模型或服務帳號設定不合法 | 回報專案負責人 |
| `embedding_invalid_input` | 輸入無效或超過模型上限 | 檢查切段，不要重試同一份內容 |
| `embedding_auth_failed` | 服務帳號無法取得權杖 | 回報專案負責人 |
| `embedding_denied` | 沒有權限或 API 未啟用 | 回報專案負責人 |
| `embedding_not_found` | 模型不存在或專案無法使用 | 回報專案負責人 |
| `embedding_quota_exceeded` | 配額或額度不足 | 工作保留，稍後重試 |
| `embedding_timeout` | 超過總時間預算或服務逾時 | 工作保留，稍後重試 |
| `embedding_unreachable` | 無法連線 | 工作保留，稍後重試 |
| `embedding_failed` | 服務錯誤或回應格式不符 | 記錄代碼，稍後重試 |

`EmbeddingError.detail` 只含 Google 的狀態代碼，可以記錄；文件內容不要寫進 `rag_jobs.error_message`。

### 實測紀錄（2026-10-30）

ADMIN 與 API 各以自己的 Vercel 設定呼叫實際模組，只送合成文字。

| 項目 | ADMIN | API |
|---|---|---|
| 向量維度 | 1536 | 1536 |
| 100 段（每段 725 字） | 4.25 秒 | 4.09 秒 |
| 問題與相關句相似度 | 0.7948 | 0.7948 |
| 問題與無關句相似度 | 0.5795 | 0.5795 |
| 超過 8,192 token | `embedding_invalid_input` | `embedding_invalid_input` |

這只是小量測試，長時間配額上限和真實文件的檢索品質都還沒有驗證。

## 環境與前置條件

- **設定**：沿用 `GOOGLE_CLOUD_PROJECT_ID` 和 `GOOGLE_SERVICE_ACCOUNT_JSON`。`VERTEX_EMBEDDING_MODEL`、`VERTEX_EMBEDDING_DIMENSIONS` 有預設值，Vercel 和 START 不用新增設定。
- **GCP**：專案已啟用 Agent Platform API，服務帳號已有 Agent Platform User 權限（`roles/aiplatform.user`）。
- **不使用 `GEMINI_API_KEY`**：這把 Key 目前無法用於 Gemini API。
- **費用**：GCP 專案目前使用 300 美金試用額度。額度用完或試用到期時，同專案的 Document AI 與向量都會停止。

## 分工

| 類別 | 處理者 |
|---|---|
| 資料庫結構與 ALTER | 專案負責人 |
| 共用模組（`app/integrations/`）與 AI 設定 | 專案負責人 |
| Vercel 環境變數、START／SETUP、GCP、Supabase bucket | 專案負責人 |
| 功能開發 | 開發者 |

開發時發現上面前三類要修改，請停下來回報，不要自行修改。

## 資料規則（v1.5）

### 知識庫審核

- 新知識庫固定 `pending`，包含資訊部自己建立；記錄 `submitted_by`、`submitted_department_id`。
- 核准：`approval_status = approved`，寫入 `reviewed_by`、`reviewed_at`。
- 退回：`approval_status = rejected`，寫入 `reviewed_*` 與 `review_comment`，同一交易清除所有部門的 `use_for_qa`。
- 重新送審：回到 `pending`，更新 `submitted_*`，清空 `reviewed_*`。

### 文件

- 新上傳固定 `is_approved = false`，包含資訊部上傳。
- 新文件要替上傳部門建立 `rag_file_department_usage`（`use_document = true`）與 `rag_jobs`。
- 內容變更時同一交易：`file_version + 1`、`is_approved = false`、清空 `approved_*`、`parse_status = uploaded`、新增 `rag_jobs`（`reindex`）。
- `parse_status` 是索引進度，與核准互相獨立。

### 部門選用

- 只能選 `approved` 且 `is_active` 的知識庫，且需 `can_read`。
- 一個部門同時只能選一個知識庫，由 `ux_rag_department_access_qa` 保證。切換時同一交易先關舊、再開新。

### 索引

- 開始處理時記下 `file_version`；呼叫模型期間不持有 DB 交易。
- 寫入前鎖定 `rag_files` 並核對版本，不符就丟棄結果。
- 同一交易刪舊 chunks、寫新 chunks、填 `embedding_model`、設 `parse_status = ready`。
- 掃描檔、空文字、不支援格式：`parse_status = failed`，`error_message` 放固定代碼，不可標成 `ready`。
- 不用 Vercel 請求結束後的背景 thread 處理工作。

### 檢索

五項都成立才納入：

1. 知識庫 `approved` 且 `is_active`
2. 部門 `use_for_qa`
3. 文件在該部門 `use_document`
4. 文件 `is_approved`
5. `parse_status = ready`

權限以已驗證的 `user_id` 和目前部門查 `v_user_department_rag_access`，不接受請求自報。只比對 `embedding_model` 相同的 chunks。

## 開發慣例

- **分層**：Router 不直接呼叫模組或 DB。Service 控制交易並呼叫 `VertexEmbeddingClient`，repository 不 commit。
- **DB 存取**：沿用 `department_repository.py` 的固定 SQL 寫法，不新增 ORM Model 或 migration。
- **向量寫入與比對**：不需要 `pgvector` Python 套件，以文字轉型即可。下面的寫法尚未在正式 DB 實測：

```sql
-- 寫入
CAST(:embedding AS extensions.vector)
-- 比對（距離越小越相似）
embedding OPERATOR(extensions.<=>) CAST(:query_embedding AS extensions.vector)
```

- **登入身分**：`/knowledge` 目前的 `require_admin` 拿到整數 ID，寫不進 `reviewed_by` 這類 UUID 欄位。改用 `invoices.py` 的 `module.identity`／`module.check` 寫法，寫入 `identity.user_id`。
- **檔案路徑**：`{knowledge_base_id}/RAG_{台灣時間YYYYMMDDHHMMSS}_{rag_file_id}.{副檔名}`。
- **切段**：起始值約 800 字、重疊 100 字，放常數，依實測調整。
- **新增套件**：先回報；只用純 Python 套件。
- **檢索放置**：`KNOWLEDGE_API_CONTRACT.md` 把檢索放在 API，前台問答也走 API。ADMIN 的檢索 service 要寫成不依賴畫面，日後才能用在 API。

### 測試

測試一律離線，不呼叫正式 DB、Storage、Google 或 Groq。本機 ADMIN 連的是正式環境，不要用它做寫入測試。

Service 接受注入的用戶端，測試時用替身：

```python
from app.integrations.vertex_embedding import EmbeddingBatch


class FakeEmbedding:
    def embed_texts(self, texts, *, task="document", title=None, timeout_seconds=None):
        vectors = tuple((0.0,) * 1536 for _ in texts)
        return EmbeddingBatch(vectors=vectors, model="synthetic-model", dimensions=1536)
```

至少涵蓋：越權、版本不符、掃描檔不可 `ready`、一個部門只能選一個知識庫、檢索五項條件。

## 尚未定案

| 項目 | 目前做法 | 影響 |
|---|---|---|
| `rag_chunks.embedding` 固定維度 | 待 ALTER，由專案負責人執行 | 建立 HNSW 索引前必須完成 |
| 文件退回是否寫原因 | 依 v1.5，文件只有核准／暫停；原因只在知識庫層 | 若要寫原因需加欄位 |
| 索引由誰觸發 | 暫由畫面手動觸發，不做排程 | 排程另行決定 |
| RAG 專用 bucket | 待確認名稱與允許的檔案類型 | 真實上傳前需要 |
