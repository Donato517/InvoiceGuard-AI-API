"""
模組名稱：app.routers.robots
功能說明：提供 /robots.txt；內容取自三站共用的 app/core/constants.py。
路由：GET /robots.txt
注意事項：
    - 三站不出現在搜尋結果，靠頁面 <meta name="robots"> 與 vercel.json 的 X-Robots-Tag（noindex）。
    - robots.txt 刻意不封鎖抓取，搜尋引擎才讀得到 noindex；原因見 app/core/constants.py。
"""

from fastapi import APIRouter
from fastapi.responses import PlainTextResponse

from app.core.constants import ROBOTS_TXT

router = APIRouter(tags=["robots"])


@router.get("/robots.txt", response_class=PlainTextResponse)
def robots_txt() -> str:
    """回傳 robots.txt 內容。"""
    return ROBOTS_TXT
