"""
模組名稱：app.core.logging_config
功能說明：設定全域 logging 格式與等級。
注意事項：
    - Vercel 會收集 stdout / stderr 作為 Runtime Logs，因此只輸出到 console，不寫入檔案。
    - 各模組取得 logger 的方式統一為：logger = logging.getLogger(__name__)
    - 禁止記錄密碼、token、完整身分證號等敏感資料。
"""

import logging

from app.core.config import settings

LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup_logging() -> None:
    """初始化 root logger；DEBUG 模式輸出 DEBUG 等級，否則 INFO。"""
    logging.basicConfig(
        level=logging.DEBUG if settings.DEBUG else logging.INFO,
        format=LOG_FORMAT,
    )
