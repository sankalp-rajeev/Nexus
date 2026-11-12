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

# Stage both inference models at the exact revisions used by CI. Network access
# belongs to this build step only; runtime constructors use local files only.
COPY .github/model-revisions.json /app/.github/model-revisions.json
COPY scripts/phase6/prepare_classifier_models.py /app/scripts/phase6/prepare_classifier_models.py
RUN python scripts/phase6/prepare_classifier_models.py

COPY services/__init__.py /app/services/__init__.py
COPY services/common /app/services/common
COPY services/classifier /app/services/classifier
COPY tests/fixtures/generate_synthetic_traces.py /app/tests/fixtures/generate_synthetic_traces.py
COPY data/classifier_model /app/data/classifier_model

ENV PYTHONUNBUFFERED=1
ENV CLASSIFIER_MODEL_DIR=/app/data/classifier_model
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 HF_HUB_DISABLE_TELEMETRY=1
RUN python -c "from services.classifier.embedder import NLIScorer, _load_model, DEFAULT_MODEL; NLIScorer.get(); _load_model(DEFAULT_MODEL)"
EXPOSE 8002
HEALTHCHECK --interval=10s --timeout=3s --start-period=60s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8002/health', timeout=2).close()"
CMD ["python", "-m", "services.classifier.main"]
