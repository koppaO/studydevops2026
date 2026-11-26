"""EduCloud consumer: читает топик orders, если задан KAFKA_BOOTSTRAP."""

from __future__ import annotations

import asyncio
import json
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from aiokafka import AIOKafkaConsumer
from aiokafka.structs import OffsetAndMetadata, TopicPartition
from fastapi import FastAPI
from fastapi.responses import JSONResponse


def load_env(path: Path) -> None:
    # Как в API: непустая переменная окружения важнее файла.
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

KAFKA_BOOTSTRAP = os.environ.get("KAFKA_BOOTSTRAP", "").strip()
DOCS_ON = os.environ.get("ENABLE_DOCS", "1") != "0"

orders: list[dict] = []
orders_lock = asyncio.Lock()
handlers: set[asyncio.Task] = set()


def log(level: str, message: str, **fields: object) -> None:
    record = {
        "timestamp": datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "level": level,
        "message": message,
    }
    record.update(fields)
    print(json.dumps(record, ensure_ascii=False), flush=True)


def decode_order(raw: object) -> dict | None:
    if not isinstance(raw, (bytes, bytearray)):
        return None
    try:
        payload = json.loads(bytes(raw).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


async def remember(payload: dict) -> None:
    await asyncio.sleep(0.2)
    async with orders_lock:
        orders.append(payload)


async def stop_consumer(consumer: AIOKafkaConsumer) -> None:
    try:
        await consumer.stop()
    except Exception as exc:
        log("ERROR", f"остановка консьюмера: {type(exc).__name__}: {exc}")


async def pull(consumer: AIOKafkaConsumer) -> None:
    # Commit только в этом цикле. Обработчик consumer не вызывает.
    while True:
        msg = await consumer.getone()
        payload = decode_order(msg.value)
        if payload is None:
            log("ERROR", f"битое сообщение orders offset={msg.offset}, пропускаю")
        else:
            task = asyncio.create_task(remember(payload))
            handlers.add(task)
            task.add_done_callback(handlers.discard)
            await task
        tp = TopicPartition(msg.topic, msg.partition)
        await consumer.commit({tp: OffsetAndMetadata(msg.offset + 1, "")})


async def read_loop() -> None:
    while True:
        consumer = AIOKafkaConsumer(
            "orders",
            bootstrap_servers=KAFKA_BOOTSTRAP,
            group_id="orders-group",
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            request_timeout_ms=8000,
        )
        try:
            await consumer.start()
            log("INFO", f"читаю топик orders, bootstrap={KAFKA_BOOTSTRAP}")
            await pull(consumer)
        except asyncio.CancelledError:
            await stop_consumer(consumer)
            raise
        except Exception as exc:
            log("ERROR", f"чтение orders остановилось: {type(exc).__name__}: {exc}")
            await stop_consumer(consumer)
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task: asyncio.Task | None = None
    if KAFKA_BOOTSTRAP:
        task = asyncio.create_task(read_loop())
    else:
        log("INFO", "KAFKA_BOOTSTRAP пустой, топик orders не читаю")
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        pending = [item for item in list(handlers) if not item.done()]
        for item in pending:
            item.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


app = FastAPI(
    title="EduCloud consumer",
    lifespan=lifespan,
    docs_url="/docs" if DOCS_ON else None,
    redoc_url="/redoc" if DOCS_ON else None,
    openapi_url="/openapi.json" if DOCS_ON else None,
)


@app.middleware("http")
async def access_log(request, call_next):
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception as exc:
        log(
            "ERROR",
            f"{type(exc).__name__}: {exc}",
            method=request.method,
            path=request.url.path,
            status_code=500,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return JSONResponse(status_code=500, content={"detail": "Внутренняя ошибка"})
    log(
        "INFO" if response.status_code < 500 else "ERROR",
        "request",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round((time.perf_counter() - started) * 1000, 3),
    )
    return response


@app.get("/health")
async def health():
    if not KAFKA_BOOTSTRAP:
        return {"status": "degraded"}
    return {"status": "ok"}


@app.get("/orders")
async def list_orders():
    async with orders_lock:
        items = list(orders)
    return {"orders": items, "count": len(items)}
