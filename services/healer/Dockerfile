FROM python:3.11-slim

WORKDIR /app

COPY services/healer/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY sdk/ sdk/
RUN pip install --no-cache-dir -e sdk/

COPY services/ services/

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "services.healer.main"]
