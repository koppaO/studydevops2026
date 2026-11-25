from fastapi import FastAPI, HTTPException

app = FastAPI(title="sast-lab")


def require_text(value):
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=400, detail="пустое значение")
    return value


@app.get("/")
def root():
    return {"service": "sast-lab"}


@app.get("/health")
def health():
    state = require_text("ok")
    return {"status": state}


@app.get("/cpu")
def cpu():
    total = 0
    for number in range(100000):
        total += number
    return {"status": "ok", "iterations": 100000, "total": total}


@app.get("/metrics")
def metrics():
    return {"status": "ok", "requests": 0, "errors": 0}
