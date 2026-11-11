"""Handmade tests for Part B hardening, scoring-only tags and fail-closed gating."""
import copy
import json

import pytest
from nexus_agent.models import PatchProposal

from services.critic.fault_reversal import snapshots, tag_fix
from services.critic.hardening import inspect_patch
from services.critic.leak_assert import EvidenceLeakError, assert_no_evidence_leaks, audit_evidence
from services.critic.proposal import StructuredDiagnosis, StructuredPatch
from services.critic.registry import BadReferenceError, ConfigRegistry, NoOpPatchError
from services.critic.round3_audit import binary_agreement, score_proxy
from tests.unit.critic.test_groundwork import evidence, response


def config():
    return {"_BASE_SYSTEM": "Original prompt text", "MAX_STEPS": 8,
            "TOOL_SPECS": [{"name": "get_order", "args": {"order_id": "string"}, "description": "Orders"},
                           {"name": "read_memory", "args": {}, "description": "Saved notes"}]}


def proposal(content, target="_BASE_SYSTEM", patch_type="PROMPT_PATCH"):
    return PatchProposal.model_validate({**response(patch_content=content, target_component=target, patch_type=patch_type),
        "trace_id": "fixture", "alert_id": "fixture", "failure_type": "HALLUCINATION"})


@pytest.mark.parametrize("key,patch_type", [("_BASE_SYSTEM", "PROMPT_PATCH"),
    ("MAX_STEPS", "RETRY_POLICY_PATCH"), ("TOOL_SPECS", "TOOL_CONFIG_PATCH")])
def test_exact_no_op_flagged_and_rejected_for_each_registry_value_type(key, patch_type):
    cfg = config()
    value = cfg[key]
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True, indent=2)
    p = proposal(text, key, patch_type)
    assert inspect_patch(p, cfg).no_op
    with pytest.raises(NoOpPatchError):
        ConfigRegistry(cfg).apply(p)


@pytest.mark.parametrize("content,expected", [
    ('{"tool_name":"memory_read","args":{}}', "unknown tool: memory_read"),
    ('{"tool":"get_order","args":{"id":"B-1000"}}', "unknown argument: get_order.id"),
    ('{"tool_specs":[{"name":"lookup_order","args":{"order_id":"B-1000"}}]}', "unknown tool: lookup_order"),
    ('{"tool_name":"read_memory","argument_schema":{"properties":{"user_id":{"type":"string"}},"required":["user_id"]}}', "unknown argument: read_memory.user_id"),
    ("Call lookup_order(order_id='B-1000') before answering.", "unknown tool: lookup_order"),
    ("Use read_memory(user_id='u-1000') to retrieve notes.", "unknown argument: read_memory.user_id"),
    ("Use the tool named memory_read to get the notes.", "unknown tool: memory_read"),
    ("Pass user_id to read_memory when retrieving notes.", "unknown argument: read_memory.user_id"),
    ("Call read_memory with user_id to scope the lookup.", "unknown argument: read_memory.user_id"),
    ("Call read_memory (user_id='u-1000') for notes.", "unknown argument: read_memory.user_id"),
    ("Call read_memory('u-1000') for notes.", "unknown positional argument: read_memory[0]"),
])
def test_explicit_bad_tool_or_argument_reference_rejected(content, expected):
    p = proposal(content)
    assert expected in inspect_patch(p, config()).bad_references
    with pytest.raises(BadReferenceError, match="Bad tool reference"):
        ConfigRegistry(config()).apply(p)


@pytest.mark.parametrize("content", [
    "Call get_order(order_id='B-1000'), then use read_memory() for saved notes.",
    "The current user_id is metadata. Filter returned notes without passing new arguments.",
    "Do not repeat an identical tool call. Hash the response with hash(tool_response).",
    "A validation error (e.g. 422) calls for another approach (such as checking the tool spec).",
    "Use user_id from the session for context. Serialize a result with json.dumps(result).",
    "Identify the span(s) supporting each fact. Use canonical_json(args) to hash a signature.",
])
def test_valid_tools_arguments_and_incidental_metadata_are_allowed(content):
    p = proposal(content)
    assert not inspect_patch(p, config()).bad_references
    assert ConfigRegistry(config()).apply(p)["_BASE_SYSTEM"] == content


def test_no_op_and_bad_reference_checks_are_independent_and_do_not_mutate_snapshot():
    cfg = config()
    cfg["_BASE_SYSTEM"] = "Call lookup_order(order_id='B-1000')"
    before = copy.deepcopy(cfg)
    result = inspect_patch(proposal(cfg["_BASE_SYSTEM"]), cfg)
    assert result.no_op and result.bad_references
    assert cfg == before


def test_fault_reversal_restores_any_changed_leaf_without_using_labels_in_schema():
    injected = {"memory": {"scope": "all", "limit": 8}}
    clean = {"memory": {"scope": "user", "limit": 8}}
    p = proposal('{"scope":"user","limit":4}', "memory", "MEMORY_PATCH")
    tag = tag_fix(p, injected, clean)
    assert tag["fix_tag"] == "reverts_injection"
    assert tag["restored_paths"] == [["memory", "scope"]]
    assert tag["clean_config_diff"]
    assert "fix_tag" not in StructuredPatch.model_json_schema()["properties"]
    assert "clean_config_diff" not in StructuredDiagnosis.model_json_schema()["properties"]


@pytest.mark.parametrize("content,target,expected", [("clean prompt", "_GUESS_SYSTEM", "reverts_injection"),
    ("clean prompt with extra guard", "_GUESS_SYSTEM", "other_fix"),
    ("clean prompt", "missing_target", "other_fix")])
def test_fault_reversal_requires_exact_restoration_at_a_real_injected_target(content, target, expected):
    p = proposal(content, target)
    assert tag_fix(p, {"_GUESS_SYSTEM": "guess prompt"}, {"_GUESS_SYSTEM": "clean prompt"})["fix_tag"] == expected


def test_clean_no_op_is_not_an_injection_reversal_and_snapshots_are_scoring_only():
    p = proposal("clean prompt", "_BASE_SYSTEM")
    assert tag_fix(p, {"_BASE_SYSTEM": "clean prompt"}, {"_BASE_SYSTEM": "clean prompt"})["fix_tag"] == "other_fix"
    constants = {"_BASE_SYSTEM": "base", "_GUESS_SYSTEM": "guess", "MAX_STEPS": 8, "TOOL_SPECS": []}
    injected, clean = snapshots({"split": "dev", "fault": "HALLUCINATION"}, constants=constants)
    assert injected["_GUESS_SYSTEM"] == "guess" and clean["_GUESS_SYSTEM"] == "base"
    with pytest.raises(ValueError, match="DEV"):
        snapshots({"split": "test"}, constants=constants)


@pytest.mark.parametrize("leak", ["dev_label", "item_users", "item_sessions", "item_owners", "CANARY-AB1234", "SYSTEM NOTICE TO ASSISTANT"])
def test_leak_gate_persists_failure_and_raises_without_rewriting_evidence(tmp_path, leak):
    ev = evidence(supporting_text=f"Observed {leak}")
    original = ev.model_dump_json()
    with pytest.raises(EvidenceLeakError) as caught:
        assert_no_evidence_leaks({"fixture": ev}, tmp_path / "leak.json",
                                injection_texts={"notice": "SYSTEM NOTICE TO ASSISTANT"})
    assert caught.value.audit["evidence_with_leaks"] == 1
    assert json.loads((tmp_path / "leak.json").read_text())["status"] == "failed"
    assert ev.model_dump_json() == original


def test_leak_gate_counts_unique_evidence_arm_instances_and_misses():
    audit = audit_evidence({"a": evidence(), "b": None}, injection_texts={})
    assert audit["status"] == "passed" and audit["traces_checked"] == 2
    assert audit["evidence_checked"] == 1 and audit["detector_arm_evidence_instances_checked"] == 2
    assert audit["detector_misses_without_evidence"] == 1


def test_kappa_hand_calculated_and_degenerate_cases():
    result = binary_agreement([(True, True), (False, False), (True, False), (False, True)])
    assert result["agreement"] == .5 and result["cohens_kappa"] == 0
    assert binary_agreement([(True, True), (False, False)])["cohens_kappa"] == 1
    assert binary_agreement([(True, True)])["cohens_kappa"] is None
    assert binary_agreement([])["agreement"] is None


def test_proxy_unclear_sensitivity_matches_handmade_twenty_case_sheet(tmp_path):
    sheet = "\n".join(f"## P{i:02d}\n| {'unclear' if i <= 10 else 'grounded'} | reason |" for i in range(1, 21))
    key = {"samples": [{"sample_id": f"P{i:02d}", "grounding": {"grounded": i <= 10}} for i in range(1, 21)]}
    sheet_path, key_path = tmp_path / "sheet.md", tmp_path / "key.json"
    sheet_path.write_text(sheet, encoding="utf-8")
    key_path.write_text(json.dumps(key), encoding="utf-8")
    result = score_proxy(sheet_path, key_path)
    assert result["unclear_as_ungrounded"]["cohens_kappa"] == -1
    assert result["unclear_as_grounded"]["agreement"] == .5
    assert result["counts"] == {"unclear": 10, "grounded": 10}


def test_runner_leak_failure_occurs_before_any_provider_or_embedding_model(tmp_path, monkeypatch):
    import sys
    import services.critic.round3_part_b as module
    monkeypatch.setattr(sys, "argv", ["part_b"])
    monkeypatch.setattr(module, "preflight", lambda: None)
    monkeypatch.setattr(module, "OUT", tmp_path)
    monkeypatch.setattr(module, "load_inputs", lambda: ([], {}, {}, {}, {
        "fixture": evidence(supporting_text="request failed (code 422)")}))
    def forbidden(*args, **kwargs):
        raise AssertionError("A model/provider was constructed despite evidence leak")
    for name in ("OriginalCritic", "MiniLMEmbeddings", "DeepSeekProvider", "OriginalDeepSeek"):
        monkeypatch.setattr(module, name, forbidden)
    with pytest.raises(EvidenceLeakError):
        module.main()
    assert not (tmp_path / "protocol.json").exists()
    assert not (tmp_path / "calls.jsonl").exists()


def test_part_b_preflight_allows_tracked_report_changes_but_not_code_changes(tmp_path, monkeypatch):
    import services.critic.round3_part_b as module
    def git(*args):
        if args[0] == "branch":
            return "phase-3-critic"
        if args[0] == "merge-base":
            assert args[1:] == ("--is-ancestor", "origin/main", "HEAD")
            return ""
        if args[0] == "status":
            return " M reports/phase3/proxy_sample.md"
        return "same-object"
    monkeypatch.setattr(module, "git", git)
    monkeypatch.setattr(module, "OUT", tmp_path)
    module.preflight()
