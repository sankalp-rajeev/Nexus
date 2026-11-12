"""Config diffs, hashing and the reverts_injection / other_fix tag."""

from __future__ import annotations

import pytest

from bench import agent as bench_agent
from bench.heal.config import (ConfigPatch, PatchError, apply_patch, clean_config, config_hash,
                               faulted_config, from_phase3, injection_tag)
from bench.heal.generic import Inapplicable, generic_patch

GUESS_TAIL = bench_agent._GUESS_SYSTEM[len(bench_agent._BASE_SYSTEM):]


def rep(path, value, source="t"):
    return ConfigPatch(ops=({"op": "replace", "path": path, "value": value},), source=source)


def test_only_hallucination_lives_in_the_config():
    clean = clean_config()
    for fault in ("NONE", "CONTEXT_BLEED", "PLAN_DRIFT", "TOOL_MISFIRE", "LOOP_DETECTED"):
        assert faulted_config(fault) == clean
    assert faulted_config("HALLUCINATION")["system_prompt"] == bench_agent._GUESS_SYSTEM


def test_apply_replaces_without_mutating():
    cfg = clean_config()
    out = apply_patch(cfg, rep("/MAX_STEPS", 12))
    assert out["MAX_STEPS"] == 12 and cfg["MAX_STEPS"] == bench_agent.MAX_STEPS
    out = apply_patch(cfg, rep("/TOOL_SPECS/1/description", "Use `id`."))
    assert out["TOOL_SPECS"][1]["description"] == "Use `id`."
    assert cfg["TOOL_SPECS"][1]["description"] != "Use `id`."


@pytest.mark.parametrize("patch", [
    rep("/nope", "x"),                       # unknown key
    rep("/TOOL_SPECS/99/name", "x"),         # bad index
    rep("/MAX_STEPS", "15"),                 # type change
    rep("/MAX_STEPS", 0),                    # out of bounds
    rep("/MAX_STEPS", 31),
    rep("/system_prompt", "   "),            # empty prompt
    rep("", {}),                             # whole-config replacement
    ConfigPatch(ops=({"op": "add", "path": "/x", "value": 1},)),
])
def test_bad_patches_are_rejected(patch):
    with pytest.raises(PatchError):
        apply_patch(clean_config(), patch)


def test_patch_hash_is_content_only():
    a = rep("/MAX_STEPS", 10, source="a")
    b = rep("/MAX_STEPS", 10, source="b")
    assert a.patch_hash == b.patch_hash != rep("/MAX_STEPS", 11).patch_hash
    assert ConfigPatch.from_json(a.to_json()).patch_hash == a.patch_hash
    bad = {**a.to_json(), "patch_hash": "0" * 64}
    with pytest.raises(PatchError):
        ConfigPatch.from_json(bad)


def test_config_hash_changes_with_any_value():
    c = clean_config()
    assert config_hash(c) == config_hash(clean_config())
    assert config_hash(c) != config_hash(faulted_config("HALLUCINATION"))
    assert config_hash(c) != config_hash(apply_patch(c, rep("/TOOL_SPECS/0/description", "x")))


def test_injection_tag():
    assert injection_tag(ConfigPatch.none(), "HALLUCINATION") == "none"
    revert = rep("/system_prompt", bench_agent._BASE_SYSTEM)
    assert injection_tag(revert, "HALLUCINATION") == "reverts_injection"
    # Deleting part of the injected sentence neutralises it: still a revert.
    partial = rep("/system_prompt", bench_agent._GUESS_SYSTEM.replace(
        ", and never say that you don't know or that information is missing", ""))
    assert injection_tag(partial, "HALLUCINATION") == "reverts_injection"
    # Contradicting the injection without removing it is another fix.
    append = rep("/system_prompt", bench_agent._GUESS_SYSTEM + " If a fact is missing, say so.")
    assert injection_tag(append, "HALLUCINATION") == "other_fix"
    # A rewritten prompt that keeps the injected text verbatim is not a revert.
    keep = rep("/system_prompt", "Be careful." + GUESS_TAIL)
    assert injection_tag(keep, "HALLUCINATION") == "other_fix"
    # Faults outside the config cannot be reverted by a config diff.
    for fault in ("CONTEXT_BLEED", "PLAN_DRIFT", "TOOL_MISFIRE", "LOOP_DETECTED"):
        assert injection_tag(revert, fault) == "other_fix"
    assert injection_tag(rep("/MAX_STEPS", 4), "HALLUCINATION") == "other_fix"


def test_phase3_adapter():
    p = from_phase3("_GUESS_SYSTEM", "New prompt.")
    assert p.ops[0] == {"op": "replace", "path": "/system_prompt", "value": "New prompt."}
    assert from_phase3("MAX_STEPS", "10").ops[0]["value"] == 10
    with pytest.raises(PatchError):
        from_phase3("memory_store", "{}")


def test_generic_templates_map_to_real_keys_or_are_inapplicable():
    h = generic_patch("HALLUCINATION")
    assert h.ops[0]["path"] == "/system_prompt"
    assert h.ops[0]["value"].startswith(bench_agent._GUESS_SYSTEM + " INSTRUCTION:")
    assert injection_tag(h, "HALLUCINATION") == "other_fix"
    d = generic_patch("PLAN_DRIFT")
    assert d.ops[0]["value"].startswith(bench_agent._BASE_SYSTEM + " RULE:")
    assert generic_patch("LOOP_DETECTED").ops == ({"op": "replace", "path": "/MAX_STEPS",
                                                    "value": 15},)
    for fault in ("CONTEXT_BLEED", "TOOL_MISFIRE"):
        with pytest.raises(Inapplicable):
            generic_patch(fault)
