"""Модели запросов. Email проверяю сам, без email-validator."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


def check_email(value: str) -> str:
    """Адрес годится, если в нём одна @ и в домене есть точка."""
    text = value.strip()
    at = text.find("@")
    if at <= 0 or at != text.rfind("@"):
        raise ValueError("в email должна быть одна @ и непустая локальная часть")
    domain = text[at + 1 :]
    if "." not in domain or domain.startswith(".") or domain.endswith("."):
        raise ValueError("в домене email должна быть точка")
    return text


class User(BaseModel):
    username: str
    email: str
    # exclude=True: даже если модель случайно уйдёт в ответ, хеш в JSON не попадёт.
    password_hash: str = Field(exclude=True)
    role: Literal["user", "admin"] = "user"
    disabled: bool = False
    # без default: время ставлю при создании, не один раз на класс
    created_at: datetime
    token_version: int = 0
    # Растёт только при смене пароля. Access несёт это число в поле pwd.
    password_version: int = 0


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    email: str
    password: str = Field(min_length=1, max_length=1024)
    role: Literal["user", "admin"] = "user"

    @field_validator("username")
    @classmethod
    def username_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("username пустой")
        return cleaned

    @field_validator("email")
    @classmethod
    def email_has_at_and_dot(cls, value: str) -> str:
        return check_email(value)


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class RefreshToken(BaseModel):
    refresh_token: str


class PasswordChange(BaseModel):
    old_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=1, max_length=1024)


class TokenData(BaseModel):
    username: Optional[str] = None
