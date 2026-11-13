"""Missing NLI artifacts make health fail and prevent consumption/publication."""
import importlib.util
import json
from pathlib import Path
import threading
import urllib.error
import urllib.request
from unittest.mock import MagicMock

import pytest

from services.classifier import consumer
from services.classifier.consumer import ClassifierService
from services.classifier.embedder import NLIModelUnavailable, NLIScorer
from services.classifier.health import make_health_server


def test_missing_nli_is_unhealthy_and_refuses_consumption(monkeypatch, tmp_path):
    monkeypatch.setattr(NLIScorer, "_instance", None)
    monkeypatch.setattr(NLIScorer, "MODEL_NAME", str(tmp_path / "missing-nli"))
    build_consumer = MagicMock()
    monkeypatch.setattr(consumer, "build_consumer", build_consumer)
    classifier = MagicMock()
    service = ClassifierService(classifier)
    service._producer = MagicMock()
    server = make_health_server(service, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(NLIModelUnavailable, match="startup and consumption refused"):
            service.run()
        with pytest.raises(NLIModelUnavailable):
            service.process_trace(MagicMock())
        with pytest.raises(urllib.error.HTTPError) as response:
            urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/health", timeout=3)
        assert response.value.code == 503
        state = json.load(response.value)
        assert state["status"] == "unhealthy" and not state["nli_ready"] and not state["consumer_running"]
        assert "Required NLI model" in state["error"]
        assert NLIScorer._instance is None
        build_consumer.assert_not_called()
        classifier.classify.assert_not_called()
        service._producer.produce.assert_not_called()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_required_classifier_nli_guard_rejects_uninitialized_model(monkeypatch):
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("nli_guard_under_test", root / "tests/conftest.py")
    conftest = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(conftest)
    broken = NLIScorer.__new__(NLIScorer)
    broken.model = None
    monkeypatch.setattr(NLIScorer, "get", lambda: broken)
    with pytest.raises(pytest.fail.Exception, match="zero-score fallback is not valid"):
        conftest.required_classifier_nli.__wrapped__()


def test_initialized_worker_health_is_healthy_until_stopped(monkeypatch, required_classifier_nli):
    entered, release = threading.Event(), threading.Event()
    service = ClassifierService(MagicMock())
    broker = MagicMock()

    def poll(timeout):
        entered.set()
        assert release.wait(5)
        return None

    broker.poll.side_effect = poll
    monkeypatch.setattr(consumer, "build_consumer", lambda: broker)
    monkeypatch.setattr(consumer, "build_producer", MagicMock())
    server = make_health_server(service, "127.0.0.1", 0)
    http_thread = threading.Thread(target=server.serve_forever, daemon=True)
    worker = threading.Thread(target=service.run, daemon=True)
    http_thread.start()
    worker.start()
    try:
        assert entered.wait(5)
        with urllib.request.urlopen(f"http://127.0.0.1:{server.server_port}/health", timeout=3) as response:
            state = json.load(response)
            assert response.status == 200
            assert state["status"] == "ok" and state["nli_ready"] and state["consumer_running"]
    finally:
        service.stop()
        release.set()
        worker.join(timeout=5)
        server.shutdown()
        server.server_close()
        http_thread.join(timeout=3)
    assert not worker.is_alive()
    broker.close.assert_called_once()
    assert service.health()["status"] == "unhealthy"
