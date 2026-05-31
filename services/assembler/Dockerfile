# nexus-assembler — Kafka consumer + trace assembly + Postgres writes
FROM python:3.11-slim

WORKDIR /app

COPY sdk /app/sdk
COPY services/assembler/requirements.txt /app/services/assembler/requirements.txt
RUN pip install --no-cache-dir -e /app/sdk \
 && pip install --no-cache-dir -r /app/services/assembler/requirements.txt

COPY services/__init__.py /app/services/__init__.py
COPY services/common /app/services/common
COPY services/assembler /app/services/assembler

ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "services.assembler.main"]
