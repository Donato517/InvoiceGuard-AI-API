## 變更說明

<!-- 這個 PR 做了什麼、為什麼要做 -->

## 變更類型

- [ ] feat：新功能
- [ ] fix：修正錯誤
- [ ] refactor：重構（不影響功能）
- [ ] docs：文件
- [ ] chore：設定 / 套件 / 建置

## 關聯 Issue

<!-- 例：Closes #12 -->

## 測試方式

<!-- 如何驗證：執行了哪些測試、手動測了哪些情境 -->

## 檢查清單

- [ ] 程式碼備註符合 `docs/CODING_CONVENTIONS.md`
- [ ] `ruff check .` 與 `pytest` 通過
- [ ] 異動 Model 時：已同步更新 Schema 備註、異動紀錄、migration、`app/db/README.md`
- [ ] 新增環境變數時：已更新 `.env.example` 與 `app/core/config.py`
- [ ] 新增 / 修改排程時：已更新 `vercel.json` 與 `docs/ARCHITECTURE.md`
- [ ] API 格式變更時：已通知前台 / 後台並更新 `docs/API_CONVENTIONS.md`
- [ ] 沒有提交任何密碼、金鑰、`.env` 檔
