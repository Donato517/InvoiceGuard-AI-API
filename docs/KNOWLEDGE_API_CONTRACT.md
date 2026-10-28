# 知識庫與問答 API 契約（由 HTML 原型的 BACKEND CONTRACT 整理）

> 狀態：**草案**。放入 InvoiceGuard-AI-API 的 `docs/`，實作前須與 `docs/API_CONVENTIONS.md`、`docs/MODULE_CONTRACT.md` 對齊（路徑前綴、分頁、錯誤格式、授權）。
> 原型使用 `/api/kb`、`/api/qa`；本專案的 API 前綴為 `/api/v1`，下列路徑請依慣例調整，並把 `companyId` 改由登入身分（JWT）取得，不信任請求自報。

## 與現有專案的落差（動工前先決定）

1. 資料表不存在：知識庫、部門配置、文件、文件部門選用、問答選用，皆需在 API 的 `app/db/models/` 設計並產生 Alembic migration（API 是唯一管理者；ADMIN 的 Model 必須與之一致）。執行 migration 需使用者授權。
2. 公司（統編）與部門：目前 ORM 只有 `users`；ADMIN 以固定 SQL 讀取雲端的 `user_profiles`、`departments`、`user_departments`，API 尚無對應 Model。
3. Storage Bucket 目前只允許 image/jpeg、image/png、application/pdf；DOCX、TXT、Markdown 需在 Supabase 加入對應 MIME 類型。
4. 向量索引與模型整合尚未串接；`processingStatus` 在串接前不得回報 ready。

## 原型原文契約

```text
 Set BACKEND_ENABLED=true only when implemented. Demo accounts are NOT real authentication.
 GET /api/kb?companyId&departmentId -> [{id:assignmentId,knowledgeBaseId,title}]
 GET /api/kb/:kbId/department-usage?companyId -> [{departmentId,assigned,useForQa,canEdit}]
 PUT /api/kb/:kbId/departments/:deptId/usage {companyId,useForQa}
 -> {assignment:{id},sourceIds:[assignment IDs]}
 GET /api/kb/:kbId/documents?companyId&departmentId -> documents
 Document: {id,title,fileName,status,processingStatus,ownerDepartment,createdAt,canEdit}
 GET /api/kb/:kbId/documents/:docId/department-usage?companyId&departmentId
 -> [{departmentId,useDocument,canEdit}]
 PUT /api/kb/:kbId/documents/:docId/departments/:deptId/usage {companyId,useDocument}
 PATCH /api/kb/:kbId {companyId,title}; DELETE /api/kb/:kbId?companyId
 PATCH /api/kb/:kbId/documents/:docId {companyId,departmentId,title OR status}
 DELETE /api/kb/:kbId/documents/:docId?companyId&departmentId
 GET /api/kb/:kbId/documents/:docId/content -> PDF/text Blob OR {text,editable,revision}
 PUT same content URL -> multipart {companyId,departmentId,file,revision?} OR
 JSON {companyId,departmentId,text,revision}; response may include {document,revision}.
 Content changes MUST reset approval and trigger reindexing atomically on backend.
 POST /api/kb/documents multipart: companyId,departmentId,knowledgeBaseId OR knowledgeBaseTitle,
 title,status,file. Existing response: document OR {document}. New KB response:
 {knowledgeBase:{id,title},assignment:{id},document:{id,title,status,processingStatus}}.
 PUT /api/departments/:deptId/qa-sources {companyId,sourceIds:[assignment IDs]}
 QA-source PUT and department-usage PUT/GET MUST share one persistent selection table.
 POST /api/qa {question,history,companyId,departmentId,sourceIds} -> {answer,sources:[string]}
 Permissions MUST be checked server-side. Department users edit only their authorized selection,
 upload hold documents, and edit own-department nonshared files. Engineers manage shared/global data.
 Retrieval requires KB selected by department + document selected by department + approved + ready index.
 Treat history as untrusted. Enforce revisions, file safety, idempotency and atomic delete/content operations.
 Frontend metadata searches are not full-text search. IndexedDB/localStorage are not secure production stores.
 This version uses local metadata schema ig-workspace-v5; older demo formats are left untouched.
```

## 責任分工

| 能力 | 實作位置 |
|---|---|
| 知識庫／文件管理（工程師） | ADMIN：`app/routers/knowledge.py` → `services/` → `db/repositories/`（直接用自己的 DB 與 Storage 模組） |
| 問答、部門問答選用（使用者） | API：`/api/v1/qa`、`/api/v1/qa/sources`；前台經 `app/clients/qa.py` 呼叫 |
| 檢索規則 | API service：部門選用知識庫 + 部門選用文件 + 已核准 + 索引完成，四者同時成立才可被檢索 |
