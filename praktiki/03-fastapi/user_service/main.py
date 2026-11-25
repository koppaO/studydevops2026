"""User Service. Практическая работа № 3: FastAPI, Postman, интеграции."""

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field, field_validator

NOTIFY_URL = "http://localhost:8001/notify/"
POSTS_URL = "https://jsonplaceholder.typicode.com/posts"
HTTP_TIMEOUT = 5.0
TOKEN_TTL_MINUTES = 60
PBKDF2_ITERATIONS = 100_000
SALT_BYTES = 16
MAX_TOKEN_LENGTH = 4096
SECRET_MISSING = (
    "JWT_SECRET не задан. Укажите переменную окружения JWT_SECRET "
    "или файл .env рядом с main.py"
)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
B64URL_RE = re.compile(r"^[A-Za-z0-9_-]*$")

logger = logging.getLogger("user_service")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_handler)

bearer_scheme = HTTPBearer(auto_error=False)


class UserBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=100)
    email: str = Field(min_length=3, max_length=200)
    age: Optional[int] = Field(default=None, ge=0)

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Имя не задано")
        return value

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        value = value.strip().lower()
        if EMAIL_RE.fullmatch(value) is None:
            raise ValueError("Некорректный email")
        return value


class UserCreate(UserBase):
    pass


class User(UserBase):
    id: int
    created_at: datetime
    is_active: bool = True


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("username")
    @classmethod
    def strip_username(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Логин не задан")
        return value


class Store:
    def __init__(self) -> None:
        self.users: dict[int, User] = {}
        self.accounts: dict[str, str] = {}
        self.next_user_id: int = 1


store = Store()
app = FastAPI(
    title="User Service",
    version="1.0.0",
    description="Практическая работа № 3. Сервис пользователей.",
)


def get_jwt_secret() -> Optional[str]:
    env_value = os.environ.get("JWT_SECRET", "").strip()
    if env_value:
        return env_value

    env_file = Path(__file__).resolve().parent / ".env"
    if not env_file.is_file():
        return None
    try:
        text = env_file.read_text(encoding="utf-8-sig")
    except OSError as exc:
        logger.error("Не удалось прочитать %s: %s", env_file.name, exc)
        return None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        if key.strip() != "JWT_SECRET":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        return value.strip() or None
    return None


def require_secret() -> str:
    secret = get_jwt_secret()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=SECRET_MISSING,
        )
    return secret


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, digest_hex = stored.split("$", 1)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError:
        return False
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    if len(derived) != len(expected):
        return False
    return hmac.compare_digest(derived, expected)


def b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def b64url_decode(raw: str) -> bytes:
    if not raw or B64URL_RE.fullmatch(raw) is None:
        raise ValueError("bad base64url")
    padding = "=" * ((4 - len(raw) % 4) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def encode_jwt(username: str, secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": username,
        "exp": int(
            (datetime.now(timezone.utc) + timedelta(minutes=TOKEN_TTL_MINUTES)).timestamp()
        ),
    }
    header_part = b64url_encode(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    payload_part = b64url_encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    )
    signing_input = f"{header_part}.{payload_part}".encode("ascii")
    signature = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    return f"{header_part}.{payload_part}.{b64url_encode(signature)}"


def decode_jwt(token: str, secret: str) -> dict[str, Any]:
    if not token or len(token) > MAX_TOKEN_LENGTH or token.count(".") != 2:
        raise unauthorized("Некорректный токен")

    header_part, payload_part, signature_part = token.split(".")
    try:
        signing_input = f"{header_part}.{payload_part}".encode("ascii")
        header = json.loads(b64url_decode(header_part))
        payload = json.loads(b64url_decode(payload_part))
        signature = b64url_decode(signature_part)
    except (ValueError, json.JSONDecodeError, UnicodeError):
        raise unauthorized("Некорректный токен") from None

    if not isinstance(header, dict) or header.get("alg") != "HS256":
        raise unauthorized("Поддерживается только алгоритм HS256")
    if header.get("typ") != "JWT":
        raise unauthorized("Некорректный заголовок токена")

    expected = hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()
    if len(signature) != len(expected) or not hmac.compare_digest(signature, expected):
        raise unauthorized("Неверная подпись токена")

    if not isinstance(payload, dict):
        raise unauthorized("Некорректный токен")

    exp = payload.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        raise unauthorized("В токене нет срока действия")
    if datetime.now(timezone.utc).timestamp() >= float(exp):
        raise unauthorized("Срок действия токена истёк")
    return payload


def require_username(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    if credentials is None or not credentials.credentials:
        raise unauthorized("Требуется заголовок Authorization: Bearer <token>")
    payload = decode_jwt(credentials.credentials, require_secret())
    username = payload.get("sub")
    if not isinstance(username, str) or not username:
        raise unauthorized("В токене нет имени пользователя")
    return username


def ensure_email_free(email: str, ignore_id: Optional[int] = None) -> None:
    for user in store.users.values():
        if user.email == email and user.id != ignore_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Пользователь с таким email уже существует",
            )


def get_or_404(user_id: int) -> User:
    user = store.users.get(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Пользователь не найден",
        )
    return user


async def notify_created(user: User) -> None:
    age_part = f", возраст {user.age}" if user.age is not None else ""
    body = {
        "message": (
            f"Создан пользователь id={user.id}, {user.name}, "
            f"email {user.email}{age_part}"
        ),
        "user": user.model_dump(mode="json"),
    }
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.post(NOTIFY_URL, json=body)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Сервис уведомлений вернул статус %s",
            exc.response.status_code,
        )
    except httpx.RequestError as exc:
        logger.error("Сервис уведомлений недоступен: %s", exc)
    else:
        logger.info("Уведомление отправлено, user id=%s", user.id)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "User Service работает", "status": "ok"}


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.post("/users/", response_model=User, status_code=status.HTTP_201_CREATED)
async def create_user(payload: UserCreate) -> User:
    ensure_email_free(payload.email)
    user = User(
        id=store.next_user_id,
        created_at=datetime.now(timezone.utc),
        is_active=True,
        **payload.model_dump(),
    )
    store.users[user.id] = user
    store.next_user_id += 1
    await notify_created(user)
    return user


@app.get("/users/", response_model=list[User])
async def list_users(
    skip: int = Query(0, ge=0),
    limit: int = Query(10, ge=1),
    min_age: Optional[int] = Query(
        default=None,
        description=(
            "Если задан, в выдаче только пользователи с age строго больше этого "
            "значения. Записи без age не проходят фильтр."
        ),
    ),
) -> list[User]:
    rows = list(store.users.values())
    if min_age is not None:
        rows = [user for user in rows if user.age is not None and user.age > min_age]
    return rows[skip : skip + limit]


@app.get("/users/{user_id}/posts")
async def user_posts(user_id: int) -> Any:
    # Локальная проверка раньше исходящего запроса.
    get_or_404(user_id)
    url = f"{POSTS_URL}?userId={user_id}"
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        logger.error("Внешний API постов вернул %s", exc.response.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Внешний API постов ответил кодом {exc.response.status_code}",
        ) from exc
    except httpx.RequestError as exc:
        logger.error("Внешний API постов недоступен: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "Не удалось связаться с внешним API постов: "
                f"{exc.__class__.__name__}"
            ),
        ) from exc
    except json.JSONDecodeError as exc:
        logger.error("Внешний API постов вернул не JSON: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Внешний API постов вернул ответ, который не удалось разобрать как JSON",
        ) from exc


@app.get("/users/{user_id}", response_model=User)
async def get_user(user_id: int) -> User:
    return get_or_404(user_id)


@app.put("/users/{user_id}", response_model=User)
async def update_user(
    user_id: int,
    payload: UserCreate,
    username: str = Depends(require_username),
) -> User:
    current = get_or_404(user_id)
    ensure_email_free(payload.email, ignore_id=user_id)
    updated = current.model_copy(update=payload.model_dump())
    store.users[user_id] = updated
    logger.info("%s обновил пользователя id=%s", username, user_id)
    return updated


@app.delete("/users/{user_id}")
async def delete_user(
    user_id: int,
    username: str = Depends(require_username),
) -> dict[str, Any]:
    get_or_404(user_id)
    store.users.pop(user_id)
    logger.info("%s удалил пользователя id=%s", username, user_id)
    return {"message": "Пользователь удалён", "id": user_id}


@app.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(body: Credentials) -> dict[str, str]:
    if body.username in store.accounts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Такой username уже зарегистрирован",
        )
    store.accounts[body.username] = hash_password(body.password)
    return {"message": "Учётная запись создана", "username": body.username}


@app.post("/login")
async def login(body: Credentials) -> dict[str, str]:
    stored = store.accounts.get(body.username)
    if stored is None or not verify_password(body.password, stored):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный логин или пароль",
        )
    secret = require_secret()
    return {
        "access_token": encode_jwt(body.username, secret),
        "token_type": "bearer",
    }
