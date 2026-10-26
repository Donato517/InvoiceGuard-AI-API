"""
模組名稱：app.core.constants
功能說明：三站共用的公開網址與常數；三站同名檔案內容相同，由開發者／管理者直接填寫。
注意事項：
    - 只放公開值（網址、名稱、上限等）；密碼、Key、Token 等機密放雲端環境變數，不寫在這裡。
    - 名稱不與雲端環境變數同名（例如不用 API_BASE_URL、DATABASE_URL），兩者各自獨立。
    - 正式網址固定；本機網址依自己電腦填寫，修改後同步到另外兩站的同名檔案。
"""

# 正式平台網址（Vercel 雲端）
PRODUCTION: dict[str, str] = {
    "FRONTEND_URL": "https://invoice-guard-ai.vercel.app",
    "API_URL": "https://invoice-guard-ai-api.vercel.app",
    "ADMIN_URL": "https://invoice-guard-ai-admin.vercel.app",
}

# 本機開發網址（預設為 START.cmd 的 8080 共用別名；依自己電腦填寫）
LOCAL: dict[str, str] = {
    "FRONTEND_URL": "http://invoiceguard-ai.localhost:8080",
    "API_URL": "http://invoiceguard-ai-api.localhost:8080",
    "ADMIN_URL": "http://invoiceguard-ai-admin.localhost:8080",
}

# 三站顯示名稱（瀏覽器分頁標題、頁首）；各站 app/constants.py 的 SITE_NAME 取自這裡
SITE_NAMES: dict[str, str] = {
    "FRONTEND": "InvoiceGuard AI",
    "ADMIN": "InvoiceGuard 後台",
    "API": "InvoiceGuard API",
}

# 網站圖示（favicon）：相對於各站 app/static/ 的路徑；換圖時替換該檔或改這裡
SITE_ICON = "icons/favicon.svg"

# 搜尋引擎：三站可互相連結，但一律不出現在 Google 等搜尋結果。
# 頁面 <meta name="robots"> 與各站 vercel.json 的 X-Robots-Tag 標頭都使用此值。
ROBOTS_POLICY = "noindex, nofollow"
# robots.txt 不封鎖抓取：搜尋引擎必須讀得到頁面上的 noindex 才會排除；
# 若以 Disallow 封鎖，搜尋引擎讀不到 noindex，被其他網站連結時仍可能列出網址。
ROBOTS_TXT = "User-agent: *\nAllow: /\n"


def current() -> dict[str, str]:
    """取得目前環境適用的網址：Vercel 雲端用正式網址，其餘（本機）用開發網址。

    判斷沿用 app.core.config 的 Vercel 執行標記，不另外讀取環境變數。

    Returns:
        FRONTEND_URL、API_URL、ADMIN_URL 三個網址的複本；修改回傳值不影響本檔設定。
    """
    # 延遲匯入：config 模組也可能引用本檔的正式網址，避免循環匯入
    from app.core.config import settings

    return dict(PRODUCTION if settings.is_vercel else LOCAL)
