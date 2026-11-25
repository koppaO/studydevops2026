"""Маршруты JWT-микросервиса.

.env читается при импорте этого модуля. Пустой SECRET_KEY останавливает процесс.
"""

from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import parse_qs


def load_env_file(path: Path) -> None:
    """Строки KEY=VALUE. Пустые и комментарии с # пропускаются.

    Непустая переменная окружения остаётся как есть: файл её не затирает.
    """
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8-sig")
    for raw_line in text.splitlines():
        line = raw_line.strip()
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


load_env_file(Path(__file__).resolve().parent.parent / ".env")

if not os.environ.get("SECRET_KEY", "").strip():
    raise SystemExit(
        "Приложение не запущено: не задан SECRET_KEY. "
        "Скопируйте .env.example в .env и впишите свой ключ "
        "или задайте переменную окружения SECRET_KEY. "
        "Секрет по умолчанию не подставляется."
    )

# Импорты приложения ниже: к этому моменту ключ уже в окружении.
from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm

from app.auth import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    create_user_with_hash,
    get_current_user,
    get_password_hash,
    verify_password,
    verify_refresh_token,
)
from app.database import (
    allow_auth_request,
    blacklist_refresh_token,
    create_user,
    get_user_by_username,
    list_usernames,
)
from app.models import PasswordChange, RefreshToken, Token, User, UserCreate, UserLogin

app = FastAPI(title="JWT Protected Microservice")

_AUTH_LIMIT_PATHS = {"/register", "/token", "/token/custom"}


def _client_ip(request: Request) -> str:
    if request.client is None or not request.client.host:
        return "unknown"
    return request.client.host


@app.middleware("http")
async def limit_auth_routes(request: Request, call_next):
    if request.method == "POST" and request.url.path in _AUTH_LIMIT_PATHS:
        if not allow_auth_request(_client_ip(request)):
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": "Слишком много запросов с этого IP за последнюю минуту"
                },
                headers={"Retry-After": "60"},
            )
    return await call_next(request)


async def read_password_form(request: Request) -> OAuth2PasswordRequestForm:
    """OAuth2 password flow: username и password в urlencoded-форме.

    В методичке стоит Depends(OAuth2PasswordRequestForm). У этого класса
    поля объявлены через Form(), а Form() на старте требует python-multipart.
    Пакета в requirements нет, поэтому тело разбираю сам и собираю тот же
    объект: набор полей у формы не меняется.
    """
    content_type = request.headers.get("content-type", "")
    media = content_type.split(";", 1)[0].strip().lower()
    if media != "application/x-www-form-urlencoded":
        raise HTTPException(
            status_code=422,
            detail=(
                "Ожидается форма application/x-www-form-urlencoded "
                "с полями username и password"
            ),
        )
    raw = await request.body()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=422,
            detail="Тело формы должно быть в UTF-8",
        ) from None
    parsed = parse_qs(text, keep_blank_values=True)
    if "username" not in parsed or "password" not in parsed:
        raise HTTPException(
            status_code=422,
            detail="Нужны поля username и password",
        )
    return OAuth2PasswordRequestForm(
        grant_type=parsed["grant_type"][0] if "grant_type" in parsed else None,
        username=parsed["username"][0],
        password=parsed["password"][0],
        scope=parsed["scope"][0] if "scope" in parsed else "",
        client_id=parsed["client_id"][0] if "client_id" in parsed else None,
        client_secret=(
            parsed["client_secret"][0] if "client_secret" in parsed else None
        ),
    )


def _token_pair(user: User) -> Token:
    return Token(
        access_token=create_access_token(user.username, user.password_version),
        refresh_token=create_refresh_token(user.username, user.token_version),
    )


def _bad_login() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Incorrect username or password",
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.get("/")
async def public_root():
    return {
        "message": "JWT-микросервис. Публичная страница.",
        "endpoints": {
            "public": ["/", "/public-info"],
            "auth": [
                "/register",
                "/token",
                "/token/custom",
                "/refresh",
                "/logout",
                "/token/revoke-all",
                "/change-password",
            ],
            "protected": ["/protected", "/protected/admin"],
        },
    }


@app.get("/public-info")
async def public_info():
    return {
        "app_name": "JWT Microservice",
        "version": "1.0.0",
        "status": "operational",
        "note": "Полные данные пользователя только с access-токеном",
    }


@app.post("/register", status_code=status.HTTP_201_CREATED)
async def register(user_data: UserCreate):
    if get_user_by_username(user_data.username):
        raise HTTPException(status_code=400, detail="Username already registered")
    user = create_user_with_hash(user_data)
    create_user(user)
    return {
        "message": "User created successfully",
        "username": user.username,
        "email": user.email,
        "role": user.role,
    }


@app.post("/token", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(read_password_form),
):
    user = authenticate_user(form_data.username, form_data.password)
    if user is None:
        raise _bad_login()
    return _token_pair(user)


@app.post("/token/custom", response_model=Token)
async def login_custom(login_data: UserLogin):
    user = authenticate_user(login_data.username, login_data.password)
    if user is None:
        raise _bad_login()
    return _token_pair(user)


@app.post("/refresh", response_model=Token)
async def refresh_token(body: RefreshToken):
    user = verify_refresh_token(body.refresh_token)
    pair = _token_pair(user)
    blacklist_refresh_token(body.refresh_token)
    return pair


@app.post("/logout")
async def logout(body: RefreshToken):
    verify_refresh_token(body.refresh_token)
    blacklist_refresh_token(body.refresh_token)
    return {"message": "Successfully logged out"}


@app.get("/protected")
async def protected_endpoint(current_user: User = Depends(get_current_user)):
    return {
        "message": f"Hello, {current_user.username}! This is protected information",
        "username": current_user.username,
        "email": current_user.email,
        "role": current_user.role,
        "created_at": current_user.created_at.isoformat(),
    }


@app.get("/protected/admin")
async def admin_endpoint(current_user: User = Depends(get_current_user)):
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Insufficient permissions")
    return {
        "message": "Admin panel",
        "users": list_usernames(),
    }


@app.post("/token/revoke-all")
async def revoke_all(current_user: User = Depends(get_current_user)):
    current_user.token_version += 1
    return {"message": "Все ранее выданные refresh-токены отозваны"}


@app.post("/change-password")
async def change_password(
    body: PasswordChange,
    current_user: User = Depends(get_current_user),
):
    if not verify_password(body.old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Старый пароль не совпадает")
    current_user.password_hash = get_password_hash(body.new_password)
    current_user.token_version += 1
    current_user.password_version += 1
    return {"message": "Пароль изменён, ранее выданные токены больше не принимаются"}
