"""nexus-classifier entry point. Loads the trained model and consumes spans."""

from __future__ import annotations

import logging
import os
import threading

from services.classifier.classifier import FailureClassifier
from services.classifier.consumer import ClassifierService
from services.classifier.health import make_health_server

logging.basicConfig(level=logging.INFO)

MODEL_DIR = os.getenv(
    "CLASSIFIER_MODEL_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "classifier_model")),
)


def load_classifier() -> FailureClassifier:
    clf = FailureClassifier()
    if os.path.exists(os.path.join(MODEL_DIR, "svm.joblib")):
        clf.load(MODEL_DIR)
        logging.info("nexus-classifier: loaded model from %s (tau=%.4f)", MODEL_DIR, clf.threshold)
    else:
        logging.warning("nexus-classifier: no trained model at %s; run services.classifier.train", MODEL_DIR)
    return clf


def classifier_mode(value: str | None = None) -> str:
    """``NEXUS_CLASSIFIER``: unset or ``detectors`` (default), or ``legacy``. Anything else refuses."""
    mode = ((os.getenv("NEXUS_CLASSIFIER") if value is None else value) or "detectors").strip().lower()
    if mode not in ("detectors", "legacy"):
        raise ValueError(f"NEXUS_CLASSIFIER must be 'detectors' or 'legacy', not {mode!r}")
    return mode


def build_classifier(mode: str | None = None):
    """Live classifier: the scored Phase 2 detectors by default, the legacy pipeline on request."""
    mode = classifier_mode(mode)
    logging.info("nexus-classifier: NEXUS_CLASSIFIER=%s", mode)
    if mode == "legacy":
        return FailureClassifier()  # loads its trained model after the NLI check, as before
    from services.classifier.live_detectors import DetectorClassifier

    return DetectorClassifier()


def main() -> None:
    initial = build_classifier()
    service = ClassifierService(initial)
    server = make_health_server(service, port=int(os.getenv("CLASSIFIER_HEALTH_PORT", "8002")))

    def consume():
        try:
            service.require_nli()
            if isinstance(initial, FailureClassifier):
                service.classifier = load_classifier()
            service.run()
        except Exception as exc:  # noqa: BLE001
            service.mark_unhealthy(str(exc))
            logging.exception("nexus-classifier: startup/consumer refused; /health is unhealthy")

    worker = threading.Thread(target=consume, name="classifier-consumer", daemon=True)
    worker.start()
    try:
        # Remain observable with HTTP 503 if initialization fails; never consume.
        server.serve_forever()
    finally:
        service.stop()
        server.server_close()
        worker.join(timeout=10)


if __name__ == "__main__":
    main()
