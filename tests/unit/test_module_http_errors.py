"""模組名稱：tests.unit.test_module_http_errors；功能說明：僅在測試 App 驗證錯誤不反射輸入。"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.exceptions import register_exception_handlers
from app.schemas.common import ErrorResponse
from app.schemas.data import InvoiceCreate


def test_contract_validation_does_not_echo_secret_values() -> None:
    app = FastAPI()
    register_exception_handlers(app)

    @app.post("/test-contract-only")
    def validate_invoice(data: InvoiceCreate) -> dict[str, bool]:
        return {"valid": True}

    response = TestClient(app).post(
        "/test-contract-only",
        json={"SUPABASE_SECRET_KEY": "synthetic-confidential-marker", "total_amount": "invalid"},
    )

    assert response.status_code == 422
    assert "synthetic-confidential-marker" not in response.text
    error = ErrorResponse.model_validate(response.json()).error
    assert error.code == "VALIDATION_ERROR"
    assert all(set(detail) == {"loc", "type", "msg"} for detail in error.details)
