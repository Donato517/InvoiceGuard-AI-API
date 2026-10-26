"""模組名稱：tests.unit.test_module_boundaries；功能說明：測試離線限制與未接線服務拒絕操作。"""

import importlib
import socket
from typing import Any

import pytest

from app.core.module_errors import ModuleNotReadyError
from app.integrations.storage_client import get_storage_client
from app.services.data_service import get_data_service
from app.services.file_service import get_file_service


@pytest.mark.parametrize("factory", [get_storage_client, get_file_service, get_data_service])
def test_unwired_services_fail_closed(factory: Any) -> None:
    with pytest.raises(ModuleNotReadyError, match="尚未提供真實資料或檔案操作"):
        factory()


@pytest.mark.parametrize(
    "module_name",
    [
        "app.integrations.vercel",
        "app.integrations.storage_client",
        "app.db.contracts",
        "app.services.file_service",
        "app.services.data_service",
    ],
)
def test_imports_do_not_connect(module_name: str) -> None:
    importlib.reload(importlib.import_module(module_name))


def test_unit_test_network_guard_is_active() -> None:
    with pytest.raises(AssertionError, match="禁止外部網路"):
        socket.create_connection(("example.invalid", 443))


def test_loopback_database_socket_is_also_blocked() -> None:
    with socket.socket() as connection, pytest.raises(AssertionError, match="禁止外部網路"):
        connection.connect(("127.0.0.1", 5432))


def test_dns_resolution_is_blocked() -> None:
    with pytest.raises(AssertionError, match="禁止外部網路"):
        socket.getaddrinfo("company.example.invalid", 443)


def test_udp_network_is_blocked() -> None:
    with (
        socket.socket(type=socket.SOCK_DGRAM) as connection,
        pytest.raises(AssertionError, match="禁止外部網路"),
    ):
        connection.sendto(b"synthetic", ("127.0.0.1", 53))


def test_internal_socketpair_still_works() -> None:
    first, second = socket.socketpair()
    first.close()
    second.close()
