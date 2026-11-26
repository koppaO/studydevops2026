"""Пользователи, чёрный список refresh и лимит по IP. Всё в памяти процесса."""

from __future__ import annotations

import time
from collections import defaultdict, deque

from app.models import User

fake_users_db: dict[str, User] = {}
refresh_tokens_blacklist: set[str] = set()

RATE_LIMIT_WINDOW_SECONDS = 60.0
RATE_LIMIT_MAX_REQUESTS = 10
_hits: dict[str, deque[float]] = defaultdict(deque)


def get_user_by_username(username: str) -> User | None:
    return fake_users_db.get(username)


def create_user(user: User) -> User:
    if user.username in fake_users_db:
        raise ValueError("Username already registered")
    fake_users_db[user.username] = user
    return user


def list_usernames() -> list[str]:
    return list(fake_users_db.keys())


def blacklist_refresh_token(token: str) -> None:
    refresh_tokens_blacklist.add(token)


def is_token_blacklisted(token: str) -> bool:
    return token in refresh_tokens_blacklist


def allow_auth_request(ip: str) -> bool:
    """False, если с этого IP за последние 60 секунд уже было 10 запросов.

    Отклонённый запрос в окно не дописываю: пока старые метки не выйдут
    за 60 секунд, новые попытки так и получают отказ.
    """
    now = time.monotonic()
    bucket = _hits[ip]
    while bucket and now - bucket[0] >= RATE_LIMIT_WINDOW_SECONDS:
        bucket.popleft()
    if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
        return False
    bucket.append(now)
    return True
