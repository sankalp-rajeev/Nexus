# nexus-collector — FastAPI span ingestion service
FROM python:3.11-slim

WORKDIR /app

# Build context is the repo root (see docker-compose). Copy SDK + service.
COPY sdk /app/sdk
COPY services/collector/requirements.txt /app/services/collector/requirements.txt

RUN pip install --no-cache-dir -e /app/sdk \
 && pip install --no-cache-dir -r /app/services/collector/requirements.txt

COPY services/__init__.py /app/services/__init__.py
COPY services/collector /app/services/collector

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

CMD ["uvicorn", "services.collector.main:app", "--host", "0.0.0.0", "--port", "8000"]
