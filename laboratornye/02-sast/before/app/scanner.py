import httpx


def fetch_local_health():
    # Проверка сертификата выключена. Так оставлять нельзя.
    response = httpx.get("https://127.0.0.1/health", verify=False, timeout=2.0)
    return response.status_code


def save_note(text):
    path = "/tmp/scan-note.txt"
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path
