"""Сценарии каталога курсов через TestClient."""

from fastapi.testclient import TestClient

PASSWORD = "password123"


def _register(client: TestClient, username: str, role: str | None = None) -> None:
    payload = {
        "username": username,
        "email": f"{username}@example.com",
        "password": PASSWORD,
    }
    if role is not None:
        payload["role"] = role
    response = client.post("/register", json=payload)
    assert response.status_code == 201, response.text


def _login(client: TestClient, username: str) -> dict:
    response = client.post(
        "/login",
        json={"username": username, "password": PASSWORD},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["token_type"] == "bearer"
    return body


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _create_course(client: TestClient, token: str, title: str, price: int) -> int:
    response = client.post(
        "/courses",
        json={"title": title, "price": price},
        headers=_bearer(token),
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_register_and_login(client: TestClient):
    _register(client, "reg-user")
    tokens = _login(client, "reg-user")
    assert tokens["access_token"] != tokens["refresh_token"]


def test_me_without_token_is_401(client: TestClient):
    response = client.get("/me")
    assert response.status_code == 401


def test_teacher_creates_course_user_gets_403(client: TestClient):
    _register(client, "course-teacher", role="teacher")
    teacher = _login(client, "course-teacher")
    _register(client, "course-student")
    student = _login(client, "course-student")

    course_id = _create_course(client, teacher["access_token"], "Базы данных", 100)
    assert course_id >= 1

    forbidden = client.post(
        "/courses",
        json={"title": "Закрытый курс", "price": 50},
        headers=_bearer(student["access_token"]),
    )
    assert forbidden.status_code == 403


def test_user_buys_course_and_sees_own_order(client: TestClient):
    _register(client, "order-teacher", role="teacher")
    teacher = _login(client, "order-teacher")
    course_id = _create_course(client, teacher["access_token"], "Сети", 250)

    _register(client, "order-buyer")
    buyer = _login(client, "order-buyer")
    ordered = client.post(
        "/orders",
        json={"course_id": course_id},
        headers=_bearer(buyer["access_token"]),
    )
    assert ordered.status_code == 201, ordered.text
    assert ordered.json()["course_id"] == course_id

    listing = client.get("/orders", headers=_bearer(buyer["access_token"]))
    assert listing.status_code == 200, listing.text
    orders = listing.json()
    assert len(orders) == 1
    assert orders[0]["course_id"] == course_id
    assert orders[0]["id"] == ordered.json()["id"]


def test_other_user_order_by_id_is_404(client: TestClient):
    _register(client, "foreign-teacher", role="teacher")
    teacher = _login(client, "foreign-teacher")
    course_id = _create_course(client, teacher["access_token"], "Алгоритмы", 300)

    _register(client, "order-owner")
    owner = _login(client, "order-owner")
    ordered = client.post(
        "/orders",
        json={"course_id": course_id},
        headers=_bearer(owner["access_token"]),
    )
    assert ordered.status_code == 201, ordered.text
    order_id = ordered.json()["id"]

    _register(client, "order-other")
    other = _login(client, "order-other")
    foreign = client.get(f"/orders/{order_id}", headers=_bearer(other["access_token"]))
    assert foreign.status_code == 404


def test_health(client: TestClient):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_metrics_contain_http_requests_total(client: TestClient):
    assert client.get("/health").status_code == 200
    assert client.get("/").status_code == 200
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert "http_requests_total" in metrics.text


def test_refresh_token_cannot_be_reused(client: TestClient):
    _register(client, "refresh-user")
    tokens = _login(client, "refresh-user")
    refresh_token = tokens["refresh_token"]

    first = client.post("/refresh", json={"refresh_token": refresh_token})
    assert first.status_code == 200, first.text

    second = client.post("/refresh", json={"refresh_token": refresh_token})
    assert second.status_code == 401
