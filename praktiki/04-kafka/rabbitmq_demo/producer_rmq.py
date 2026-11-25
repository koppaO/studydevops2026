import asyncio
import json
import os
import sys
from urllib.parse import quote

try:
    import aio_pika
except ImportError:
    print("Нет aio-pika. Поставь зависимости: python -m pip install -r requirements.txt")
    raise SystemExit(1)

QUEUE = "orders"

ORDER = {
    "order_id": 1,
    "user_id": 100,
    "product": "Laptop",
    "quantity": 1,
}


def connection_params():
    user = os.getenv("RABBITMQ_USER", "guest")
    password = os.getenv("RABBITMQ_PASSWORD", "guest")
    host = os.getenv("RABBITMQ_HOST", "localhost")
    url = f"amqp://{quote(user, safe='')}:{quote(password, safe='')}@{host}:5672/"
    return url, user, host


def load_order() -> dict:
    if len(sys.argv) < 2:
        return ORDER
    try:
        data = json.loads(sys.argv[1])
    except json.JSONDecodeError as exc:
        print(f"аргумент не JSON: {exc}")
        raise SystemExit(1)
    if not isinstance(data, dict):
        print("нужен JSON-объект")
        raise SystemExit(1)
    return data


async def main():
    url, user, host = connection_params()
    order = load_order()
    print(f"подключаюсь к RabbitMQ, очередь {QUEUE}, пользователь {user}, хост {host}")
    try:
        connection = await aio_pika.connect(url)
    except Exception as exc:
        print(f"не подключился к RabbitMQ ({host}): {type(exc).__name__}: {exc}")
        print("Проверь, что контейнер rabbitmq запущен и порт 5672 открыт.")
        raise SystemExit(1)
    async with connection:
        channel = await connection.channel()
        queue = await channel.declare_queue(QUEUE, durable=True)
        message = aio_pika.Message(
            body=json.dumps(order, ensure_ascii=False).encode("utf-8"),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
        )
        await channel.default_exchange.publish(message, routing_key=queue.name)
        print(f"опубликовал в очередь {queue.name}: {order}")


if __name__ == "__main__":
    asyncio.run(main())
