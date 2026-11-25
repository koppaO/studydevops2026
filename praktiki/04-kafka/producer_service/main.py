import asyncio
import json
import os
from contextlib import asynccontextmanager

from aiokafka import AIOKafkaProducer
from aiokafka.errors import KafkaConnectionError, KafkaTimeoutError
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9094") or "localhost:9094"

connect_lock = asyncio.Lock()
producer: AIOKafkaProducer | None = None


class Order(BaseModel):
    order_id: int
    user_id: int
    product: str
    quantity: int


class Notification(BaseModel):
    user_id: int
    message: str


class ErrorEvent(BaseModel):
    code: str
    message: str


def to_bytes(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False).encode("utf-8")


def build_producer() -> AIOKafkaProducer:
    return AIOKafkaProducer(
        bootstrap_servers=KAFKA_BOOTSTRAP,
        value_serializer=to_bytes,
        request_timeout_ms=8000,
    )


async def stop_quietly(client: AIOKafkaProducer | None) -> None:
    if client is None:
        return
    try:
        await client.stop()
    except Exception as exc:
        print(f"остановка продюсера: {type(exc).__name__}: {exc}")


async def connect_producer() -> AIOKafkaProducer | None:
    global producer
    async with connect_lock:
        if producer is not None:
            return producer
        candidate = build_producer()
        try:
            await candidate.start()
        except asyncio.CancelledError:
            await stop_quietly(candidate)
            raise
        except Exception as exc:
            print(
                f"брокер {KAFKA_BOOTSTRAP} недоступен: "
                f"{type(exc).__name__}: {exc}"
            )
            await stop_quietly(candidate)
            return None
        producer = candidate
        print(f"продюсер подключён к {KAFKA_BOOTSTRAP}")
        return producer


async def publish(topic: str, payload: dict) -> None:
    global producer
    current = await connect_producer()
    if current is None:
        raise HTTPException(
            status_code=503,
            detail=(
                f"Брокер Kafka недоступен ({KAFKA_BOOTSTRAP}). "
                "Контейнер kafka не отвечает, сообщение не отправлено."
            ),
        )
    try:
        await current.send_and_wait(topic, value=payload)
    except (KafkaConnectionError, KafkaTimeoutError, OSError) as exc:
        print(f"отправка в {topic} не удалась: {type(exc).__name__}: {exc}")
        async with connect_lock:
            if producer is current:
                producer = None
        await stop_quietly(current)
        raise HTTPException(
            status_code=503,
            detail=(
                f"Брокер Kafka недоступен ({KAFKA_BOOTSTRAP}). "
                f"Сообщение в топик {topic} не записано."
            ),
        ) from None
    except Exception as exc:
        print(f"отправка в {topic} не удалась: {type(exc).__name__}: {exc}")
        raise HTTPException(
            status_code=503,
            detail=(
                f"Не удалось записать сообщение в топик {topic}. "
                f"Брокер {KAFKA_BOOTSTRAP} не принял его."
            ),
        ) from None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global producer
    await connect_producer()
    yield
    async with connect_lock:
        current = producer
        producer = None
    await stop_quietly(current)


app = FastAPI(title="Producer Service", lifespan=lifespan)


@app.post("/orders/")
async def create_order(order: Order):
    """Кладёт заказ в топик orders."""
    # pydantic v2: model_dump(). .dict() из методички здесь уже нет.
    await publish("orders", order.model_dump(mode="json"))
    return {"status": "success", "message": f"Order {order.order_id} sent to Kafka"}


@app.post("/notify/")
async def send_notification(notification: Notification):
    """Кладёт уведомление в топик notifications."""
    await publish("notifications", notification.model_dump(mode="json"))
    return {
        "status": "success",
        "message": f"Notification sent to user {notification.user_id}",
    }


@app.post("/errors/")
async def send_error(error: ErrorEvent):
    """Кладёт сообщение об ошибке в топик errors."""
    await publish("errors", error.model_dump(mode="json"))
    return {"status": "success", "message": f"Error {error.code} sent to Kafka"}


@app.get("/health")
async def health():
    return {
        "status": "healthy" if producer is not None else "degraded",
        "bootstrap": KAFKA_BOOTSTRAP,
    }
