"""EduCloud API: каталог курсов, токены и публикация заказа в Kafka."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import math
import os
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path

ACCESS_TTL = 15 * 60
REFRESH_TTL = 7 * 24 * 60 * 60
PBKDF2_ITERATIONS = 100_000
PBKDF2_MAX = 1_000_000
RATE_WINDOW = 60.0
RATE_LIMIT = 10
AUTH_PATHS = {"/login", "/register"}


def load_env(path: Path) -> None:
    # Непустая переменная окружения важнее файла.
    if not path.is_file():
        return
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if not key:
            continue
        current = os.environ.get(key)
        if current is None or current.strip() == "":
            os.environ[key] = value


load_env(Path(__file__).resolve().parent.parent / ".env")

if not os.environ.get("SECRET_KEY", "").strip():
    raise SystemExit(
        "API не запущен: нет SECRET_KEY. "
        "Скопируй .env.example в .env и впиши ключ "
        "или задай переменную окружения SECRET_KEY."
    )

SECRET_KEY = os.environ["SECRET_KEY"].strip()
DOCS_ON = os.environ.get("ENABLE_DOCS", "1") != "0"

from aiokafka import AIOKafkaProducer
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, field_validator


class TokenError(Exception):
    """Токен не принят. Наружу уходит общий 401."""


def log(level: str, message: str, **fields: object) -> None:
    # Одна JSON-строка в stdout. Поля кладу в dict сам, не через logging.
    record = {
        "timestamp": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "level": level,
        "message": message,
    }
    record.update(fields)
    print(json.dumps(record, ensure_ascii=False), flush=True)


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(raw: str) -> bytes:
    if not raw or any(ch.isspace() for ch in raw):
        raise TokenError()
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (ValueError, TypeError):
        raise TokenError() from None


def sign(signing_input: bytes) -> bytes:
    return hmac.new(SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()


def encode_jwt(payload: dict) -> str:
    header = b64url_encode(
        json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode("utf-8")
    )
    body = b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{header}.{body}".encode("ascii")
    return f"{header}.{body}.{b64url_encode(sign(signing_input))}"


def decode_jwt(token: str) -> dict:
    if not isinstance(token, str):
        raise TokenError()
    parts = token.split(".")
    if len(parts) != 3 or any(part == "" for part in parts):
        raise TokenError()
    header_b64, payload_b64, signature_b64 = parts
    try:
        header = json.loads(b64url_decode(header_b64))
        payload = json.loads(b64url_decode(payload_b64))
    except (TokenError, json.JSONDecodeError, UnicodeDecodeError):
        raise TokenError() from None
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise TokenError()
    # alg из токена алгоритм не выбирает: принимаю только HS256 и сверяю HMAC.
    if header.get("alg") != "HS256":
        raise TokenError()
    expected = sign(f"{header_b64}.{payload_b64}".encode("ascii"))
    try:
        actual = b64url_decode(signature_b64)
    except TokenError:
        raise TokenError() from None
    if len(actual) != len(expected) or not hmac.compare_digest(actual, expected):
        raise TokenError()
    exp = payload.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        raise TokenError()
    if time.time() >= float(exp):
        raise TokenError()
    return payload


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, rounds_raw, salt_hex, digest_hex = stored.split("$")
        rounds = int(rounds_raw)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    if scheme != "pbkdf2_sha256" or not 1 <= rounds <= PBKDF2_MAX:
        return False
    if len(expected) != hashlib.sha256().digest_size:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(actual, expected)


def make_token(username: str, role: str, token_type: str, ttl: int) -> str:
    payload = {
        "sub": username,
        "role": role,
        "type": token_type,
        "jti": secrets.token_hex(16),
        "exp": int(time.time()) + ttl,
    }
    return encode_jwt(payload)


def issue_tokens(user: dict) -> dict[str, str]:
    return {
        "access_token": make_token(user["username"], user["role"], "access", ACCESS_TTL),
        "refresh_token": make_token(user["username"], user["role"], "refresh", REFRESH_TTL),
        "token_type": "bearer",
    }


_DUMMY_HASH = hash_password("not-a-real-password")

users: dict[str, dict] = {}
courses: dict[int, dict] = {}
orders: dict[int, dict] = {}
refresh_blacklist: set[str] = set()
seq = {"course": 0, "order": 0}
hits: dict[str, deque[float]] = defaultdict(deque)
http_requests: dict[tuple[str, str, str], int] = {}

bearer_scheme = HTTPBearer(auto_error=False)


def client_ip(request: Request) -> str:
    if request.client is None or not request.client.host:
        return "unknown"
    return request.client.host


def allow_auth(ip: str) -> bool:
    # Общий потолок: 10 POST на /login и /register с одного IP за 60 секунд.
    now = time.monotonic()
    bucket = hits[ip]
    while bucket and now - bucket[0] >= RATE_WINDOW:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT:
        return False
    bucket.append(now)
    return True


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=401,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def note_request(
    method: str,
    path: str,
    status_code: int,
    duration_ms: float,
    message: str = "request",
) -> None:
    level = "ERROR" if status_code >= 500 else "INFO"
    log(
        level,
        message,
        method=method,
        path=path,
        status_code=status_code,
        duration_ms=duration_ms,
    )
    if path == "/metrics":
        return
    key = (method, path, str(status_code))
    http_requests[key] = http_requests.get(key, 0) + 1


def escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def render_metrics() -> str:
    lines = [
        "# HELP http_requests_total Total HTTP requests.",
        "# TYPE http_requests_total counter",
    ]
    for method, path, status in sorted(http_requests):
        labels = (
            f'method="{escape_label(method)}",'
            f'path="{escape_label(path)}",'
            f'status="{escape_label(status)}"'
        )
        lines.append(f"http_requests_total{{{labels}}} {http_requests[(method, path, status)]}")
    lines.append("")
    return "\n".join(lines)


class RegisterIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=128)
    role: str = "user"

    @field_validator("username", "email")
    @classmethod
    def strip_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("пустое поле")
        return value

    @field_validator("email")
    @classmethod
    def email_ok(cls, value: str) -> str:
        if "@" not in value or value.startswith("@") or value.endswith("@"):
            raise ValueError("нужен email")
        return value

    @field_validator("role")
    @classmethod
    def role_ok(cls, value: str) -> str:
        if value not in ("user", "teacher"):
            raise ValueError("role: только user или teacher")
        return value


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def strip_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("пустое имя")
        return value


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=1)


class CourseIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    price: float = Field(gt=0)

    @field_validator("title")
    @classmethod
    def strip_title(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("пустое название")
        return value

    @field_validator("price")
    @classmethod
    def finite_price(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("price должен быть конечным числом больше 0")
        return value


class OrderIn(BaseModel):
    course_id: int = Field(ge=1)


app = FastAPI(
    title="EduCloud",
    docs_url="/docs" if DOCS_ON else None,
    redoc_url="/redoc" if DOCS_ON else None,
    openapi_url="/openapi.json" if DOCS_ON else None,
)


@app.middleware("http")
async def access_log(request: Request, call_next):
    started = time.perf_counter()
    path = request.url.path
    if request.method == "POST" and path in AUTH_PATHS and not allow_auth(client_ip(request)):
        response = JSONResponse(
            status_code=429,
            content={"detail": "Слишком много запросов с этого IP за последнюю минуту"},
            headers={"Retry-After": "60"},
        )
        note_request(
            request.method,
            path,
            response.status_code,
            round((time.perf_counter() - started) * 1000, 3),
        )
        return response
    try:
        response = await call_next(request)
    except Exception as exc:
        note_request(
            request.method,
            path,
            500,
            round((time.perf_counter() - started) * 1000, 3),
            message=f"{type(exc).__name__}: {exc}",
        )
        return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка"})
    note_request(
        request.method,
        path,
        response.status_code,
        round((time.perf_counter() - started) * 1000, 3),
    )
    return response


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
) -> dict:
    if creds is None or creds.scheme.lower() != "bearer":
        raise unauthorized("Нужна авторизация")
    try:
        payload = decode_jwt(creds.credentials)
    except TokenError:
        raise unauthorized("Недействительный токен") from None
    if payload.get("type") != "access":
        raise unauthorized("Нужен access-токен")
    username = payload.get("sub")
    user = users.get(username) if isinstance(username, str) else None
    if user is None:
        raise unauthorized("Недействительный токен")
    return {"username": user["username"], "role": user["role"]}


async def publish_order(payload: dict) -> None:
    bootstrap = os.environ.get("KAFKA_BOOTSTRAP", "").strip()
    if not bootstrap:
        return
    producer = AIOKafkaProducer(
        bootstrap_servers=bootstrap,
        request_timeout_ms=5000,
    )
    try:
        await producer.start()
        raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        await producer.send_and_wait("orders", raw)
    finally:
        try:
            await producer.stop()
        except Exception:
            pass


@app.get("/")
async def root():
    return {"service": "educloud"}


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return PlainTextResponse(
        render_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.post("/register", status_code=201)
async def register(body: RegisterIn):
    if body.username in users:
        raise HTTPException(status_code=400, detail="Такой username уже есть")
    users[body.username] = {
        "username": body.username,
        "email": body.email,
        "password_hash": hash_password(body.password),
        "role": body.role,
    }
    return {"username": body.username, "email": body.email, "role": body.role}


@app.post("/login")
async def login(body: LoginIn):
    user = users.get(body.username)
    if user is None:
        verify_password(body.password, _DUMMY_HASH)
        raise unauthorized("Неверный логин или пароль")
    if not verify_password(body.password, user["password_hash"]):
        raise unauthorized("Неверный логин или пароль")
    return issue_tokens(user)


@app.post("/refresh")
async def refresh(body: RefreshIn):
    if body.refresh_token in refresh_blacklist:
        raise unauthorized("Refresh-токен уже использован")
    try:
        payload = decode_jwt(body.refresh_token)
    except TokenError:
        raise unauthorized("Недействительный refresh-токен") from None
    if payload.get("type") != "refresh":
        raise unauthorized("Недействительный refresh-токен")
    # Старый refresh гасится сразу, ещё до выдачи новой пары.
    refresh_blacklist.add(body.refresh_token)
    username = payload.get("sub")
    user = users.get(username) if isinstance(username, str) else None
    if user is None:
        raise unauthorized("Недействительный refresh-токен")
    return issue_tokens(user)


@app.get("/me")
async def me(user: dict = Depends(current_user)):
    return {"username": user["username"], "role": user["role"]}


@app.get("/courses")
async def list_courses():
    return list(courses.values())


@app.post("/courses", status_code=201)
async def create_course(body: CourseIn, user: dict = Depends(current_user)):
    if user["role"] != "teacher":
        raise HTTPException(status_code=403, detail="Курс создаёт только teacher")
    seq["course"] += 1
    course = {"id": seq["course"], "title": body.title, "price": body.price}
    courses[course["id"]] = course
    return course


@app.post("/orders", status_code=201)
async def create_order(body: OrderIn, user: dict = Depends(current_user)):
    course = courses.get(body.course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Курс не найден")
    seq["order"] += 1
    order = {
        "id": seq["order"],
        "username": user["username"],
        "course_id": course["id"],
        "title": course["title"],
        "price": course["price"],
    }
    orders[order["id"]] = order
    started = time.perf_counter()
    try:
        # Молчащий брокер не должен держать клиента на дефолтном таймауте.
        await asyncio.wait_for(publish_order(order), timeout=8)
    except Exception as exc:
        log(
            "ERROR",
            f"kafka не приняла заказ {order['id']}: {type(exc).__name__}: {exc}",
            method="POST",
            path="/orders",
            status_code=201,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
    return order


@app.get("/orders")
async def list_orders(user: dict = Depends(current_user)):
    return [item for item in orders.values() if item["username"] == user["username"]]


@app.get("/orders/{order_id}")
async def get_order(order_id: int, user: dict = Depends(current_user)):
    order = orders.get(order_id)
    if order is None or order["username"] != user["username"]:
        raise HTTPException(status_code=404, detail="Заказ не найден")
    return order
