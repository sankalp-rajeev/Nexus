# nexus-classifier — Kafka consumer + embedding + PatchCore + SVM
# NOTE: pulls torch + sentence-transformers (large image, several GB). The
# embedding model is baked in at build time so the container runs offline.
FROM python:3.11-slim

WORKDIR /app

COPY sdk /app/sdk
COPY services/classifier/requirements.txt /app/services/classifier/requirements.txt
RUN pip install --no-cache-dir -e /app/sdk \
 && pip install --no-cache-dir --extra-index-url https://download.pytorch.org/whl/cpu torch \
 && pip install --no-cache-dir -r /app/services/classifier/requirements.txt

# Pre-download the embedding model into the image.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

COPY services/__init__.py /app/services/__init__.py
COPY services/common /app/services/common
COPY services/classifier /app/services/classifier
COPY tests/fixtures/generate_synthetic_traces.py /app/tests/fixtures/generate_synthetic_traces.py
COPY data/classifier_model /app/data/classifier_model

ENV PYTHONUNBUFFERED=1
ENV CLASSIFIER_MODEL_DIR=/app/data/classifier_model
CMD ["python", "-m", "services.classifier.main"]
