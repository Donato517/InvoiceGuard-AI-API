"""
模組名稱：app.services.invoice_few_shot
功能說明：提供台灣三聯式發票多模態 Few-Shot 示範範例（手寫範例與點陣列印範例）。
使用方式：
    from app.services.invoice_few_shot import get_invoice_few_shot_examples
    examples = get_invoice_few_shot_examples()
注意事項：
    - 包含兩組典型三聯式統一發票真實樣本：
      1. 手寫開立發票（含公司章、國字大寫、勾選應稅）
      2. 點陣/電子列印三聯式發票
    - 影像二進位檔與對應的標註 JSON 於首次呼叫時載入並快取於記憶體，避免重複讀取磁碟。
"""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_SAMPLES_DIR = Path(__file__).resolve().parent / "few_shot_samples"

_SAMPLE_CONFIGS = (
    {
        "image_filename": "sample_1_handwritten.jpg",
        "json_filename": "sample_1_handwritten.json",
        "mime_type": "image/jpeg",
    },
    {
        "image_filename": "sample_2_printed.jpg",
        "json_filename": "sample_2_printed.json",
        "mime_type": "image/jpeg",
    },
)


@lru_cache(maxsize=1)
def get_invoice_few_shot_examples() -> tuple[dict[str, Any], ...]:
    """載入多模態 Few-Shot 發票範例（影像 bytes、MIME 類型與對應模型輸出 JSON 字典）。

    Returns:
        包含各範例 content、mime_type 與 reply 的唯讀元組。
    """
    examples: list[dict[str, Any]] = []
    for config in _SAMPLE_CONFIGS:
        image_path = _SAMPLES_DIR / config["image_filename"]
        json_path = _SAMPLES_DIR / config["json_filename"]
        if not image_path.is_file() or not json_path.is_file():
            continue
        image_bytes = image_path.read_bytes()
        reply_dict = json.loads(json_path.read_text(encoding="utf-8"))
        examples.append(
            {
                "content": image_bytes,
                "mime_type": config["mime_type"],
                "reply": reply_dict,
            }
        )
    return tuple(examples)
