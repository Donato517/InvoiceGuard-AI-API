"""本機 Show Case 草案接入既有結構版本鏈的離線檢查。"""

from pathlib import Path

from alembic.script import ScriptDirectory


def test_showcase_has_one_head_and_preserves_company_lineage() -> None:
    """解析版本定義即可核對鏈結，無需載入 env.py 或連線資料庫。"""
    directory = Path(__file__).resolve().parents[2] / "app/db/migrations"
    scripts = ScriptDirectory(str(directory))
    assert scripts.get_heads() == ["4c7c7c1d26b0"]
    showcase = scripts.get_revision("4c7c7c1d26b0")
    assert set(showcase.down_revision) == {"8ef487f17b06", "f5e7afb48888"}
    assert scripts.get_revision("8ef487f17b06").down_revision == "5e8b11d0a941"
    assert scripts.get_revision("5e8b11d0a941").down_revision == "7c1d4e9a2b30"
