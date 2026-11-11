"""Round 3 contracts, leak tripwires and scoring, exclusively handmade fixtures."""
import builtins
import inspect
import json
from pathlib import Path

import httpx
import numpy as np
import pytest
from nexus_agent.models import Alert

from services.critic.accounting import BudgetExceeded
from services.critic.arms import V1_VERSION, original_prompts, v1_prompt
from services.critic.c3 import GroundTruth, score_c3, summarize_c3
from services.critic.detector_adapter import VISIBLE_METADATA, critic_view, from_detector
from services.critic.dev_adapter import evidence_from_dev
from services.critic.graph import run_critic
from services.critic.llm import DeepSeekProvider
from services.critic.proposal import CriticConfig, Provenance, StructuredDiagnosis, StructuredPatch, response_schema
from services.critic.proxy_sample import ARMS, CLASSES, sample_records, write_sample
from services.critic.round2_legacy import OriginalCritic, git_source
from services.critic.round3_part_b import Round3Ledger, run_experiment
from services.critic.scoring_truth import truth_from_dev
from services.critic.validator import format_trace_for_prompt
from tests.unit.critic.test_groundwork import evidence, response, store, trace

VID = "v-0123456789abcdef"


def view_fixture(kinds=("agent_step",)):
    t = trace().model_copy(deep=True, update={"trace_id": VID})
    base = t.spans[0]
    t.spans = [base.model_copy(deep=True, update={"trace_id": VID, "span_id": f"s{i}",
        "span_type": type(base.span_type)(kind), "input": '{"id":"B-1043"}',
        "output": "Observed claim", "metadata": {"role": "root"} if kind == "agent_step"
        else {"tool_name": "read_memory" if kind == "memory_read" else "get_order"}})
        for i, kind in enumerate(kinds)]
    return t


class StructuredDouble:
    def __init__(self, *, malformed=False, target="_BASE_SYSTEM", ledger=None):
        self.last_provenance = Provenance(source="llm", model="fixture", model_version="unit",
            temperature=.2, input_tokens=10, output_tokens=20, cost_usd=.01, latency_ms=1)
        self.prompts = []
        self.malformed, self.target, self.ledger = malformed, target, ledger

    def log(self, prompt):
        self.prompts.append(json.loads(prompt))
        if self.ledger:
            self.ledger.append({"call_id": f"{self.ledger.arm}-{len(self.ledger.rows())}",
                "status": "reserved", **self.last_provenance.model_dump()})

    def complete_diagnosis(self, prompt, **kwargs):
        self.log(prompt)
        if self.malformed:
            return "not JSON"
        return json.dumps({"diagnosed_failure_type": "HALLUCINATION", "cited_span_id": "s",
                           "cited_step": 0, "root_cause_analysis": "Specific unsupported output in the root span."})

    def complete_patch(self, prompt, **kwargs):
        self.log(prompt)
        return json.dumps(response(target_component=self.target, diagnosed_failure_type="HALLUCINATION",
                                   cited_span_id="s", cited_step=0))


@pytest.mark.parametrize("arm,calls", [("new", 1), ("v1_structured", 2)])
def test_arm_runs_through_same_registry_dry_run_and_audit(arm, calls):
    db, provider = store(), StructuredDouble()
    p = run_critic(Alert(trace_id="t", agent_name="a", failure_type="HALLUCINATION"), db,
                   llm_factory=lambda **_: provider, config={"critic_arm": arm})
    assert p.critic_arm == arm and p.valid_without_fallback and p.dry_run_applied
    assert p.cited_span_id == "s" and p.cited_step == 0
    assert p.diagnosed_failure_type.value == "HALLUCINATION"
    assert len(provider.prompts) == calls
    assert p.provenance.cost_usd == pytest.approx(.01*calls)
    assert p.provenance.input_tokens == 10*calls
    db.record_attempt.assert_called_once_with(p)
    db.write_patch.assert_called_once_with(p)
    assert p.model_dump(mode="json")["critic_arm"] == arm
    if arm == "v1_structured":
        assert p.provenance.prompt_version == V1_VERSION
        assert p.provenance.prompt_hashes == original_prompts()[1]


@pytest.mark.parametrize("kind", ["parse", "context", "dry_run"])
def test_v1_arm_is_preserved_on_all_rejection_paths(kind):
    db = store()
    provider = StructuredDouble(malformed=kind == "parse", target="invented_setting" if kind == "dry_run" else "_BASE_SYSTEM")
    if kind == "context":
        db.load_trace.return_value = None
    p = run_critic(Alert(trace_id="t", agent_name="a", failure_type="HALLUCINATION"), db,
                   llm_factory=lambda **_: provider, config={"critic_arm": "v1_structured"})
    assert p.critic_arm == "v1_structured" and not p.dry_run_applied
    db.write_patch.assert_not_called()
    if kind == "parse":
        assert p.provenance.source == "fallback"
        assert len(provider.prompts) == 2
        assert p.provenance.input_tokens == 20  # no duplicate diagnosis accounting


def test_original_prompt_content_matches_phase1_bytes_and_rendering():
    templates, hashes = original_prompts()
    state = {"trace": trace(), "current_config": {"_BASE_SYSTEM": "old"}, "evidence": evidence(),
             "failure_type": "HALLUCINATION", "root_cause_analysis": "specific diagnosis"}
    for name in templates:
        assert templates[name] == git_source(f"services/critic/prompts/{name}.txt").decode("utf-8")
        assert len(hashes[name]) == 64
    expected = templates["root_cause"].format(failure_type="HALLUCINATION", span_count=1,
                                              formatted_trace=format_trace_for_prompt(trace()))
    assert json.loads(v1_prompt(state, diagnosis=True))["original_prompt"] == expected
    patch = json.loads(v1_prompt(state))["original_prompt"]
    assert "specific diagnosis" in patch and "Propose ONE concrete" in patch


def test_arm_config_and_environment_are_validated(monkeypatch):
    monkeypatch.setenv("CRITIC_ARM", "v1_structured")
    db, provider = store(), StructuredDouble()
    p = run_critic(Alert(trace_id="t", agent_name="a", failure_type="HALLUCINATION"), db,
                   llm_factory=lambda **_: provider)
    assert p.critic_arm == "v1_structured"
    with pytest.raises(ValueError):
        CriticConfig(critic_arm="old")
    with pytest.raises(ValueError):
        CriticConfig(critic_arm="new", typo=True)


@pytest.mark.parametrize("model", [StructuredPatch, StructuredDiagnosis])
def test_strict_schemas_inline_every_reference_and_require_nullable_fields(model):
    schema = response_schema(model)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert "$ref" not in json.dumps(schema) and "$defs" not in schema
    assert "default" not in json.dumps(schema)


def test_v1_diagnosis_uses_strict_transport_and_persistent_budget(tmp_path):
    requests = []
    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={"model": "deepseek-flash", "system_fingerprint": "fixture",
            "usage": {"prompt_tokens": 20, "completion_tokens": 10},
            "choices": [{"finish_reason": "tool_calls", "message": {"tool_calls": [
                {"function": {"name": "propose_patch", "arguments": '{}'}}]}}]})
    ledger = Round3Ledger(tmp_path / "calls.jsonl", "fixture")
    provider = DeepSeekProvider(ledger=ledger, api_key="fixture", client=httpx.Client(transport=httpx.MockTransport(handler)))
    provider.complete_diagnosis("fixture prompt")
    schema = requests[0]["tools"][0]["function"]["parameters"]
    assert "diagnosed_failure_type" in schema["properties"] and "patch_type" not in schema["properties"]
    assert ledger.rows()[0]["prompt_version"] == V1_VERSION
    assert provider.last_provenance.prompt_version == V1_VERSION
    assert "fixture prompt" not in ledger.path.read_text()


class Tripwire(dict):
    def __getitem__(self, key):
        if key not in {"pred", *VISIBLE_METADATA}:
            raise AssertionError(f"Forbidden field read: {key}")
        return super().__getitem__(key)

    def get(self, key, default=None):
        return self[key] if key in self else default

    def items(self):
        raise AssertionError("Unknown metadata must never be traversed")

    def __iter__(self):
        raise AssertionError("Unknown metadata must never be enumerated")


def test_detector_adapter_cannot_reach_label_or_injection_fields(monkeypatch):
    # Complete labels.csv header plus injection-only metadata/config names.
    forbidden = ("run_id trace_id task_id family split provider model fault rep label checker_pass "
        "loop misfire bleed drift hallucination abstained injection_effective plan_divergence "
        "plan_complete stop_reason n_steps llm_calls invalid_json final_answer gold label_v1 "
        "item_owners item_sessions item_users source injection_config DRIFT_CUSTOMER "
        "_GUESS_SYSTEM target_company canary").split()
    class Secret:
        def __str__(self):
            raise AssertionError("Forbidden value was serialized")
        def __deepcopy__(self, memo):
            raise AssertionError("Forbidden value was copied")
    prediction = Tripwire({k: Secret() for k in forbidden} | {"pred": "CONTEXT_BLEED"})
    view = view_fixture(("memory_read",))
    view.spans[0].metadata = Tripwire({k: Secret() for k in forbidden} | {"tool_name": "read_memory"})
    def no_io(*args, **kwargs):
        raise AssertionError("Adapter attempted filesystem IO")
    monkeypatch.setattr(builtins, "open", no_io)
    monkeypatch.setattr(Path, "open", no_io)
    ev = from_detector(prediction, view)
    assert ev.failure_type.value == "CONTEXT_BLEED"
    assert json.loads(ev.supporting_text)["metadata"] == {"tool_name": "read_memory"}
    assert set(inspect.signature(from_detector).parameters) == {"prediction", "view"}


def test_adapter_has_no_scoring_or_benchmark_imports():
    import ast
    import services.critic.detector_adapter as module
    tree = ast.parse(inspect.getsource(module))
    imports = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert imports <= {"nexus_agent.models", "services.critic.evidence"}
    direct = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert direct == {"json", "re"}


@pytest.mark.parametrize("ft", CLASSES)
def test_detector_prediction_and_observation_are_only_evidence_sources(ft):
    view = view_fixture(("tool_call", "memory_read", "agent_step"))
    before = view.model_dump(mode="json")
    ev = from_detector({"pred": ft, "label_v1": "NORMAL"}, view)
    assert ev.failure_type.value == ft and ev.span_id in {s.span_id for s in view.spans}
    assert "Phase 2 has no span attribution" in ev.supporting_text
    assert view.model_dump(mode="json") == before


def test_normal_empty_and_unsanitized_inputs_fail_closed():
    assert from_detector({"pred": "NORMAL"}, view_fixture()) is None
    with pytest.raises(ValueError, match="opaque"):
        from_detector({"pred": "HALLUCINATION"}, trace())
    empty = view_fixture()
    empty.spans = []
    with pytest.raises(ValueError, match="no observed"):
        from_detector({"pred": "HALLUCINATION"}, empty)
    with pytest.raises(ValueError):
        from_detector({"pred": "UNKNOWN"}, view_fixture())
    wrong = view_fixture()
    wrong.spans[0].trace_id = "other"
    with pytest.raises(ValueError, match="belong"):
        critic_view(wrong)


def test_oracle_adapter_requires_explicit_opt_in():
    with pytest.raises(ValueError, match="allow_oracle"):
        evidence_from_dev({"split": "dev", "label": "HALLUCINATION"}, trace())
    assert evidence_from_dev({"split": "dev", "label": "HALLUCINATION"}, trace(), allow_oracle=True)


TRUTH = GroundTruth(failure_type="HALLUCINATION", span_id="s1", step=1, span_ids=("s0", "s1", "s10"))


@pytest.mark.parametrize("citation,match", [
    ({"cited_span_id": "s1"}, True), ({"cited_step": 1}, True),
    ({"cited_span_id": "s1", "cited_step": 1}, True),
    ({"cited_span_id": "s10"}, False), ({"cited_step": 0}, False),
    ({"cited_span_id": "s1", "cited_step": 0}, False), ({"cited_step": -1}, False),
    ({"cited_step": True}, False), ({"cited_step": 100}, False), ({}, False),
])
def test_c3_exact_span_and_zero_based_step_matching(citation, match):
    result = score_c3({"diagnosed_failure_type": "HALLUCINATION", **citation}, TRUTH, detector_type="HALLUCINATION")
    assert result["type_match"] and result["step_span_match"] is match
    assert result["joint_match"] is match


def test_c3_does_not_mistake_alert_echo_or_incidental_span_text_for_diagnosis():
    result = score_c3({"failure_type": "HALLUCINATION", "root_cause_analysis": "I saw s1 and s10"},
                      TRUTH, detector_type="HALLUCINATION")
    assert not result["type_match"] and not result["step_span_match"]
    assert result["proposal_type_match"] and not result["diagnosis_present"]


@pytest.mark.parametrize("text,match", [
    ("FAILURE_TYPE: HALLUCINATION\nFAILURE_SPAN_ID: s1", True),
    ("FAILURE_TYPE: HALLUCINATION\nFAILURE_STEP: 1", True),
    ("FAILURE_TYPE: HALLUCINATION\nFAILURE_SPAN_ID: s1\nFAILURE_SPAN_ID: s10", False),
    ("FAILURE_TYPE: HALLUCINATION\nFAILURE_SPAN_ID: s10", False),
])
def test_c3_legacy_matching_is_explicit_and_unambiguous(text, match):
    result = score_c3({"root_cause_analysis": text}, TRUTH, detector_type="PLAN_DRIFT")
    assert result["step_span_match"] is match
    assert result["detector_wrong"]


def test_c3_reports_detector_errors_per_class_and_unknown_locations():
    correct = {"diagnosed_failure_type": "HALLUCINATION", "cited_span_id": "s1"}
    scores = [score_c3(correct, TRUTH, detector_type="PLAN_DRIFT"),
              score_c3(None, TRUTH, detector_type="NORMAL"),
              score_c3(correct, GroundTruth(failure_type="HALLUCINATION"), detector_type="HALLUCINATION")]
    report = summarize_c3(scores)
    wrong = report["detector_wrong"]["per_class"]["HALLUCINATION"]
    assert wrong["n"] == 2 and wrong["type_match"]["successes"] == 1
    assert wrong["step_span_match"]["total"] == 2
    assert report["overall"]["unknown_truth_location"] == 1
    assert report["per_class"]["PLAN_DRIFT"]["n"] == 0
    fallback = {**correct, "provenance": {"source": "fallback"}}
    assert not score_c3(fallback, TRUTH, detector_type="HALLUCINATION")["joint_match"]


@pytest.mark.parametrize("ft,kinds,expected", [
    ("HALLUCINATION", ("tool_call", "agent_step"), 1),
    ("LOOP_DETECTED", ("tool_call", "tool_call", "tool_call"), 2),
    ("TOOL_MISFIRE", ("tool_call", "tool_call"), 0),
    ("CONTEXT_BLEED", ("memory_read", "memory_read"), 1),
    ("PLAN_DRIFT", ("tool_call", "tool_call"), 1),
])
def test_truth_localization_uses_fault_firing_origin(ft, kinds, expected):
    t = view_fixture(kinds)
    if ft == "TOOL_MISFIRE":
        t.spans[0].error_type = "ToolError"
    if ft == "CONTEXT_BLEED":
        for i, s in enumerate(t.spans):
            s.metadata.update(user_id="u1", item_owners=["u1" if i == 0 else "u2"])
    if ft == "PLAN_DRIFT":
        t.spans[1].input = '{"customer_id":"C-FAULT"}'
    gt = truth_from_dev({"split": "dev", "label": ft}, t,
                        allowed_owners={"u1": {"u1"}}, drift_id="C-FAULT")
    assert gt.step == expected and gt.span_id == f"s{expected}"


def test_truth_unknown_is_not_filled_with_detector_location_and_test_is_rejected():
    gt = truth_from_dev({"split": "dev", "label": "CONTEXT_BLEED"}, view_fixture(("memory_read",)), allowed_owners={})
    assert gt.step is None and gt.span_id is None
    with pytest.raises(ValueError, match="DEV"):
        truth_from_dev({"split": "test"}, None)
    with pytest.raises(ValueError, match="disagree"):
        GroundTruth(failure_type="HALLUCINATION", span_id="s0", step=1, span_ids=("s0", "s1"))


def test_proxy_sample_balances_twenty_strata_and_keeps_verdict_in_separate_key(tmp_path):
    rows = [{"trace_id": f"t{i}", "arm": arm, "failure_type": ft,
             "proposal": {"patch_content": "A specific saved patch", "proposal_id": str(i)},
             "evidence": {"supporting_text": "Observed evidence"},
             "grounding": {"grounded": True, "matches": {"tool": ["example"]}}}
            for ft in CLASSES for arm in ARMS for i in range(3)]
    chosen = sample_records(rows)
    assert len(chosen) == 20 and chosen == sample_records(list(reversed(rows)))
    assert len({(r["failure_type"], r["arm"]) for r in chosen}) == 20
    for arm in ARMS:
        (tmp_path / f"{arm}.jsonl").write_text("\n".join(json.dumps(r) for r in rows if r["arm"] == arm), encoding="utf-8")
    write_sample(tmp_path, tmp_path / "out")
    sheet = (tmp_path / "out/proxy_sample.md").read_text(encoding="utf-8")
    assert sheet.count("| | |") == 20 and '"grounded"' not in sheet
    key = json.loads((tmp_path / "out/proxy_sample_key.json").read_text())
    assert len(key["samples"]) == 20 and key["samples"][0]["grounding"]["grounded"]
    with pytest.raises(ValueError, match="Missing"):
        sample_records([])


def test_part_b_aggregate_cap_survives_restart(tmp_path):
    ledger = Round3Ledger(tmp_path / "calls.jsonl", "unit")
    ledger.arm = "original"
    ledger.append({"call_id": "old", "status": "reserved", "cost_usd": .99})
    resumed = Round3Ledger(ledger.path, "unit")
    resumed.arm = "new"
    with pytest.raises(BudgetExceeded):
        resumed.append({"call_id": "new", "status": "reserved", "cost_usd": .02})
    assert resumed.spent == .99
    assert resumed.rows()[0]["evidence_mode"] == "detector"


@pytest.mark.parametrize("branch,object_id,dirty", [("phase-3-critic", "same", ""),
    ("main", "changed", ""), ("main", "same", " M code.py")])
def test_part_b_preflight_requires_main_clean_and_exact_bench_revision(monkeypatch, tmp_path, branch, object_id, dirty):
    import services.critic.round3_part_b as module
    def git(*args):
        assert args[0] in {"branch", "status", "rev-parse"}  # no git mutation
        if args[0] == "branch":
            return branch
        if args[0] == "status":
            return dirty
        return object_id if args[-1].startswith("HEAD:") else "same"
    monkeypatch.setattr(module, "git", git)
    monkeypatch.setattr(module, "OUT", tmp_path)
    with pytest.raises(RuntimeError):
        module.preflight()


def test_part_b_three_arms_use_views_only_and_keep_detector_misses(tmp_path):
    import services.critic.round3_part_b as module
    raw = trace()
    raw.spans[0].metadata["gold"] = "SECRET ORACLE VALUE"
    sanitized = raw.model_copy(deep=True, update={"trace_id": VID})
    sanitized.spans[0].trace_id = VID
    sanitized = critic_view(sanitized)
    rows = [{"trace_id": tid, "split": "dev", "label": "HALLUCINATION"} for tid in ("a", "b")]
    predictions = {"a": {"pred": "HALLUCINATION"}, "b": {"pred": "NORMAL"}}
    ledger = Round3Ledger(tmp_path / "calls.jsonl", "fixture")
    class FreeTextDouble:
        def __init__(self):
            self.last_provenance = Provenance(source="llm", model="fixture", model_version="unit", temperature=.2)
            self.prompts = []
        def complete(self, prompt):
            self.prompts.append(prompt)
            assert "SECRET ORACLE VALUE" not in prompt
            ledger.append({"call_id": f"original-{len(self.prompts)}", "status": "reserved",
                "cost_usd": .01, "input_tokens": 10, "output_tokens": 20, "latency_ms": 1})
            if len(self.prompts) % 2:
                return "FAILURE_SPAN_ID: s\nROOT_CAUSE: An unsupported claim"
            return json.dumps(response())
    class EmbeddingsDouble:
        def encode(self, texts):
            return np.ones((len(texts), 1)), [1]*len(texts)
    providers = {"original": FreeTextDouble(), "v1_structured": StructuredDouble(ledger=ledger),
                 "new": StructuredDouble(ledger=ledger)}
    summary = run_experiment(rows, {"a": raw, "b": raw}, predictions,
        {"a": sanitized, "b": sanitized},
        {"a": from_detector(predictions["a"], sanitized), "b": None},
        legacy=OriginalCritic(), providers=providers, ledger=ledger,
        config={"_BASE_SYSTEM": "Existing baseline prompt"}, embedder=EmbeddingsDouble(), output=tmp_path)
    assert summary["status"] == "complete" and ledger.spent == pytest.approx(.05)
    assert set(summary["arms"]) == set(module.ARMS)
    for arm in module.ARMS:
        result = summary["arms"][arm]["overall"]
        assert result["selected_dev_failures"] == 2 and result["proposals"] == 1
        assert result["detector_misses"] == 1 and result["C3"]["detector_wrong"]["overall"]["n"] == 1
        saved = [json.loads(line) for line in (tmp_path / f"{arm}.jsonl").read_text().splitlines()]
        assert saved[0]["proposal"]["critic_arm"] == arm and saved[1]["proposal"] is None
    for arm in ("new", "v1_structured"):
        assert "SECRET ORACLE VALUE" not in json.dumps(providers[arm].prompts)
