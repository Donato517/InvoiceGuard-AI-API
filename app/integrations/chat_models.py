"""
模組名稱：app.integrations.chat_models
功能說明：對話模組（Gemini、Groq）共用的訊息與回答資料型別。
注意事項：
    - role 接受 user、assistant、model（model 與 assistant 同義，各模組自行轉成供應商的角色名稱）。
    - raw_response 為供應商原始回應，不出現在 repr，避免日誌帶出整段內容。
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ChatMessage:
    """一則對話訊息；role 為 user、assistant 或 model。"""

    role: str
    text: str


@dataclass(frozen=True)
class ChatReply:
    """模型回答與用量；raw_response 為供應商原始回應。"""

    text: str
    model: str
    finish_reason: str
    prompt_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    raw_response: dict[str, Any] = field(repr=False)
