"""
模組名稱：tests.unit.test_shared_integrations
功能說明：ADMIN 與 API 共用的 integration 模組（Vercel 模組與 AI 模組）必須逐位元組相同。
注意事項：
    - 兩站各有一份相同的本測試；只在兩站同在一個根目錄時比對，單站 checkout（例如 CI）明確 skip。
    - 修改其中一站的這些檔案時，必須把同一份內容複製到另一站，否則本測試失敗。
"""

import hashlib
from pathlib import Path

import pytest

from app.core.config import Settings

SITE_ROOT = Path(__file__).resolve().parents[2]
SITES = ("InvoiceGuard-AI-ADMIN", "InvoiceGuard-AI-API")
# 2026-10-29 使用者核定 ADMIN 也使用 AI 模組；supabase_storage.py 自 2026-10-25 起即為兩站相同檔案
SHARED_FILES = (
    "app/integrations/supabase_storage.py",
    "app/integrations/chat_models.py",
    "app/integrations/document_ai.py",
    "app/integrations/gemini.py",
    "app/integrations/groq.py",
)


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("relative", SHARED_FILES)
def test_shared_integration_exists_in_this_site(relative: str) -> None:
    assert (SITE_ROOT / relative).is_file()


@pytest.mark.parametrize("relative", SHARED_FILES)
def test_shared_integration_is_identical_in_admin_and_api(relative: str) -> None:
    # 依本站 APP_NAME 判斷角色（Clone 資料夾名稱不同也能執行），兄弟站以固定 Repository 名稱尋找
    this_site = Settings.model_fields["APP_NAME"].default
    assert this_site in SITES
    sibling = SITE_ROOT.parent / (SITES[1] if this_site == SITES[0] else SITES[0])
    if not (sibling / "app").is_dir():
        pytest.skip("單站 checkout 沒有兄弟 Repository；兩站比對只在同一根目錄時執行")
    assert _digest(SITE_ROOT / relative) == _digest(sibling / relative), (
        f"{relative} 在 ADMIN 與 API 不同；請把修改同步到兩站"
    )
