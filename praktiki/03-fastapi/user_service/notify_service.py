"""Приёмник уведомлений для User Service. Порт 8001."""

import sys
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict


def _console_utf8() -> None:
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is None:
        return
    try:
        reconfigure(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return


class NotifyIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str
    user: dict[str, Any]


app = FastAPI(title="Notification Service")


@app.post("/notify/")
async def notify(body: NotifyIn) -> dict[str, str]:
    data = body.model_dump()
    print(data["message"])
    return {"status": "sent"}


if __name__ == "__main__":
    import uvicorn

    _console_utf8()
    uvicorn.run(app, host="127.0.0.1", port=8001)
