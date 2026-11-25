import asyncio
import json
import os
from contextlib import asynccontextmanager

from aiokafka import AIOKafkaConsumer
from aiokafka.structs import OffsetAndMetadata, TopicPartition
from fastapi import FastAPI

KAFKA_BOOTSTRAP = os.getenv("KAFKA_BOOTSTRAP", "localhost:9094") or "localhost:9094"

received_orders = []
received_notifications = []
received_errors = []

orders_lock = asyncio.Lock()
notifications_lock = asyncio.Lock()
errors_lock = asyncio.Lock()

started_consumers = []
reader_tasks = []
handlers = set()
kafka_ok = False


class OffsetTracker:
    # Пока ранний offset партиции в sleep, поздний коммитить нельзя:
    # брокер сочтёт ранний обработанным.
    def __init__(self):
        self._lock = asyncio.Lock()
        self._next = {}
        self._done = {}

    async def seen(self, topic: str, partition: int, offset: int) -> None:
        async with self._lock:
            key = (topic, partition)
            self._next.setdefault(key, offset)
            self._done.setdefault(key, set())

    async def finished(self, topic: str, partition: int, offset: int) -> None:
        async with self._lock:
            key = (topic, partition)
            self._done.setdefault(key, set()).add(offset)

    async def commit_ready(self, consumer) -> None:
        # commit только из задачи, которая читает consumer.
        # aiokafka не разрешает звать его из обработчиков параллельно с getone.
        async with self._lock:
            planned = []
            for key, current in self._next.items():
                done = self._done.get(key, set())
                target = current
                while target in done:
                    target += 1
                if target != current:
                    planned.append((key, current, target))
        if not planned:
            return
        commits = {
            TopicPartition(topic, partition): OffsetAndMetadata(target, "")
            for (topic, partition), _current, target in planned
        }
        try:
            await consumer.commit(commits)
        except Exception as exc:
            print(f"commit не прошёл: {type(exc).__name__}: {exc}")
            return
        async with self._lock:
            for key, current, target in planned:
                if self._next.get(key) != current:
                    continue
                done = self._done.get(key, set())
                for old in range(current, target):
                    done.discard(old)
                self._next[key] = target


def make_consumer(topic: str, group_id: str) -> AIOKafkaConsumer:
    return AIOKafkaConsumer(
        topic,
        bootstrap_servers=KAFKA_BOOTSTRAP,
        group_id=group_id,
        auto_offset_reset="earliest",
        enable_auto_commit=False,
        request_timeout_ms=8000,
    )


async def stop_consumer(consumer) -> None:
    try:
        await consumer.stop()
    except Exception as exc:
        print(f"остановка консьюмера: {type(exc).__name__}: {exc}")


async def open_consumer(topic: str, group_id: str) -> AIOKafkaConsumer:
    consumer = make_consumer(topic, group_id)
    try:
        await consumer.start()
    except Exception:
        await stop_consumer(consumer)
        raise
    return consumer


def decode_payload(raw):
    if not isinstance(raw, (bytes, bytearray)):
        raise ValueError("пустое тело")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("ожидался JSON-объект")
    return payload


async def handle_message(payload, msg, storage, lock, tracker, title: str):
    try:
        print(
            f"{title}: взял partition={msg.partition} offset={msg.offset}, "
            "обработка 1 с"
        )
        await asyncio.sleep(1)
        async with lock:
            storage.append(payload)
        print(f"{title}: готово offset={msg.offset} value={payload}")
        await tracker.finished(msg.topic, msg.partition, msg.offset)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"{title}: ошибка offset={msg.offset}: {type(exc).__name__}: {exc}")


async def run_reader(consumer, storage, lock, title: str):
    global kafka_ok
    try:
        await consume(consumer, storage, lock, title)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        print(f"{title}: цикл чтения остановился: {type(exc).__name__}: {exc}")
        kafka_ok = False
    else:
        print(f"{title}: цикл чтения завершился")
        kafka_ok = False


async def consume(consumer, storage, lock, title: str):
    tracker = OffsetTracker()
    while True:
        await tracker.commit_ready(consumer)
        try:
            msg = await asyncio.wait_for(consumer.getone(), timeout=0.3)
        except asyncio.TimeoutError:
            continue
        try:
            payload = decode_payload(msg.value)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError) as exc:
            print(f"{title}: пропускаю битое сообщение offset={msg.offset}: {exc}")
            await tracker.seen(msg.topic, msg.partition, msg.offset)
            await tracker.finished(msg.topic, msg.partition, msg.offset)
            continue
        await tracker.seen(msg.topic, msg.partition, msg.offset)
        task = asyncio.create_task(
            handle_message(payload, msg, storage, lock, tracker, title)
        )
        handlers.add(task)
        task.add_done_callback(handlers.discard)


async def snapshot(storage, lock):
    async with lock:
        return list(storage)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global kafka_ok
    specs = [
        ("orders", "orders-group", received_orders, orders_lock),
        ("notifications", "notifications-group", received_notifications, notifications_lock),
        ("errors", "errors-group", received_errors, errors_lock),
    ]
    for topic, group, storage, lock in specs:
        try:
            consumer = await open_consumer(topic, group)
        except Exception as exc:
            print(
                f"{topic}: не подключился к {KAFKA_BOOTSTRAP}: "
                f"{type(exc).__name__}: {exc}"
            )
            break
        started_consumers.append(consumer)
        reader_tasks.append(
            asyncio.create_task(run_reader(consumer, storage, lock, topic))
        )
    kafka_ok = len(started_consumers) == 3
    if kafka_ok:
        print(f"консьюмеры запущены, bootstrap={KAFKA_BOOTSTRAP}")
    else:
        print("часть консьюмеров не запустилась, списки будут пустыми до перезапуска uvicorn")
    try:
        yield
    finally:
        for task in reader_tasks:
            task.cancel()
        if reader_tasks:
            await asyncio.gather(*reader_tasks, return_exceptions=True)
        pending = [task for task in list(handlers) if not task.done()]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for consumer in started_consumers:
            await stop_consumer(consumer)
        kafka_ok = False
        print("консьюмеры остановлены")


app = FastAPI(title="Consumer Service", lifespan=lifespan)


@app.get("/orders/")
async def get_orders():
    """Заказы, которые консьюмер уже обработал."""
    items = await snapshot(received_orders, orders_lock)
    return {"orders": items, "count": len(items)}


@app.get("/notifications/")
async def get_notifications():
    """Уведомления, которые консьюмер уже обработал."""
    items = await snapshot(received_notifications, notifications_lock)
    return {"notifications": items, "count": len(items)}


@app.get("/errors/")
async def get_errors():
    """Ошибки из топика errors."""
    items = await snapshot(received_errors, errors_lock)
    return {"errors": items, "count": len(items)}


@app.get("/health")
async def health():
    return {
        "status": "healthy" if kafka_ok else "degraded",
        "bootstrap": KAFKA_BOOTSTRAP,
    }
