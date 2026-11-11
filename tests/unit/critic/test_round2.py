"""Round 2 isolation, deterministic specificity, and cross-provider budget boundaries."""
import hashlib
import json
import sys
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np
import pytest

from services.critic.accounting import BudgetExceeded
from services.critic.evidence import FailureEvidence
from services.critic.round2_legacy import OriginalCritic
from services.critic.round2_providers import GeminiStructured, LABEL, OriginalDeepSeek, Round2Ledger
from services.critic.round2_specificity import distinctness, evidence_anchors, grounding, normalize
from tests.unit.critic.test_groundwork import response, trace


def test_original_sources_are_isolated_without_replacing_current_modules():
    import services.critic.validator as current
    original = OriginalCritic()
    assert sys.modules["services.critic.validator"] is current
    assert original.original_validator.__module__ != "services.critic.graph"
    assert original.hashes["graph.py"] == hashlib.sha256(original.sources["graph.py"]).hexdigest()
    assert b"re.search" in original.sources["graph.py"]
    assert b"raw = provider.complete(prompt)" in original.sources["graph.py"]


@pytest.mark.parametrize("valid", [True, False])
def test_original_validator_retry_then_fallback_is_executed(valid):
    from nexus_agent.models import Alert
    from services.critic.round2 import Store
    original = OriginalCritic()
    raw = json.dumps(response()) if valid else '{}'
    class TextProvider:
        def __init__(self):
            self.calls = 0
        def complete(self, prompt):
            self.calls += 1
            return "FAILURE_SPAN_ID: s\nROOT_CAUSE: Specific observed failure" if self.calls % 2 else raw
    provider = TextProvider()
    p, fallback, attempts = original.run(Alert(trace_id="t", agent_name="a", failure_type="HALLUCINATION"), Store({"t": trace()}), provider)
    assert fallback is not valid
    assert provider.calls == (2 if valid else 4)
    assert len(attempts) == (1 if valid else 2)
    assert p.trace_id == "t"
    if not valid:
        assert all(a["reason"] == "No proposal produced" for a in attempts)


def test_normalization_preserves_identifiers_and_canonicalizes_json():
    assert normalize(' { "b": 2, "a": 1 } ') == normalize('{"a":1,"b":2}')
    assert normalize("  Hello\n WORLD ") == "hello world"
    assert normalize("order B-1043") != normalize("order B-1044")


def test_exact_and_near_duplicates_include_transitive_components():
    vectors = np.array([[1., 0], [.95, np.sqrt(1-.95**2)], [.8, .6]])
    result = distinctness(["one", "two", "three"], vectors)
    assert result["exact_unique"] == 3
    assert result["near_components"] == 1
    assert result["direct_near_pairs"] == 2
    duplicate = distinctness(["Hello world", " hello   WORLD "], np.eye(2))
    assert duplicate["exact_unique"] == 1 and duplicate["near_components"] == 1


def test_grounding_requires_specific_eligible_terms_and_boundaries():
    evidence = FailureEvidence(failure_type="TOOL_MISFIRE", span_id="span_1", supporting_text=json.dumps(
        {"input": '{"order_id":"B-1043"}', "output": None, "metadata": {"tool_name": "get_order"}}))
    anchors = evidence_anchors(evidence)
    assert not grounding("TOOL_MISFIRE happened and validation is required", anchors)["grounded"]
    assert not grounding("span_10 B-10430 get_ordering", anchors)["grounded"]
    assert grounding("Reject B-1043 before get_order at span_1", anchors)["grounded"]
    assert "TOOL_MISFIRE" not in str(anchors)


def test_round2_budget_is_separate_and_reservations_are_atomic(tmp_path):
    ledger = Round2Ledger(tmp_path / "calls.jsonl", git_commit="unit")
    def reserve(i):
        try:
            ledger.append({"call_id": str(i), "status": "reserved", "cost_usd": .6})
            return True
        except BudgetExceeded:
            return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(reserve, range(2))) == 1
    assert ledger.spent == .6
    assert ledger.rows()[0]["evidence_label"] == LABEL
    assert ledger.cap_usd == 1.0


def test_gemini_schema_usage_and_thought_cost_are_logged(tmp_path):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"modelVersion": "gemini-3.5-flash-lite-001",
            "usageMetadata": {"promptTokenCount": 101, "candidatesTokenCount": 20, "thoughtsTokenCount": 5},
            "candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": json.dumps(response())}]}}]})
    ledger = Round2Ledger(tmp_path / "calls.jsonl", git_commit="unit")
    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = GeminiStructured(ledger, client=client, api_key="unit-only")
    assert provider.complete_patch("prompt", trace_id="t") == json.dumps(response())
    assert requests[0]["generationConfig"]["responseJsonSchema"]["additionalProperties"] is False
    row, = ledger.rows()
    assert row["output_tokens"] == 25
    assert row["cost_usd"] == pytest.approx((101*.30+25*2.50)/1e6)
    assert row["model_version"] == "gemini-3.5-flash-lite-001"
    assert "unit-only" not in ledger.path.read_text()


def test_original_provider_does_not_enable_structured_or_json_mode(tmp_path):
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"model": "deepseek-flash", "system_fingerprint": "unit",
                "usage": {"prompt_tokens": 100, "completion_tokens": 50},
                "choices": [{"message": {"content": "free text from the original interface"}}]})
    ledger = Round2Ledger(tmp_path / "calls.jsonl", git_commit="unit")
    provider = OriginalDeepSeek(ledger, client=httpx.Client(transport=httpx.MockTransport(handler)), api_key="unit-only")
    assert provider.complete("original prompt") == "free text from the original interface"
    assert not ({"tools", "tool_choice", "response_format"} & requests[0].keys())
    assert ledger.rows()[0]["prompt_version"] == "phase1-original-free-text"


def test_gemini_transport_timeout_retains_reservation(tmp_path):
    def handler(request):
        raise httpx.ReadTimeout("unit")
    ledger = Round2Ledger(tmp_path / "calls.jsonl", git_commit="unit")
    provider = GeminiStructured(ledger, client=httpx.Client(transport=httpx.MockTransport(handler)), api_key="unit-only")
    with pytest.raises(RuntimeError):
        provider.complete_patch("prompt")
    row, = ledger.rows()
    assert row["cost_usd"] == row["reserved_usd"] > 0
    assert row["input_tokens"] is None
