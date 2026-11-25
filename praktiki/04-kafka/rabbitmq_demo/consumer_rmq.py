import asyncio
import json
import os
from urllib.parse import quote

try:
    import aio_pika
except ImportError:
    print("Нет aio-pika. Поставь зависимости: python -m pip install -r requirements.txt")
    raise SystemExit(1)

QUEUE = "orders"


def connection_params():
    user = os.getenv("RABBITMQ_USER", "guest")
    password = os.getenv("RABBITMQ_PASSWORD", "guest")
    host = os.getenv("RABBITMQ_HOST", "localhost")
    url = f"amqp://{quote(user, safe='')}:{quote(password, safe='')}@{host}:5672/"
    return url, user, host


async def main():
    url, user, host = connection_params()
    print(f"подключаюсь к RabbitMQ, очередь {QUEUE}, пользователь {user}, хост {host}")
    try:
        connection = await aio_pika.connect(url)
    except Exception as exc:
        print(f"не подключился к RabbitMQ ({host}): {type(exc).__name__}: {exc}")
        print("Проверь, что контейнер rabbitmq запущен и порт 5672 открыт.")
        raise SystemExit(1)
    async with connection:
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)
        queue = await channel.declare_queue(QUEUE, durable=True)
        print(f"слушаю очередь {queue.name}, выход по Ctrl+C")
        async with queue.iterator() as iterator:
            async for message in iterator:
                async with message.process():
                    try:
                        payload = json.loads(message.body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                        print(f"битое сообщение, подтверждаю и пропускаю: {exc}")
                        continue
                    print(f"получил и подтвердил: {payload}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("остановлен")
