FROM python:3.12-slim

WORKDIR /srv

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 1000 --no-create-home appuser

COPY api ./api
COPY consumer ./consumer

USER 1000

# консьюмер: uvicorn consumer.main:app --host 0.0.0.0 --port 8001
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
