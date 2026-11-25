import pytest
from fastapi.testclient import TestClient

from src.main import app

client = TestClient(app)


def test_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "Hello, QA!"}


@pytest.mark.parametrize(
    ("name", "price"),
    [
        ("Laptop", 999.99),
        ("Mouse", 25.5),
        ("Keyboard", 79.0),
    ],
)
def test_create_item(name, price):
    response = client.post("/items/", json={"name": name, "price": price})
    assert response.status_code == 201
    assert response.json()["message"] == f"Item {name} created"
    saved = client.get(f"/items/{name}")
    assert saved.status_code == 200
    assert saved.json() == {"name": name, "price": price}


def test_create_duplicate_item():
    item_data = {"name": "Laptop", "price": 999.99}
    first = client.post("/items/", json=item_data)
    assert first.status_code == 201
    second = client.post("/items/", json=item_data)
    assert second.status_code == 400
    assert second.json()["detail"] == "Item already exists"


def test_get_item():
    client.post("/items/", json={"name": "Laptop", "price": 999.99})
    response = client.get("/items/Laptop")
    assert response.status_code == 200
    assert response.json() == {"name": "Laptop", "price": 999.99}


def test_get_non_existent_item():
    response = client.get("/items/Nonexistent")
    assert response.status_code == 404
    assert response.json()["detail"] == "Item not found"


def test_get_all_items():
    client.post("/items/", json={"name": "Laptop", "price": 999.99})
    client.post("/items/", json={"name": "Mouse", "price": 25.5})
    response = client.get("/items/")
    assert response.status_code == 200
    payload = response.json()
    assert isinstance(payload, list)
    by_name = {item["name"]: item["price"] for item in payload}
    assert by_name == {"Laptop": 999.99, "Mouse": 25.5}


def test_delete_item():
    client.post("/items/", json={"name": "Laptop", "price": 999.99})
    response = client.delete("/items/Laptop")
    assert response.status_code == 200
    assert response.json() == {"message": "Item Laptop deleted"}
    gone = client.get("/items/Laptop")
    assert gone.status_code == 404
    again = client.delete("/items/Laptop")
    assert again.status_code == 404
    assert again.json()["detail"] == "Item not found"


def test_delete_non_existent_item():
    response = client.delete("/items/Nonexistent")
    assert response.status_code == 404
    assert response.json()["detail"] == "Item not found"
