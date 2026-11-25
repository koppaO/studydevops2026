import pytest

from src.main import items_db


@pytest.fixture(autouse=True)
def clear_items_db():
    """Сбрасывает items_db перед каждым тестом и после него."""
    items_db.clear()
    yield
    items_db.clear()
