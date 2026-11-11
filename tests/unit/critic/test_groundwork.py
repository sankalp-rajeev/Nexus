"""Contract, rejection, accounting and sealed-data boundaries for Phase 3."""
import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import httpx
import pytest
from nexus_agent.models import Alert, CompleteTrace, FailureType, PatchProposal, Span

from services.critic.accounting import BudgetExceeded, CostLedger
from services.critic.dev_adapter import current_config, dev_labels, dev_traces, evidence_from_dev
from services.critic.evidence import FailureEvidence
from services.critic.graph import build_prompt, run_critic
from services.critic.llm import MockProvider, OllamaProvider, ProviderError
from services.critic.proposal import Provenance, StructuredPatch, response_schema
from services.critic.registry import ConfigRegistry


def response(**changes):
    raw = dict(patch_type="PROMPT_PATCH", target_component="_BASE_SYSTEM",
               explanation="The prompt does not require sufficient grounding from the trace evidence.",
               patch_content="Answer only using the observed tool output. Abstain if context is missing.",
               confidence="MEDIUM", estimated_impact="Independent evaluation is required to measure repair quality.",
               root_cause_analysis="The trace output lacks support in the observed tool results.")
    return {**raw, **changes}


def trace():
    now = datetime.now(timezone.utc)
    span = Span(span_id="s", trace_id="t", agent_name="a", span_type="agent_step",
                input="x" * 2200, output="Observed output", duration_ms=1,
                client_timestamp=now, sdk_version="1", metadata={"role": "root"})
    return CompleteTrace(trace_id="t", agent_name="a", started_at=now, spans=[span])


def evidence(**changes):
    return FailureEvidence(**{**dict(failure_type="HALLUCINATION", span_id="s",
                                     supporting_text="Observed unsupported output"), **changes})


def store():
    db = MagicMock()
    db.load_trace.return_value = trace()
    db.load_config.return_value = {"_BASE_SYSTEM": "Existing prompt value"}
    db.load_evidence.return_value = evidence()
    return db


class ScriptedProvider:
    def __init__(self, outputs):
        self.outputs = iter(outputs)
        self.last_provenance = Provenance(source="llm", model="transport-double",
                                          model_version="unit-v1", temperature=0.2,
                                          input_tokens=11, output_tokens=17)
        self.prompts = []

    def complete_patch(self, prompt, **kwargs):
        self.prompts.append(json.loads(prompt))
        return next(self.outputs)


def run_with(db, provider):
    return run_critic(Alert(trace_id="t", agent_name="a", failure_type=FailureType.HALLUCINATION),
                      db, llm_factory=lambda **_: provider)


@pytest.mark.parametrize("raw", ["```json\n{}\n```", "prefix {} suffix", "[]", "null",
                                  json.dumps(response(extra_field="unknown")),
                                  json.dumps(response(confidence="CERTAIN")),
                                  json.dumps(response(patch_content=17))])
def test_structured_parser_never_repairs_free_text(raw):
    with pytest.raises(ValueError):
        StructuredPatch.model_validate_json(raw)


def test_structured_response_validates_against_shared_patch_proposal():
    parsed = StructuredPatch.model_validate_json(json.dumps(response()))
    proposal = PatchProposal.model_validate({**parsed.model_dump(), "trace_id": "t", "alert_id": "a",
                                             "failure_type": "HALLUCINATION"})
    original = {"_BASE_SYSTEM": "Original value"}
    assert ConfigRegistry(original).apply(proposal)["_BASE_SYSTEM"] == response()["patch_content"]
    assert original == {"_BASE_SYSTEM": "Original value"}


def test_unknown_key_is_rejected_and_never_stored():
    db = store()
    p = run_with(db, ScriptedProvider([json.dumps(response(target_component="invented_guard"))]))
    assert p.valid_without_fallback and not p.dry_run_applied
    assert "Unknown config key" in p.rejection_reasons[-1]
    assert p.status == "REJECTED"
    db.write_patch.assert_not_called()
    db.record_attempt.assert_called_once()


@pytest.mark.parametrize("content,patch_type", [('"wrong type"', "TOOL_CONFIG_PATCH"),
                                                 ('{"nested":1}', "PROMPT_PATCH"),
                                                 ('{"nested":NaN}', "MEMORY_PATCH")])
def test_registry_rejects_type_mismatch_and_nonfinite_values(content, patch_type):
    proposal = PatchProposal.model_validate({**response(patch_content=content, patch_type=patch_type,
                                                       target_component="memory_config"),
                                             "trace_id": "t", "alert_id": "a", "failure_type": "HALLUCINATION"})
    with pytest.raises(ValueError):
        ConfigRegistry({"memory_config": {"nested": 0}}).apply(proposal)


def test_dry_run_deep_copy():
    config = {"memory_config": {"items": [1]}}
    registry = ConfigRegistry(config)
    config["memory_config"]["items"].append(2)
    proposal = PatchProposal.model_validate({**response(patch_type="MEMORY_PATCH",
                     target_component="memory_config", patch_content='{"items":[3]}'),
                     "trace_id": "t", "alert_id": "a", "failure_type": "HALLUCINATION"})
    patched = registry.apply(proposal)
    patched["memory_config"]["items"].append(4)
    assert registry.config["memory_config"]["items"] == [1]


def test_fallback_after_two_structured_failures_is_tagged_audited_not_stored():
    db = store()
    provider = ScriptedProvider(["bad JSON", "still bad JSON"])
    p = run_with(db, provider)
    assert p.provenance.source == "fallback"
    assert not p.valid_without_fallback
    assert not p.dry_run_applied
    assert len(p.rejection_reasons) == 2
    assert p.provenance.input_tokens == 22 and p.provenance.output_tokens == 34
    db.write_patch.assert_not_called()
    assert "previous_rejection" in provider.prompts[1]


def test_existing_vagueness_rules_still_trigger_retry():
    db = store()
    p = run_with(db, ScriptedProvider([json.dumps(response(explanation="You should try improving the system prompt")),
                                      json.dumps(response())]))
    assert p.provenance.source == "llm" and p.dry_run_applied
    assert "vague" in p.rejection_reasons[0]
    db.write_patch.assert_called_once()


def test_full_prompt_preserves_untruncated_trace_and_evidence():
    prompt = json.loads(build_prompt({"trace": trace(), "current_config": {"_BASE_SYSTEM": "prompt"},
                                      "evidence": evidence()}))
    assert len(prompt["full_trace"]["spans"][0]["input"]) == 2200
    assert prompt["failure_evidence"]["span_id"] == "s"


@pytest.mark.parametrize("change", [{"span_id": None}, {"failure_type": "NORMAL"},
                                   {"supporting_text": ""}, {"step": -1}])
def test_evidence_requires_location_type_and_support(change):
    with pytest.raises(ValueError):
        evidence(**change)


@pytest.mark.parametrize("kind", ["trace_identity", "missing_config", "foreign_span", "wrong_type", "bad_step"])
def test_invalid_context_fails_before_model_call(kind):
    db = store()
    if kind == "trace_identity":
        db.load_trace.return_value.agent_name = "foreign"
    elif kind == "missing_config":
        db.load_config.return_value = {}
    elif kind == "foreign_span":
        db.load_evidence.return_value = evidence(span_id="foreign")
    elif kind == "wrong_type":
        db.load_evidence.return_value = evidence(failure_type="PLAN_DRIFT")
    else:
        db.load_evidence.return_value = evidence(span_id=None, step=9)
    provider = ScriptedProvider([])
    p = run_with(db, provider)
    assert p.provenance.source == "fallback" and p.rejection_reasons
    assert not provider.prompts
    assert db.record_attempt.call_args.args[0].rejection_reasons
    db.write_patch.assert_not_called()


def test_mock_requires_explicit_environment(monkeypatch):
    monkeypatch.delenv("NEXUS_LLM")
    with pytest.raises(RuntimeError):
        MockProvider()


def test_mock_never_counts_as_valid():
    p = run_with(store(), MockProvider())
    assert p.provenance.mock and not p.valid_without_fallback


def client_for(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


@pytest.mark.parametrize("failed", [False, True])
def test_schema_is_sent_and_every_call_logs_usage_or_unknown(tmp_path, failed):
    requests = []
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:7b-instruct", "digest": "digest1"}]})
        requests.append(json.loads(request.content))
        if failed:
            return httpx.Response(503)
        return httpx.Response(200, json={"done": True, "done_reason": "stop", "message": {"content": json.dumps(response())},
                                         "prompt_eval_count": 101, "eval_count": 37})
    ledger = CostLedger(tmp_path / "calls.jsonl")
    provider = OllamaProvider(client=client_for(handler), ledger=ledger, expected_digest="digest1")
    if failed:
        with pytest.raises(ProviderError):
            provider.complete_patch("prompt", trace_id="t")
    else:
        provider.complete_patch("prompt", trace_id="t")
    row, = ledger.rows()
    assert row["cost_usd"] == 0 and row["latency_ms"] >= 0
    assert row["input_tokens"] == (None if failed else 101)
    assert row["output_tokens"] == (None if failed else 37)
    assert row["model_version"] == "digest1"
    assert requests[0]["format"] == response_schema()
    assert "seed" not in requests[0]["options"]  # stability runs are independent, uncached samples


def test_budget_cap_persists_across_restarts(tmp_path):
    path = tmp_path / "calls.jsonl"
    ledger = CostLedger(path)
    ledger.append({"cost_usd": 0.74})
    CostLedger(path).check(0.01)
    with pytest.raises(BudgetExceeded):
        CostLedger(path).check(0.02)
    ledger.append({"cost_usd": 0.01})
    with pytest.raises(BudgetExceeded):
        CostLedger(path).check()


def test_dev_gate_discards_opaque_test_label_before_csv_parsing(tmp_path):
    path = tmp_path / "labels.csv"
    path.write_text('run_id,trace_id,task_id,family,split,label,fault\n'
                    'r0,SEALED,q0,qa,test,OPAQUE,OPAQUE\n'
                    'r1,t,q1,qa,dev,HALLUCINATION,HALLUCINATION\n', encoding="utf-8")
    assert list(dev_labels(path)) == [dict(run_id="r1", trace_id="t", task_id="q1", family="qa", split="dev",
                                         label="HALLUCINATION", fault="HALLUCINATION")]


def test_dev_trace_gate_does_not_deserialize_unselected_payload(tmp_path):
    path = tmp_path / "traces.jsonl"
    path.write_text('{"trace_id": "SEALED", "opaque": THIS IS NOT JSON' + 'x'*70 + '\n'
                    + trace().model_dump_json().replace('{"trace_id":"t"', '{"trace_id": "t"') + '\n', encoding="utf-8")
    assert dev_traces(path, {"t"})["t"].trace_id == "t"


def test_adapter_rejects_test_marker_before_using_other_fields():
    with pytest.raises(ValueError, match="Only DEV"):
        evidence_from_dev({"split": "test"}, None)


def test_snapshot_uses_only_real_active_constants():
    from bench import agent
    config = current_config({"fault": "HALLUCINATION"})
    assert config == {"_GUESS_SYSTEM": agent._GUESS_SYSTEM, "MAX_STEPS": agent.MAX_STEPS,
                      "TOOL_SPECS": agent.TOOL_SPECS}
    config["TOOL_SPECS"][0]["description"] = "changed"
    assert config["TOOL_SPECS"] != agent.TOOL_SPECS


def test_db_rejects_unchecked_shared_proposals_before_connecting():
    from services.critic.db import CriticDB
    db = CriticDB()
    db._ensure = MagicMock()
    proposal = PatchProposal.model_validate({**response(), "trace_id": "t", "alert_id": "a", "failure_type": "HALLUCINATION"})
    with pytest.raises(ValueError):
        db.write_patch(proposal)
    db._ensure.assert_not_called()


def test_clopper_pearson_boundary_counts():
    from services.critic.experiments import interval
    all_passed = interval(12, 12)
    assert all_passed["ci95_clopper_pearson"] == pytest.approx([0.7353515, 1.0])
    assert interval(0, 0)["ci95_clopper_pearson"] == [None, None]
    assert interval(0, 12)["ci95_clopper_pearson"] == pytest.approx([0, 0.2646485])


def test_stability_requires_three_valid_nonfallback_outputs():
    from services.critic.experiments import stability
    base = {"trace_id": "t", "failure_type": "HALLUCINATION", "source_model": "unit",
            "proposal": {"valid_without_fallback": True, "patch_type": "PROMPT_PATCH", "target_component": "_BASE_SYSTEM"}}
    assert stability([base] * 3)["overall"]["joint_stable"]["successes"] == 1
    bad = {**base, "proposal": {**base["proposal"], "valid_without_fallback": False}}
    assert stability([base, base, bad])["overall"]["joint_stable"]["successes"] == 0
    changed = {**base, "proposal": {**base["proposal"], "target_component": "_GUESS_SYSTEM"}}
    summary = stability([base, base, changed])["overall"]
    assert summary["type_stable"]["successes"] == 1
    assert summary["key_stable"]["successes"] == 0


@pytest.mark.parametrize("kind", ["success", "timeout", "rejected", "malformed_tool"])
def test_deepseek_strict_tools_and_conservative_accounting(tmp_path, kind):
    from services.critic.llm import DeepSeekProvider
    requests = []
    def handler(request):
        requests.append(json.loads(request.content))
        if kind == "timeout":
            raise httpx.ReadTimeout("unit timeout")
        if kind == "rejected":
            return httpx.Response(400)
        return httpx.Response(200, json={"model": "deepseek-flash", "system_fingerprint": "f1",
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20, "prompt_cache_hit_tokens": 60},
                    "choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
                        {"function": {"name": "wrong_tool" if kind == "malformed_tool" else "propose_patch",
                                      "arguments": json.dumps(response())}}]}}]})
    ledger = CostLedger(tmp_path / "paid_calls.jsonl")
    provider = DeepSeekProvider(ledger=ledger, client=client_for(handler), api_key="unit-only")
    if kind == "success":
        assert provider.complete_patch("prompt") == json.dumps(response())
    else:
        with pytest.raises(ProviderError):
            provider.complete_patch("prompt")
    row, = ledger.rows()
    events = [json.loads(x) for x in ledger.path.read_text().splitlines()]
    assert len(events) == 2 and events[0]["status"] == "reserved"
    assert requests[0]["tools"][0]["function"]["strict"] is True
    assert "$defs" not in requests[0]["tools"][0]["function"]["parameters"]
    assert requests[0]["tool_choice"]["function"]["name"] == "propose_patch"
    if kind == "timeout":
        assert ledger.spent == events[0]["cost_usd"] > 0
        assert row["input_tokens"] is None
    elif kind == "rejected":
        assert ledger.spent == 0
    else:
        assert ledger.spent == pytest.approx((60*.006 + 40*.30 + 20*1.20)/1e6)
        assert row["model_version"].endswith("fingerprint=f1")
    assert "unit-only" not in ledger.path.read_text()


def test_paid_request_is_blocked_before_http_at_cap(tmp_path):
    from services.critic.llm import DeepSeekProvider
    ledger = CostLedger(tmp_path / "paid_calls.jsonl")
    ledger.append({"cost_usd": .75})
    client = MagicMock()
    provider = DeepSeekProvider(ledger=ledger, client=client, api_key="unit-only")
    with pytest.raises(BudgetExceeded):
        provider.complete_patch("prompt")
    client.post.assert_not_called()
