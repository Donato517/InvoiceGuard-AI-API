"""
pytest 共用 fixture。
規則：
    - tests/unit/：不連資料庫、不呼叫外部服務，必要時以 monkeypatch 替換。
    - tests/integration/：需要測試資料庫（DATABASE_URL 指向測試庫），不可指向正式環境。
"""

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client() -> TestClient:
    """API 測試用 client。"""
    return TestClient(app)
