FROM python:3.11-slim

WORKDIR /app

COPY services/api/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY services/ services/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "uvicorn", "services.api.main:app",
     "--host", "0.0.0.0", "--port", "8001", "--log-level", "info"]
