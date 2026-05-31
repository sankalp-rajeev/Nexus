"""nexus-classifier entry point. Loads the trained model and consumes spans."""

from __future__ import annotations

import logging
import os

from services.classifier.classifier import FailureClassifier
from services.classifier.consumer import ClassifierService

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


def main() -> None:
    ClassifierService(load_classifier()).run()


if __name__ == "__main__":
    main()
