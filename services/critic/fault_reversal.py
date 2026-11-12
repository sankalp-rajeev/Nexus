"""SCORING ONLY. Compare proposals with clean/injected config snapshots.

This module is never imported by graph, prompt, provider or detector adapter.
Bench injectors other than the hallucination system prompt change runtime data
or backend behavior, not the agent registry; no config reversal is inferred there.
"""
import ast
import copy
import hashlib
import json

from services.critic.hardening import literal
from services.critic.round2_legacy import git_source


def phase1_config_constants():
    """Read literal constants at the original benchmark ref, without exec/import."""
    values = {}
    for path, names in (("bench/agent.py", {"_BASE_SYSTEM", "_GUESS_SYSTEM", "MAX_STEPS"}),
                        ("bench/tools.py", {"TOOL_SPECS"})):
        tree = ast.parse(git_source(path).decode("utf-8"))
        for node in tree.body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                name = node.targets[0].id
                if name in names:
                    value = node.value
                    if isinstance(value, ast.BinOp) and isinstance(value.op, ast.Add) and isinstance(value.left, ast.Name):
                        values[name] = values[value.left.id] + ast.literal_eval(value.right)
                    else:
                        values[name] = ast.literal_eval(value)
    return values


def snapshots(label, *, constants=None):
    if label.get("split") != "dev":
        raise ValueError("Fault reversal scoring is DEV only")
    if constants is None:
        from bench import agent
        constants = {k: getattr(agent, k) for k in ("_BASE_SYSTEM", "_GUESS_SYSTEM", "MAX_STEPS", "TOOL_SPECS")}
    active = "_GUESS_SYSTEM" if label.get("fault") == "HALLUCINATION" else "_BASE_SYSTEM"
    injected = {active: constants[active], "MAX_STEPS": constants["MAX_STEPS"],
                "TOOL_SPECS": copy.deepcopy(constants["TOOL_SPECS"])}
    clean = {**copy.deepcopy(injected), active: constants["_BASE_SYSTEM"]}
    return injected, clean


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def tag_fix(proposal, injected, clean):
    """Tag exact restoration of an actually changed leaf at an existing config key.

    Diff values stay hashed in reports. Invalid/missing target or unparseable
    replacement cannot claim a config reversal. No fuzzy or semantic matching.
    """
    key = proposal.target_component
    changes = []
    reverts = []
    if key not in injected or key not in clean:
        return {"fix_tag": "other_fix", "clean_config_diff": [], "restored_paths": []}
    replacement = proposal.patch_content if isinstance(injected[key], str) else literal(proposal.patch_content)

    def walk(before, after, patched, path):
        if isinstance(before, dict) and isinstance(after, dict) and isinstance(patched, dict):
            for k in sorted(before.keys() | after.keys() | patched.keys()):
                if k not in before or k not in after or k not in patched:
                    changes.append({"path": path + [k], "kind": "missing_key"})
                else:
                    walk(before[k], after[k], patched[k], path + [k])
        elif isinstance(before, list) and isinstance(after, list) and isinstance(patched, list) and len(before) == len(after) == len(patched):
            for i, (b, a, p) in enumerate(zip(before, after, patched)):
                walk(b, a, p, path + [i])
        else:
            restores = (type(before) is type(after) is type(patched) and before != after and patched == after)
            if restores:
                reverts.append(path)
            if type(patched) is not type(after) or patched != after or restores:
                changes.append({"path": path, "injected_sha256": _digest(before),
                    "clean_sha256": _digest(after), "proposed_sha256": _digest(patched),
                    "restores_injected_value": restores})
    walk(injected[key], clean[key], replacement, [key])
    return {"fix_tag": "reverts_injection" if reverts else "other_fix",
            "clean_config_diff": changes, "restored_paths": reverts}
