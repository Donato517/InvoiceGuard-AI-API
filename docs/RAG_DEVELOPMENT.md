# RAG 開發說明

> 適用 ADMIN 與 API；兩站此檔內容相同，修改時手動同步。最後更新：2026-11-05（查無資料次數、同名文件版本、段落多樣化、回答文字；ADMIN 與 API 已同步）。
> 結構依據：`InvoiceGuard_AI_PostgreSQL_Schema_v1_8_PortableAuth_draft.sql` 與 `InvoiceGuard_AI_v1_7_to_v1_8_ALTER.sql`。程式涵蓋 ADMIN 檔案庫、知識庫組合、資訊部問答與操作視窗，不新增 ORM Model、migration 或套件。
> 正式 DB 已套用 v1.8（2026-10-31 本機 ADMIN 連正式 DB 已讀到 v1.8 欄位與移轉後的關聯）。新版程式尚未提交、尚未部署，Vercel 仍是舊程式。

## 目前狀態

| 項目 | 狀態 |
|---|---|
| 向量模組 `app/integrations/vertex_embedding.py` | 已完成，兩站相同；ADMIN 已接索引與問題向量，API 尚未接 RAG 功能 |
| 對話模組 `GroqClient`（`purpose="rag"`） | 已完成，ADMIN 已接資訊部知識庫問答；API 尚未接 RAG 功能 |
| Storage 模組 | 已支援 `from_settings(bucket=...)`，`get` 可指定 `timeout_seconds`；RAG 使用私有 bucket `rag` |
| RAG 資料表 | 程式依 v1.8；正式 DB 已套用 v1.8，新版程式尚未部署。6 份法規已於 2026-11-01 依新規則重新索引 |
| `rag_chunks.embedding` | v1.8 Schema 固定 `vector(1536)`，本批未查正式 DB |
| `rag_file_department_usage` | 已停用，保留表與既有資料，程式不再讀寫 |
| 獨立檔案庫、檔案組合、複製與移除確認 | ADMIN 已實作並做離線測試；不代表正式 DB 或 Storage 驗收 |
| `/knowledge` 權限 | 已接新登入，功能代碼 `rag.manager` 對應 DB 的 `rag_manager` |
| 審核、部門多選、切段、索引、v1.8 檢索、`/knowledge` 接 DB 與資訊部知識庫問答 | ADMIN 已實作並以離線替身驗證；API 尚未接 RAG 功能，正式服務未驗證 |

## 各步驟使用的模型

| 步驟 | 使用 | 說明 |
|---|---|---|
| 文字擷取 | TXT／MD：程式；DOCX：標準函式庫 `zipfile`＋XML；PDF：`DocumentAIClient` | 都不需新增套件，見「PDF 文字擷取」「DOCX 文字擷取」 |
| 切段 | 程式 | 不需要模型 |
| 文件與問題轉向量 | `gemini-embedding-2` | `VertexEmbeddingClient`，走 Agent Platform（原 Vertex AI） |
| 依檢索結果產生回答 | `openai/gpt-oss-120b` | `GroqClient.chat(..., purpose="rag")`，分初稿與修正兩輪 |
| 回答備援 | `GEMINI_MODEL`（預設 `gemini-3.8-flash`） | `VertexChatClient`，走 Agent Platform 與服務帳號；Groq 無法回應時使用，僅 ADMIN |
| 問答的問題理解（部門問答與資訊部測試共用） | `openai/gpt-oss-20b` | `purpose="default"`，由程式解析回覆的 JSON；失敗時只查原問題 |

- gpt-oss 是對話模型，不能產生向量。既有 Claude 回報：2026-10-30 實測 `gpt-oss-120b` 回 400 `does not support embeddings`，Groq 帳號也沒有 embedding 模型。
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
| `timeout_seconds` | 含取得權杖的總秒數；未傳時 25 秒。ADMIN 函式上限 60 秒 |

使用時要注意：

- **一筆失敗即整批失敗**：不回傳部分結果，也不自動重試。重試由 `rag_jobs` 處理。
- **超長文字直接報錯**：超過 8,192 token 回 `embedding_invalid_input`，不會截斷。切段要小於上限。
- **多筆處理**：此專案不能用 `batchEmbedContents`，模組以併發 `embedContent` 處理，同時最多 8 條。
- **重用用戶端**：同一個工作用同一個 client，權杖才能重用。
- **模型與維度要一致**：目前 v1.8 欄位固定 1536 維；換模型或維度須由專案負責人先確認 Schema 相容性並全部重算，不可只改設定或與舊向量混用。

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

### 既有實測回報（2026-10-30，本輪未重驗）

以下為 Claude／專案負責人的既有回報：ADMIN 與 API 各以自己的 Vercel 設定呼叫實際模組，只送合成文字。本輪不連線驗證這些數字。

| 項目 | ADMIN | API |
|---|---|---|
| 向量維度 | 1536 | 1536 |
| 100 段（每段 725 字） | 4.25 秒 | 4.09 秒 |
| 問題與相關句相似度 | 0.7948 | 0.7948 |
| 問題與無關句相似度 | 0.5795 | 0.5795 |
| 超過 8,192 token | `embedding_invalid_input` | `embedding_invalid_input` |

這只是小量測試，長時間配額上限和真實文件的檢索品質都還沒有驗證。

## PDF 文字擷取

PDF 使用現有的 `app/integrations/document_ai.py`，不需要新增解析套件，掃描檔也能辨識。

```python
from app.integrations.document_ai import DocumentAIClient, ProcessOptions

with DocumentAIClient.from_settings() as client:
    result = client.process(content, "application/pdf", timeout_seconds=25)
    # 超過 15 頁時分段；結果頁數少於要求的頁數，代表已到文件結尾
    second = client.process(
        content,
        "application/pdf",
        timeout_seconds=25,
        options=ProcessOptions(pages=tuple(range(16, 31))),
    )

result.text   # 擷取的文字
result.pages  # 各頁資料
```

- **頁數上限**：單次最多 15 頁。超過回 `document_ai_invalid_input`，detail 含 `PAGE_LIMIT_EXCEEDED`。
- **時間上限**：ADMIN 函式上限 60 秒；索引總預算 50 秒（`INDEX_TOTAL_BUDGET_SECONDS`，含讀檔、擷取、向量，另保留 4 秒寫入），每批辨識 20 秒（`PDF_TIMEOUT_SECONDS`）。
- **長文件（2026-11-04，上限 45 頁）**：先辨識第 1～15 頁；剛好 15 頁時**同時**送出 16～30、31～45 與第 46 頁探測。前一批未滿 15 頁代表已到結尾，超出結尾的批次回空頁或 `document_ai_invalid_input` 都視為結尾；第 46 頁有內容標為 `rag_pdf_page_limit`（請拆檔）。各批以 `merge_ocr_results` 合併（後批行位置加偏移），項次標示可跨批接續。超出結尾頁碼的實際回應與 45 頁耗時尚未實測。
- **空文字**：擷取不到文字時標 `parse_status = failed`，不可標成 `ready`。

既有 Claude 回報（本輪未重驗）：2026-10-30 以 ADMIN 的 Vercel 設定實測，內容為合成的中文影像 PDF：

| 文件 | 結果 | 秒數 |
|---|---|---|
| 3 頁 | 成功，可辨識中文 | 4.98 |
| 15 頁 | 成功，可辨識中文 | 13.67 |
| 16 頁，不分段 | `PAGE_LIMIT_EXCEEDED` | 12.08 |
| 20 頁，第 1～15 頁 | 成功 | 18.58 |
| 20 頁，第 16～20 頁 | 成功 | 15.58 |
| 20 頁，第 16～30 頁（超過結尾） | 成功，回 5 頁 | 15.61 |

## DOCX 文字擷取

- `rag_indexing_service.extract_docx_text`：讀 `word/document.xml`，依文件順序取段落與表格（每列一行、儲存格以 Tab 分隔），支援 `w:tab`、`w:br`、內容控制項（`w:sdt`）；刪除的修訂（`w:delText`）不取。
- 解壓後 `document.xml` 上限 20 MB（`DOCX_MAX_XML_BYTES`，防壓縮炸彈）；壞檔、缺本文或過大標 `rag_docx_invalid`。
- Word 自動編號存在 numbering.xml，不會帶出；頁首頁尾、註腳、文字方塊目前不讀。

## 環境與前置條件

以下雲端設定／費用狀態沿用既有回報，本輪未查詢；使用前仍由專案負責人確認。

- **設定**：沿用 `GOOGLE_CLOUD_PROJECT_ID` 和 `GOOGLE_SERVICE_ACCOUNT_JSON`。`VERTEX_EMBEDDING_MODEL`、`VERTEX_EMBEDDING_DIMENSIONS` 有預設值，Vercel 和 START 不用新增設定。
- **GCP**：專案已啟用 Agent Platform API，服務帳號已有 Agent Platform User 權限（`roles/aiplatform.user`）。
- **Storage**：私有 bucket `rag`，允許 `application/pdf`、`text/plain`、`text/markdown` 與 DOCX（`application/vnd.openxmlformats-officedocument.wordprocessingml.document`）。
- **不使用 `GEMINI_API_KEY`**：這把 Key 目前無法用於 Gemini API。
- **費用**：GCP 專案目前使用 300 美金試用額度。額度用完或試用到期時，同專案的 Document AI 與向量都會停止。

## 分工

| 類別 | 處理者 |
|---|---|
| 資料庫結構與 ALTER | 專案負責人 |
| 共用模組（`app/integrations/`）與 AI 設定 | 專案負責人 |
| E 功能代碼註冊與功能目錄資料 | 專案負責人 |
| Vercel 環境變數、START／SETUP、GCP、Supabase bucket | 專案負責人 |
| 功能開發 | 開發者 |

開發時發現上面前四類要修改，請停下來回報，不要自行修改。

## 資料規則（v1.8 第一階段）

### 獨立檔案與知識庫組合

- `rag_files` 是獨立檔案，索引 `rag_chunks` 與工作 `rag_jobs` 仍以檔案為單位。
- `rag_knowledge_base_files` 是知識庫 × 檔案；同一檔案可供多個知識庫共用。加入、移除或複製關聯不重新索引、不複製原檔。
- 新程式不讀寫 `rag_files.knowledge_base_id`；新增時不提供該欄位，DB 為 NULL。既有值只供 ALTER 一次性移轉，程式一律以關聯表為準。
- `rag_knowledge_bases.file_count` 只由 DB Trigger 維護，程式與表單不可寫入。最後一份關聯移除時，Trigger 同交易清除全部門的 `use_for_qa`；重新加入檔案不恢復舊指派。
- `rag_file_department_usage` 維持停用，表與資料保留，程式不讀寫。
- SQL 已定義 `rag_function_knowledge_bases`；本階段不接功能指派畫面或功能聊天。

### 審核、權限與指派

- 新知識庫與新檔案固定待審查，包含資訊部建立者。
- 知識庫核准與檔案核准互相獨立；核准知識庫須 `file_count >= 1`。檔案核准、暫停及建立索引維持資訊部，檔案須 ready 才能核准。
- 全部門可見檔案清單、來源、審核、索引狀態及引用知識庫；畫面不用「生效」表示核准。
- 檔案改名、內容替換及刪除只限上傳部門或資訊部，不能由「可管理某個知識庫」取得共用檔案修改權。
- 知識庫管理部門或資訊部可加入其他部門的已核准檔案，或移除關聯；在知識庫內新上傳時，可同交易建立待審查檔案與關聯。
- 用語：開放部門＝`can_read`；部門指派＝`use_for_qa`。可多選、整組取代、空清單取消；只能設定目前部門，資訊部可代設。指派須知識庫已核准、啟用、非空且部門可讀。
- 退回知識庫只清除該知識庫的全部門指派，其他知識庫保留。
- 所有寫入路由先由 `module.check` 檢查 CREATE／EDIT／DELETE，身分與目前部門由已驗證 identity 取得。

### 刪除、替換與複製

- 刪除知識庫只刪本體、部門配置與關聯，不建立 Storage 用戶端、不刪原檔、段落或工作。
- 檔案有任何知識庫引用時禁止刪除，錯誤列出引用名稱；解除全部關聯後，才刪 DB 檔案及其索引／工作，提交成功後清除 Storage 物件。
- 檔案有任何已核准知識庫引用時禁止替換內容，提示上傳新檔案。其餘情況同交易版本 +1、撤銷核准、parse_status=uploaded、新增 reindex 工作。
- 替換只鎖檔案，不鎖知識庫，避免與「加入檔案」（先知識庫後檔案）互相等待。替換與核准知識庫同時發生時，知識庫可能先變成已核准，但檔案的核准已被撤銷，重新核准前不會被檢索。
- 移除關聯先顯示影響；最後一份須明示將收回所有部門指派。確認提交時重新鎖定並核對檔案數，組合已變更就要求重新確認。
- 複製知識庫建立新的待審查組合，只複製檔案關聯；不複製開放部門、部門指派或功能指派。建立者部門沿用既有的可讀／可管理配置，`use_for_qa=false`。

### 上傳欄位與路徑

| 欄位 | 規則 |
|---|---|
| source_type | 必填 government_regulation／company_policy／operations_manual／mixed／other；新上傳拒絕 unclassified |
| effective_date_status | 必填 known／unknown／not_applicable |
| effective_date | known 必須有合法日期；unknown、not_applicable 必須為 NULL，不以上傳日代替 |
| source_note | 選填發布單位、網址、版本；mixed、other 提示建議填寫 |
| content_sha256 | 伺服器計算原始檔 SHA-256，不接受表單自報；相同內容提示既有名稱並改用加入關聯 |

- 檔案先存私有 bucket `rag`，再同交易寫檔案、索引工作及可選的知識庫關聯。DB 失敗後先確認資料表沒有指向新物件才清除；提交可能已成功只是沒收到確認，所以資料表已指向它或查不到狀態時都保留，最多留下孤兒物件。替換內容也一樣。
- 新路徑為 `{上傳部門代碼}/RAG_{台灣時間YYYYMMDDHHMMSS}_{rag_file_id}.{副檔名}`；部門代碼由伺服器以 identity 的部門 UUID 查 DB，不能由表單或知識庫代碼決定。替換內容時路徑跟著檔案的上傳部門，資訊部代為替換或該部門已停用都一樣；檔案沒有上傳部門時拒絕替換，請上傳新檔案。
- 替換內容的路徑在 `rag_file_id` 後加 8 碼亂數（`RAG_{時間}_{rag_file_id}_{亂數}.{副檔名}`）。時間只到秒，同秒替換若共用物件會覆寫現行原檔，失敗清除時還會刪掉它。
- 既有檔案不搬，讀檔依資料表 `storage_path`。舊資料 content_sha256 為 NULL 時，上傳／替換前會在 DB 交易外盡力補雜湊：逐筆提交，版本未變才寫入；讀不到的略過，DB 失敗就停止，總預算 8 秒用完也停止，都不擋本次上傳。每次讀取的等待上限是剩餘預算（`get` 的 `timeout_seconds`，連線與每次接收各自計算）。尚未補到雜湊的舊檔可能暫時比對不到重複內容，下一次上傳會繼續補。補齊所需時間尚未以正式資料驗證。
- 相同雜湊的寫入以交易 advisory lock 序列化，寫入前再次查重；檔案完全相同不能藉並行上傳建立重複資料。

### 索引與檢索

- 索引開始記下 file_version，呼叫 Storage／模型時不持有索引 DB 交易；寫回前鎖定並核對版本，相同才替換 chunks 並設 ready。
- 檔案與工作固定先鎖檔案、再鎖工作；開始索引、寫回結果與刪除檔案（連帶刪工作）都是同一順序。
- 掃描 PDF 使用既有 Document AI；無文字、不支援格式或超過既有限制時 failed，不可假設 ready。
- 知識庫批次索引、檔案計數及待索引查詢都走關聯表。同一檔案只保留一組索引；重新索引會影響所有引用它的知識庫。
- 部門檢索範圍：知識庫 approved、is_active、file_count >= 1；目前部門 can_read 且 use_for_qa；文件 is_approved 且 parse_status=ready。向量另限相同 embedding_model。
- 資訊部知識庫問答只允許 approved、is_active、file_count >= 1，可同時勾選多個知識庫，不要求部門開放或指派；文件仍須已核准且 ready。
- 向量、關鍵字、資訊部測試四種查詢均先彙整授權範圍內不重複檔案，再查段落，避免多對多 JOIN 在 LIMIT 前產生重複；保留所有授權來源知識庫名稱。
- 問答維持 TOP_K=8 與既有條文比對、合併及引用檢查；測試先以 uuid[] 清單限定知識庫，再依檔案分組。測試 SQL 不查 rag_department_access，部門版 SQL 與 HAS_QA_ACCESS 不變。
- ask_test 只限資訊部，流程為「防呆 → 思考問題 → 撈取知識庫 → 分析 → 回應」。先驗證問題、身分、去重後非空知識庫清單、每個知識庫狀態及選填的啟用部門，通過後才建立對話用戶端並理解問題，再呼叫向量。
- 問題理解以 `purpose="default"`（20B）、最多 1600 tokens、6 秒，取得 type（題型）、concepts（關鍵名詞）、need 與 queries；推理內容也計入上限，2026-11-01 實測 800 會以 `groq_failed/length` 失敗。不用 Groq 的 JSON 模式：2026-11-01 實測 5 題有 2 題被該模式以 `json_validate_failed` 拒絕，改由程式解析回覆。GroqError、JSON 解析失敗、欄位型別錯誤或 need 空白時改用原問題，不中斷問答，並把固定原因顯示在測試說明（不含問題或模型回覆）。queries 去空白、去重、排除原問題及超過 100 字的句子，最多 3 句。type 只接受 definition／comparison／procedure，其他值（含 other）視為未分類；concepts 最多 3 個；兩者格式不符時略過，不算理解失敗。定義題、比較題要求每個關鍵名詞各寫一句查詢，比較題才不會只查到一邊。
- 原問題加上 queries 在同一次 `embed_texts(task="query")`，每個向量各檢索一次，知識庫清單完全相同；先依 `(rag_file_id, chunk_index)` 去重、保留最小距離並排序，再沿用距離門檻、merge_hits 與 TOP_K=8。條文比對仍只用原問題，不從 queries 增加條文比對。
- **部門不影響檢索範圍，但會影響查詢內容**：名稱由伺服器讀取，提供理解及回答角度，因此可能找到不同段落；不能擴大到未勾選的知識庫。**ask（部門問答，供之後 `/knowledge_qa/` 使用）與 ask_test 走同一套流程**（2026-11-03）：ask 以已驗證身分的目前部門讀出部門名稱，帶入理解與回答（【提問部門】），先理解問題再以 `retrieval.search(extra_queries=...)` 多查詢檢索（同一批轉向量，各查一次後依段落去重、保留最小距離）；範圍仍是目前部門指派的知識庫。開發部門問答入口時直接呼叫 `rag_qa_service.ask`，不要另寫提示詞或檢索。
- 回答使用 `purpose="rag"`（120B）、最多 4000 tokens。整題上限 56 秒（Vercel 與 START 閘道都在 60 秒切斷），每輪回答最多 25 秒，其中 Groq 最多 10 秒。回答分兩輪：第一輪寫初稿；第二輪把段落、問題、初稿與程式檢查發現的問題一起交給模型，逐句對照來源、適用情況、角色、增補、事實與遺漏後輸出最終回答。兩輪都是通用規則，不針對個別問題客製。模型回 NO_ANSWER 時不進第二輪；時間不足或第二輪無法完成時回服務暫時無法使用，第二輪未通過檢查時回未通過檢查訊息，沒有完成兩輪的初稿一律不顯示。理解、向量與回答共用整題截止時間，理解與模型回覆超過期限不採用，檢索後已超時就回服務暫時無法使用；DB 查詢與驗權不在此預算內，只會扣掉後面的時間。同一題 Groq 已額度不足時，第二輪直接用 Vertex；Groq 用戶端無法建立時也改用 Vertex。Groq 無法回應、額度不足、回覆空白或被截斷時，靜默改用 `VertexChatClient`（Agent Platform、服務帳號、`GEMINI_MODEL`，不用 `GEMINI_API_KEY`），兩者走相同檢查，使用者看不出差別，只有測試說明會寫出原因；兩者都失敗才回服務暫時無法使用。引用或步驟來源不合格不改用備援。問題向量沿用 5 秒上限，但不超過整題剩餘時間。
- **題型與回答格式（2026-11-03）**：理解結果的題型以【題型】加入回答提示詞。定義題、比較題用「概念格式」：白話說明 → 主要差別（定義題為「重點」）→ 跟你的工作有什麼關係 → 依據，讓沒接觸過條文的同仁先懂概念；其他用下述「步驟格式」。白話說明是唯一可以用一般常識的地方，只能解釋名詞的意思與制度目的，不可寫數字、比例、期限、義務、例外或條號；程式檢查白話說明出現數字、比例或條項款卻沒有來源編號時丟棄回答（`plain_facts_without_source`），第二輪檢查也會把這類內容移到有來源的區塊或刪除。主要差別／重點與「跟你的工作有什麼關係」每點都要有來源（沿用步驟來源檢查）。這些只改提示詞與程式檢查，不需重新切段或重算向量。
- 問答給不熟悉規定的同仁使用：步驟格式先寫適用情況，再列「你可以這樣做」的步驟，資料不足時列「目前還需要確認」，最後列「依據」。提示詞只放通用規則，不針對個別問題或事件客製，操作內容來自知識庫文件。規定只來自段落；某個處理方法只能用在原文寫明的情況，同一段落有多條規定也不可混用；查不到只能說資料不足以確認，不可說沒有規定。條、項、款編號只能照段落原文；段落行首的「〔第N條第M項〕」標示該項開始，段落開頭的「（接續第N條第M項）」表示延續該條項，未標示項次時，即使問題提到第幾項，也不可斷定內容屬於該項，只寫到條並說明未標示。項次由索引時標示，模型是否照用仍靠提示詞。有 need 才加入【問題重點】，有部門才加入【提問部門】；部門只是工作背景，不得編造部門內部流程。程式檢查確認編號都在範圍內、操作區塊每段都有來源（縮排的子清單算在上一步）、提到的條號出現在對應的來源段落（只在同一步或同一條列內對應，取同一行後面最近的來源，沒有時取該處最近的來源；「目前還需要確認」區塊不比對）；這些只驗結構，不驗內容是否正確，適用情況與角色由第二輪核對。
- 無相關段落或模型回 NO_ANSWER 時回查無資料訊息，有 need 時另列勾選的知識庫名稱；程式無法判斷問題屬於哪個部門，所以這個訊息不指定部門。引用錯誤、編號步驟沒有來源或 token 截斷時回未通過檢查訊息，不說查無資料；服務失敗維持原處理。依文件回答時的洽詢窗口由 `contact_name` 依目前啟用部門判斷（名稱含財務、會計、財會，或代碼以 finance、accounting 開頭），新增或改名部門不必改程式，都沒有時用通稱。
- 每題只傳當題問題與段落，不帶前文；問題、need、queries 與回答不保存、不記錄，不改開放部門或部門指派。理解結果不新增畫面欄位、面板或統計。
- 未接重新分析或連續對話；條文定位只補項次標示，本批不改內容去重或文件分散。
- **檢索補強（2026-11-04，第二批）**：①文字比對除「第 X 條／章／節」外，加上「附件 X」（中文／阿拉伯數字）與「代號 NN」（與「代號」二字同組，數字前後不可緊接其他數字），仍受 MAX_REFERENCE_GROUPS 限制；②四種檢索 SQL 帶出 `rag_files.effective_date`，段落標頭加「（生效日 YYYY-MM-DD）」，問答與題庫的來源也顯示生效日（舊版排除見 11-05 第三批：以同名標題判斷，Schema 仍無取代關係欄位）；③`QaAnswer.retrieved_titles` 記錄送給模型的段落來源文件，題庫多一層「檢索命中」，可分辨檢索或回答層的問題。皆不需改 Schema、不需重新索引。
- **檢索補強（2026-11-05，第三批）**：①**同名文件版本**：標題去掉括號內年度／版次／修正字樣（例「（113年修正）」）後相同、且生效日都已知的多份文件，只把目前有效（生效日 ≤ 今天且最新）的一份送給模型；生效日未知的不判斷，尚未生效的照常使用並在段落標頭標「尚未生效」（`superseded_file_ids`）。②**段落多樣化**：向量段落同一文件最多 `MAX_CHUNKS_PER_FILE`＝3 段，其他文件的段落優先，不足 `TOP_K` 時才補回；章節條文比對的段落不受限（`merge_hits`）。皆不需改 Schema、不需重新索引。
- **查無資料次數（2026-11-05，#5）**：回答為查無資料（沒有相關段落，或模型判斷段落不足）時，檢索範圍內每個知識庫當日（台灣日期）在 `rag_no_answer_stats` 加 1：資訊部測試為勾選的知識庫，部門問答為該部門選用問答的知識庫。只記次數，不存問題、回答或使用者；服務失敗、未通過檢查與題庫測試不記錄；獨立短交易，失敗只記錯誤類別並略過，不影響回答。知識庫列表（資訊部）顯示「近 30 天查無資料」。正式 DB 已有此表（Schema v2.0），不需 Migration；資料表不存在時列表顯示 0。
- **回答文字（2026-11-05）**：概念格式的「白話說明：」標題只供模型分段與程式檢查（`plain_facts_without_source` 仍以此標題找出白話說明段落），通過檢查後以 `hide_plain_label` 拿掉回答開頭的這個標題再顯示，說明文字保留；其他區塊標題不變。固定結尾縮短為「以上依知識庫整理，請以原文為準；不確定時可問{contact}。」。題庫的概念格式判斷改看「主要差別／重點」。只改顯示文字，不需重新切段或重算向量。
- **題庫測試（2026-11-04）**：資訊部專用 `GET /knowledge/eval`，題目在 `app/schemas/rag_eval_cases.py`（擬題待財務審核，改題不需改程式）。`POST /knowledge/eval/run` 一次執行一題（`rag_eval_service.run_case` → `ask_test`，範圍為全部已核准、啟用、非空的知識庫，不帶部門），「全部執行」由 main.js 依序送出。比對寬鬆：服務失敗即未通過；應查無資料的題目須查無資料；其餘依序檢查有依文件回答（查無資料時只報這項）、引用文件標題含預期字串、回答含關鍵字、題型格式（概念＝主要差別／重點、步驟＝你可以這樣做；11-05 起白話說明標題不顯示）。結果不保存；每題都會呼叫模型並消耗 token。問答頁有入口連結。

### 畫面與路由

- `GET /knowledge/files`：全部檔案、名稱搜尋、來源、生效日、審核與索引狀態、上傳部門及引用清單。
- `POST /knowledge/files/upload`：獨立上傳，可帶 knowledge_base_id 同流程建立關聯。
- 檔案操作統一 `/knowledge/files/{file_id}/rename|content|download|delete|status|index`；`GET /knowledge/files/{file_id}/edit` 已移除，回 404。舊 `/knowledge/{kb_id}/documents/{doc_id}/...` 與舊上傳 POST `/knowledge/documents` 回 404。
- `GET /knowledge/{kb_id}/documents`：知識庫的檔案，可由檔案庫多選加入、上傳新檔或預覽移除影響。
- `POST /knowledge/{kb_id}/files`：加入關聯；`POST /knowledge/{kb_id}/files/{file_id}/remove`：確認後移除，攜帶 expected_count。確認改用視窗，不另開頁面；同一網址的 GET 回 405。
- `POST /knowledge/create` 建立空的待審查知識庫；`POST /knowledge/{kb_id}/copy` 複製檔案組合。
- 列表顯示 file_count、開放部門與「部門指派（可多選）」；空庫不在可指派或資訊部可測清單。
- 靜態 files 路由先於 /{kb_id} 註冊；全部路由保留 require_knowledge_access 與明確操作檢查。
- 移除關聯、列表刪除知識庫、檔案改名／刪除，沿用共用 `_confirm_modal.html` 與既有 dialog 開關，開啟／取消不換頁，不新增 JS。表單一般 POST，成功後 303 回原清單更新資料；知識庫刪除規則錯誤回列表，檔案改名／刪除錯誤回檔案管理完整頁面；內容替換仍回內容頁。
- 移除關聯的視窗顯示影響與剩餘檔案數，最後一份警告將收回所有部門指派。被引用檔案的刪除視窗列出知識庫名稱並提示先移除關聯，不顯示確認刪除；伺服器仍重驗引用。
- require_knowledge_access 仍先檢查查看權限，另以 Action.DELETE 取得 `knowledge_can_delete`；刪除被拒只隱藏按鈕，不影響查看。知識庫刪除須可管理且有刪除權限；檔案改名限上傳部門或資訊部，刪除另需刪除權限，所有 POST 仍逐次檢查原有操作與資料規則。知識庫編輯頁與檔案內容頁保留。
- 列表「在使用中」以部門指派（`use_for_qa`）計算；只開放未指派不算使用。
- `GET /knowledge/chat` 是資訊部專用的「知識庫問答」，一頁一個對話；打開時預選登入者目前的部門，並勾選該部門指派（use_for_qa）的知識庫；列表連結也只顯示給資訊部。非資訊部對本頁、choices 與 ask 均回 403，全部保留 require_knowledge_access。
- 右側選部門（單選，可不選）與知識庫（可多選，至少一個）。比較效果由操作者切換選擇、按「清除對話」自行評估，畫面不提供情境或比較功能。
- 選了部門才分「已指派／未指派」，依該部門的 use_for_qa，兩區都可勾；不選部門時沒有指派可言，列出全部知識庫。不以 can_read 或 use_for_qa 限制範圍。
- `GET /knowledge/chat/choices?department_id=...&knowledge_base_id=...` 切換部門時重新分組並保留勾選，所有 ID 先驗 UUID。
- `POST /knowledge/chat/ask` 接 question、多值 knowledge_base_id、選填 department_id；伺服器再次驗可用狀態。向量或對話服務失敗回 400 並顯示訊息，輸入框保留問題；找不到相關規定是正常回答，回 200。對話只留在當前畫面，重新載入即清除。
- `/knowledge_qa/` 尚未實作，新版 ADMIN 暫無一般部門聊天入口。ask 保留依部門指派的服務路徑（已含問題理解、題型格式與【提問部門】，入口直接呼叫即可），未由本批路由使用；API／前台問答仍未接線。

### 上線順序

1. v1.8 ALTER 已執行，完成既有關係移轉、Trigger、計數及 View。
2. 新版程式上線前，不得用 Vercel 上的舊版刪除知識庫或新增檔案，避免 Storage 誤刪或漏建關聯。
3. 新版 ADMIN 通過檢驗後上線並人工驗證。新程式上線後不要重跑 ALTER，否則舊欄位的已解除關聯會被補回。

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

- **權限**：`/knowledge` 由 `require_knowledge_access` 檢查目前部門的 `rag_manager` 查看權限。部門要在部門內容頁勾選功能才進得去。
- **寫入路由**：接 DB 時要另外呼叫 `module.check(identity, KNOWLEDGE, Action.EDIT, Target(department_id))`，操作依路由選 `CREATE`、`EDIT` 或 `DELETE`。
- **目前使用者**：`request.state.knowledge_identity`，`reviewed_by` 這類欄位寫入它的 `user_id`（UUID），目前部門是 `selected_department_id`。
- **資訊部判斷**：沿用既有 `request.state.is_it_workspace`（目前選取部門）；寫入另驗操作權限，service 驗證資訊部／目前部門範圍。本批不修改登入及授權共用模組。
- **檔案位置**：沿用私有 bucket rag，新檔依上傳部門代碼產生路徑，既有 storage_path 不改。
- **資料夾**：Storage 的資料夾不用先建立，第一個檔案上傳時就會出現。
- **知識庫代碼**：`knowledge_code` 由程式產生，只用小寫英數與連字號，建立後不可變更；知識庫名稱與新檔案儲存路徑分開管理。
- **切段**：沿用現有 `rag_indexing_service.py` 常數與條文分段規則，本批不調整切段。
- **項次標示**：法規 PDF 把項次印在內文左側，OCR 文字會把這些數字擠成孤立的一串。`restore_item_numbers` 依各行座標把數字對回同一列的內文，在每項第一行標示「〔第N條第M項〕」，六角括號只由程式補上，用來和原文引用的條項分開；長條文切開後，續段開頭標「（接續第N條第M項）」，條項只取條標題與程式標示，不從內文引用推斷，並依段落真正開始的位置判斷（重疊切段的開頭還屬於前一段）；切段不會切開程式標示。章、節切換時清除所屬條號，換頁重印同一條號時項次接續。只採用 PDF 實際印出的數字：同一條必須從 1 連號到至少 2，否則整條不標；條以外的數字也不標；沒有座標的文件與 TXT／MD 維持原文。規則變更後要重新建立索引才生效。2026-11-01 已重建 6 份法規，共 371 個項次（條號與續段標示要再重建一次才生效）；時限表與作業要點沒有項次，未重建。
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

至少涵蓋：

1. 共用檔案在多個所選知識庫每段只回一次，保留全部來源知識庫；四種 SQL 先取不重複檔案再 LIMIT。
2. 刪除知識庫不刪共用檔、索引、工作或 Storage；仍有引用的檔案不可刪除，解除後可刪。
3. 已核准知識庫引用的檔案不可替換；知識庫管理者可改關聯，不能改別部門共用檔案。
4. 空庫不可核准、不可部門指派；管理測試拒絕待審查、停用及空庫，排除未核准文件。
5. 複製只帶檔案關聯、新組合待審查、建立者可管理但不自動部門指派。
6. 來源類型、生效日狀態、合法日期、原始 SHA256 重複、舊雜湊補齊失敗不擋上傳、已驗證部門路徑，以及同秒替換不覆寫現行原檔。
7. 上傳檔案與關聯／工作同交易成功或回滾，失敗清除新物件；程式不寫 file_count 或舊 knowledge_base_id。
8. 新路由全部驗權、舊路由 404；全部門清單、來源欄位、移除影響確認、開放部門及多選指派。
9. 原有版本保護、索引失敗、越權及部門多選回歸；正式 DB Trigger、View、鎖定及 Storage 行為仍需人工驗證。
10. 問答三路由只限資訊部；四種部門／知識庫組合、多值 UUID、分組跟著所選部門、保留勾選、直接 POST 不可用知識庫的伺服器攔截。
11. 問題理解的 20B／不用 JSON 模式／4 秒時限、回覆前後多餘文字、格式錯誤與 GroqError 退回原問題並顯示原因、queries 限制、同批向量、多查詢去重及最小距離；部門可改查詢但知識庫清單不變；ask 不加理解。
12. 新提示詞的問題重點與部門角度、4000 tokens、每輪 25 秒；無段落或 NO_ANSWER 的有／無 need 訊息，引用錯誤、步驟缺來源及截斷回未通過檢查訊息；服務失敗 400 顯示訊息並保留問題，不 commit 或呼叫寫入 repository。
13. 三類操作視窗的開啟／取消／一般 POST、刪除按鈕權限與直接 POST 拒絕、引用檔案不顯示確認刪除、移除 expected_count／最後一份警告、完整錯誤頁、移除的兩個確認頁不再提供。
14. 多知識庫綁定 list／uuid[]、共享文件的段落與全部來源名稱、來源與名稱 HTML 跳脫。

## 尚未定案

| 項目 | 目前做法 | 影響 |
|---|---|---|
| 超過 45 頁的 PDF | 標 `failed`（`rag_pdf_page_limit`），請拆成多份上傳 | 45 頁內已支援（兩階段併發），更長需改為跨請求分次處理 |
| 向量索引 | 不建 HNSW，先用精確比對 | 資料量變大時再評估 |
| 文件退回是否寫原因 | 依 v1.5，文件只有核准／暫停；原因只在知識庫層 | 若要寫原因需加欄位 |
| 索引由誰觸發 | 暫由畫面手動觸發，不做排程 | 排程另行決定 |
