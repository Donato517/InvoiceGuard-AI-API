# 黃金測試集

> 2026-11-03。任何 Prompt、模型、前處理或欄位換算規則的變更，合併前都要用同一份清單重跑並比較。

## 組成

- 影像：`InvoiceGuard-AI-Other/新增100張發票_正確70張_錯誤30張_分類版/`（虛構、第二聯扣抵聯；**不放進 Git**）。
- 清單：[tests/golden/manifest.json](../tests/golden/manifest.json)，100 筆（正確 70、錯誤 30），含檔名、資料識別、原分類、錯誤代碼。
- 人工標註：目前只有 **3 張**逐欄對照原圖標註（`annotated: true`：0100、0096、0057）；其餘 67 張正確發票只有檔名的字軌號碼。
  標註值不得由 AI 辨識結果回填（會變成自己考自己）；要擴充，請對照原圖人工逐欄填 `expected`，日期用西元（114 年＝2025）。
- 錯誤發票（30 張）屬於「應被攔截或留給人工」的案例，目前沒有標註；A06、B04 需公司／供應商主檔才能判斷。

## 指標（對應專案規劃的驗收指標）

| 指標 | 做法 |
|---|---|
| 欄位級 Exact Match | 每個標註欄位逐一比對；金額以數值比對（`14150.00`＝`14150`），國字大寫轉成數字比對 |
| 錯誤攔截率 | 錯誤欄位中，值為空（需人工填）或有警示指到該欄位的比例 |
| 未攔截的錯誤 | 錯了又沒被攔截的欄位清單——最危險，要優先看 |
| 整張全對率 | 標註欄位全對的發票比例 |

規劃建議的關鍵欄位門檻是 ≥ 90%（最終依黃金集難度調整）；**目前樣本太少，不能宣稱達標**。

## 離線評分（不連任何服務）

評分邏輯在 [scripts/golden_eval.py](../scripts/golden_eval.py)，由 `tests/unit/test_golden_eval.py` 驗證（`pytest` 會跑）。

## 對真實 API 執行（有成本與副作用）

會呼叫 Document AI 與 Groq，並對該 API 所連的 DB／Storage 寫入辨識紀錄與影像（本機 API 連的是正式環境），
未提交的影像約 1 小時後清理，辨識紀錄不會自動刪（清除方式見 [RUNBOOK_DELETE_TEST_INVOICES.md](RUNBOOK_DELETE_TEST_INVOICES.md)）。

```bash
# Token：先用測試帳號登入取得 session_token，存成單行文字檔（不要貼進命令列、聊天或 Git）
python -m scripts.golden_eval run \
  --api-base http://127.0.0.1:8000 \
  --token-file ~/golden-token.txt \
  --images-dir "<…/正確發票資料夾>" \
  --manifest tests/golden/manifest.json \
  --annotated-only --limit 3 \
  --report /tmp/golden-report.json \
  --yes-write
```

- 不帶 `--yes-write` 一律拒絕。`--limit`、`--pause`（預設每張間隔 2 秒）控制成本與速率。
- 單張耗時約 20～24 秒（接近 API 的 25 秒總預算），70 張約 25～30 分鐘。
- 報告只含評分與欄位名稱，不含 Token、影像或完整回應。

## 已知限制

- 標註只有 3 張，統計意義不足；國字大寫規則（位名一律視為空位）依 10 張抽樣調整，有過擬合風險。
- 只涵蓋第二聯扣抵聯、單頁、單一買受人；沒有手機拍攝的反光、傾斜、模糊樣本。
- 黃金集需按「開票人或拍攝批次」分組切分，目前清單沒有這個欄位。
