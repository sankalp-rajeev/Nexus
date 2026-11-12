# nexus-critic — LangGraph critic agent
FROM python:3.11-slim

WORKDIR /app

COPY sdk /app/sdk
COPY services/critic/requirements.txt /app/services/critic/requirements.txt
RUN pip install --no-cache-dir -e /app/sdk \
 && pip install --no-cache-dir -r /app/services/critic/requirements.txt

COPY services/__init__.py /app/services/__init__.py
COPY services/common /app/services/common
COPY services/critic /app/services/critic
COPY infra/entrypoints/critic.py /app/infra/entrypoints/critic.py

ENV PYTHONUNBUFFERED=1
CMD ["python", "/app/infra/entrypoints/critic.py"]
