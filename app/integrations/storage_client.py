"""
模組名稱：app.integrations.storage_client
功能說明：檔案物件儲存（Vercel Blob）串接——上傳、取得下載網址、刪除。
相依設定：settings.BLOB_READ_WRITE_TOKEN
注意事項：
    - Vercel Function 的檔案系統不可長期保存檔案，使用者上傳的原始檔一律存到物件儲存。
    - 資料庫只存 file_key；下載網址需要時再產生。
"""

# TODO(JerryChien): upload(file_bytes, *, key, content_type) -> str   回傳 file_key
# TODO(JerryChien): get_download_url(file_key) -> str
# TODO(JerryChien): delete(file_key) -> None
