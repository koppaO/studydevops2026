"""Учебный сервис: JSON-логи в stdout и текстовые метрики Prometheus."""

import json
import random
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

app = FastAPI(title="FastAPI with Structured Logging")

# Учебная авария для расследования, не боевая ошибка.
CRASH_PROBABILITY = 0.3
# В методичке цикл 10_000_000. Он надолго занимает единственный worker.
CPU_ITERATIONS = 200_000
# Границы гистограммы в секундах. Корзина +Inf добавляется при выводе.
BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

_lock = threading.Lock()
_requests: dict[tuple[str, str, str], int] = defaultdict(int)
_buckets: dict[tuple[str, str, float], int] = defaultdict(int)
_duration_sum: dict[tuple[str, str], float] = defaultdict(float)
_duration_count: dict[tuple[str, str], int] = defaultdict(int)


def log(level: str, message: str, **fields: object) -> None:
    """Одна JSON-строка в stdout. Поля запроса кладу в dict сам, не через logging.extra."""
    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "level": level,
        "message": message,
    }
    record.update(fields)
    print(json.dumps(record, ensure_ascii=False), flush=True)


def _client_ip(request: Request) -> str:
    if request.client is None:
        return "unknown"
    return request.client.host


def observe(method: str, path: str, status: str, duration_seconds: float) -> None:
    with _lock:
        _requests[(method, path, status)] += 1
        key = (method, path)
        _duration_sum[key] += duration_seconds
        _duration_count[key] += 1
        for bound in BUCKETS:
            if duration_seconds <= bound:
                _buckets[(method, path, bound)] += 1
        _buckets[(method, path, float("inf"))] += 1


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(pairs: list[tuple[str, str]]) -> str:
    body = ",".join(f'{key}="{_escape(value)}"' for key, value in pairs)
    return "{" + body + "}"


def _format_le(bound: float) -> str:
    if bound == float("inf"):
        return "+Inf"
    return format(bound, "g")


def _format_float(value: float) -> str:
    return format(value, ".10g")


def render_metrics() -> str:
    with _lock:
        requests = sorted(_requests.items())
        series = sorted(_duration_count)
        buckets = dict(_buckets)
        duration_sum = dict(_duration_sum)
        duration_count = dict(_duration_count)

    lines = [
        "# HELP http_requests_total Total HTTP requests.",
        "# TYPE http_requests_total counter",
    ]
    for (method, path, status), value in requests:
        labels = _labels([("method", method), ("path", path), ("status", status)])
        lines.append(f"http_requests_total{labels} {value}")

    lines.append("# HELP http_request_duration_seconds HTTP request duration in seconds.")
    lines.append("# TYPE http_request_duration_seconds histogram")
    for method, path in series:
        for bound in (*BUCKETS, float("inf")):
            labels = _labels([
                ("method", method),
                ("path", path),
                ("le", _format_le(bound)),
            ])
            count = buckets.get((method, path, bound), 0)
            lines.append(f"http_request_duration_seconds_bucket{labels} {count}")
        base = _labels([("method", method), ("path", path)])
        lines.append(
            f"http_request_duration_seconds_sum{base} {_format_float(duration_sum[(method, path)])}"
        )
        lines.append(
            f"http_request_duration_seconds_count{base} {duration_count[(method, path)]}"
        )
    lines.append("")
    return "\n".join(lines)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    # Скрейп Prometheus не пишу в журнал и не считаю, иначе он забивает общий рейт.
    if request.url.path == "/metrics":
        return response
    duration_seconds = time.perf_counter() - started
    log(
        "INFO",
        "request completed",
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round(duration_seconds * 1000, 3),
        client_ip=_client_ip(request),
    )
    observe(request.method, request.url.path, str(response.status_code), duration_seconds)
    return response


@app.get("/")
async def root():
    log("INFO", "Root endpoint called", method="GET", path="/")
    return {"message": "Hello!"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.get("/cpu")
async def cpu_load():
    log("INFO", "CPU load endpoint called", method="GET", path="/cpu")
    for _ in range(CPU_ITERATIONS):
        pass
    return {"status": "loaded"}


@app.get("/crash")
async def crash(request: Request):
    if random.random() < CRASH_PROBABILITY:
        log(
            "ERROR",
            "injected failure",
            method="GET",
            path="/crash",
            status_code=500,
            client_ip=_client_ip(request),
        )
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": "injected failure"},
        )
    return {"status": "ok"}


@app.get("/metrics")
async def metrics():
    return PlainTextResponse(
        render_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )
