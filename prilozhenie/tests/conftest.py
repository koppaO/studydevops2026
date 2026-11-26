"""Корень приложения и SECRET_KEY задаются до импорта api.main."""

import os
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# KAFKA_BOOTSTRAP не задаём: пустое значение значит, что API в Kafka не ходит.
# ENABLE_DOCS не меняем.
os.environ["SECRET_KEY"] = "test-secret"

import api.main as api_main  # noqa: E402


def reset_storage() -> None:
    """Сбрасывает память процесса между тестами."""
    api_main.users.clear()
    api_main.courses.clear()
    api_main.orders.clear()
    api_main.refresh_blacklist.clear()
    api_main.hits.clear()
    api_main.http_requests.clear()
    api_main.seq["course"] = 0
    api_main.seq["order"] = 0


@pytest.fixture(autouse=True)
def clean_storage():
    reset_storage()
    yield
    reset_storage()


@pytest.fixture
def client(clean_storage):
    with TestClient(api_main.app) as test_client:
        yield test_client
