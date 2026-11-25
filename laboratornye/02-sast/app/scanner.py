import tempfile

import httpx


def fetch_status(url, verify=True):
    response = httpx.get(url, verify=verify, timeout=2.0)
    return response.status_code


def save_note(text):
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix="note-",
        suffix=".txt",
        delete=False,
    ) as handle:
        handle.write(text)
        return handle.name
