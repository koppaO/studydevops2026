"""Пароли и JWT без python-jose и passlib.

Пароль: PBKDF2-HMAC-SHA256, своя соль, сравнение hmac.compare_digest.
Токен: base64url(header).base64url(payload).base64url(HMAC-SHA256).
Алгоритм проверки в коде один — HS256. Поле alg из токена его не выбирает.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.database import get_user_by_username, is_token_blacklisted
from app.models import TokenData, User, UserCreate

logger = logging.getLogger("app.auth")
logger.setLevel(logging.INFO)
logger.propagate = False
if not logger.handlers:
    _log_handler = logging.StreamHandler()
    _log_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(_log_handler)

ALGORITHM = "HS256"
REFRESH_TOKEN_EXPIRE_DAYS = 7
PBKDF2_ITERATIONS = 200_000
_PBKDF2_MAX_ITERATIONS = 1_000_000

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


class TokenError(Exception):
    """Токен не прошёл проверку. Наружу уходит общий 401, без текста токена."""


def access_token_expire_minutes() -> int:
    raw = os.environ.get("ACCESS_TOKEN_EXPIRE_MINUTES", "").strip()
    if not raw:
        return 15
    try:
        return int(raw)
    except ValueError:
        return 15


def secret_key() -> str:
    value = os.environ.get("SECRET_KEY", "").strip()
    if not value:
        raise SystemExit(
            "Приложение не запущено: не задан SECRET_KEY. "
            "Скопируйте .env.example в .env и впишите свой ключ "
            "или задайте переменную окружения SECRET_KEY. "
            "Секрет по умолчанию не подставляется."
        )
    return value


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(raw: str) -> bytes:
    if not raw or any(ch.isspace() for ch in raw):
        raise TokenError()
    padding = "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(raw + padding)
    except (ValueError, TypeError):
        raise TokenError() from None


def _hmac_sha256(signing_input: bytes, secret: str) -> bytes:
    return hmac.new(secret.encode("utf-8"), signing_input, hashlib.sha256).digest()


def encode_jwt(payload: dict) -> str:
    header = {"alg": ALGORITHM, "typ": "JWT"}
    header_b64 = _b64url_encode(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    signature = _hmac_sha256(signing_input, secret_key())
    return f"{header_b64}.{payload_b64}.{_b64url_encode(signature)}"


def decode_jwt(token: str) -> dict:
    if not isinstance(token, str):
        raise TokenError()
    parts = token.split(".")
    if len(parts) != 3 or any(part == "" for part in parts):
        raise TokenError()
    header_b64, payload_b64, signature_b64 = parts
    try:
        header = json.loads(_b64url_decode(header_b64))
        payload = json.loads(_b64url_decode(payload_b64))
    except (TokenError, json.JSONDecodeError, UnicodeDecodeError):
        raise TokenError() from None
    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise TokenError()
    # Не смотрим на alg как на инструкцию. Другое значение — отказ,
    # подпись ниже всё равно только HMAC-SHA256.
    if header.get("alg") != ALGORITHM:
        raise TokenError()
    signing_input = f"{header_b64}.{payload_b64}".encode("ascii")
    expected = _hmac_sha256(signing_input, secret_key())
    actual = _b64url_decode(signature_b64)
    if len(actual) != len(expected) or not hmac.compare_digest(actual, expected):
        raise TokenError()
    exp = payload.get("exp")
    if isinstance(exp, bool) or not isinstance(exp, (int, float)):
        raise TokenError()
    if datetime.now(timezone.utc).timestamp() >= float(exp):
        raise TokenError()
    return payload


def get_password_hash(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PBKDF2_ITERATIONS,
    )
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(plain_password: str, stored: str) -> bool:
    try:
        scheme, iterations_raw, salt_hex, digest_hex = stored.split("$")
        if scheme != "pbkdf2_sha256":
            return False
        iterations = int(iterations_raw)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except (ValueError, TypeError):
        return False
    if iterations <= 0 or iterations > _PBKDF2_MAX_ITERATIONS:
        return False
    if len(expected) != hashlib.sha256().digest_size:
        return False
    actual = hashlib.pbkdf2_hmac(
        "sha256",
        plain_password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


def create_user_with_hash(user_data: UserCreate) -> User:
    return User(
        username=user_data.username,
        email=user_data.email,
        password_hash=get_password_hash(user_data.password),
        role=user_data.role,
        created_at=datetime.now(timezone.utc),
        token_version=0,
    )


def _log_username(username: str) -> str:
    cleaned = username.replace("\r", "").replace("\n", "")
    if len(cleaned) > 200:
        return cleaned[:200]
    return cleaned


def authenticate_user(username: str, password: str) -> User | None:
    # Регистрация сохраняет имя без крайних пробелов. Здесь то же самое,
    # иначе " testuser " не найдёт учётку "testuser".
    username = username.strip()
    user = get_user_by_username(username)
    success = user is not None and verify_password(password, user.password_hash)
    # В строке нет пароля и нет токена: только время, имя и исход.
    logger.info(
        "попытка входа time=%s username=%s success=%s",
        datetime.now(timezone.utc).isoformat(),
        _log_username(username),
        success,
    )
    if not success:
        return None
    return user


def create_access_token(username: str, password_version: int) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=access_token_expire_minutes()
    )
    return encode_jwt(
        {
            "sub": username,
            "type": "access",
            "pwd": password_version,
            "exp": int(expire.timestamp()),
            "jti": secrets.token_hex(16),
        }
    )


def create_refresh_token(username: str, token_version: int) -> str:
    # exp ниже обрезается до секунды. Без случайного jti два refresh,
    # выпущенные в одну секунду, совпадают байт в байт, и чёрный список
    # гасит новый токен вместе со старым.
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    return encode_jwt(
        {
            "sub": username,
            "type": "refresh",
            "ver": token_version,
            "exp": int(expire.timestamp()),
            "jti": secrets.token_hex(16),
        }
    )


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = decode_jwt(token)
    except TokenError:
        raise credentials_exception from None
    if payload.get("type") != "access":
        raise credentials_exception
    password_version = payload.get("pwd")
    username = payload.get("sub")
    if not isinstance(username, str) or not username:
        raise credentials_exception
    token_data = TokenData(username=username)
    user = get_user_by_username(token_data.username or "")
    if user is None:
        raise credentials_exception
    # revoke-all двигает только token_version у refresh.
    # Смена пароля двигает password_version, и старый access тут отсекается.
    if isinstance(password_version, bool) or not isinstance(password_version, int):
        raise credentials_exception
    if password_version != user.password_version:
        raise credentials_exception
    return user


def verify_refresh_token(refresh_token: str) -> User:
    try:
        payload = decode_jwt(refresh_token)
    except TokenError:
        raise HTTPException(status_code=401, detail="Invalid token") from None
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")
    username = payload.get("sub")
    if not isinstance(username, str) or not username:
        raise HTTPException(status_code=401, detail="Invalid token")
    user = get_user_by_username(username)
    if user is None:
        raise HTTPException(status_code=401, detail="User not found")
    if is_token_blacklisted(refresh_token):
        raise HTTPException(status_code=401, detail="Token revoked")
    version = payload.get("ver")
    if isinstance(version, bool) or not isinstance(version, int):
        raise HTTPException(status_code=401, detail="Token revoked")
    if version != user.token_version:
        raise HTTPException(status_code=401, detail="Token revoked")
    return user
