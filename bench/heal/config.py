"""Agent config, config diffs ("patches"), hashing and the injection tag.

The NexusBench agent's behaviour is set by three values that live in
``bench/agent.py`` and ``bench/tools.py`` (the same three that the Phase 3
critic snapshots in ``services/critic/dev_adapter.current_config``):

    system_prompt   the system prompt sent with every LLM call
    MAX_STEPS       the actor step budget
    TOOL_SPECS      the tool list the prompt advertises (names, args, descriptions)

Only the HALLUCINATION fault lives in this config: it swaps the system prompt
for one that rewards guessing. Every other fault is in the tool backend
(``bench.tools.Toolbox``), which a config patch cannot touch.

A patch is a list of ``replace`` operations on JSON-pointer paths that already
exist (RFC 6901 paths, RFC 6902 ``replace`` semantics). Replacing a top-level key
(``/system_prompt``) is how the Phase 3 critic writes patches. Deeper paths
(``/TOOL_SPECS/1/description``) work too.
"""

from __future__ import annotations

import copy
import difflib
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from bench import agent as _agent
from bench import tools as _tools

CONFIG_KEYS = ("system_prompt", "MAX_STEPS", "TOOL_SPECS")
MAX_STEPS_LIMIT = 30  # a patch may raise the step budget, within a bound on cost

# Phase 3 snapshots the active prompt under the module constant's name.
PHASE3_KEY_ALIASES = {"_BASE_SYSTEM": "system_prompt", "_GUESS_SYSTEM": "system_prompt"}


class PatchError(ValueError):
    """The patch cannot be applied to this config (unknown path, wrong type, bad value)."""


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False)


def sha256_of(obj: Any) -> str:
    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def clean_config() -> dict[str, Any]:
    """The agent's config with no fault injected."""
    return {"system_prompt": _agent._BASE_SYSTEM, "MAX_STEPS": _agent.MAX_STEPS,
            "TOOL_SPECS": copy.deepcopy(_tools.TOOL_SPECS)}


def faulted_config(fault: str) -> dict[str, Any]:
    """The deployed config under ``fault``: identical to clean except for HALLUCINATION."""
    if fault not in _tools.FAULTS:
        raise ValueError(f"unknown fault {fault!r}")
    cfg = clean_config()
    if fault == "HALLUCINATION":
        cfg["system_prompt"] = _agent._GUESS_SYSTEM
    return cfg


def base_tag(fault: str) -> str:
    """Short name of the base config a patch is applied to (part of every run id)."""
    return "guess" if fault == "HALLUCINATION" else "clean"


def config_hash(cfg: dict[str, Any]) -> str:
    return sha256_of({k: cfg[k] for k in CONFIG_KEYS})


# -- JSON pointer -------------------------------------------------------------

def _tokens(path: str) -> list[str]:
    if not path.startswith("/"):
        raise PatchError(f"path must be a JSON pointer starting with '/': {path!r}")
    return [t.replace("~1", "/").replace("~0", "~") for t in path[1:].split("/")]


def _resolve(doc: Any, path: str) -> tuple[Any, str | int]:
    toks = _tokens(path)
    if not toks or toks == [""]:
        raise PatchError("replacing the whole config is not allowed; name a key")
    node = doc
    for t in toks[:-1]:
        node = _child(node, t, path)
    last: str | int = toks[-1]
    if isinstance(node, list):
        last = _index(node, str(last), path)
    elif isinstance(node, dict):
        if last not in node:
            raise PatchError(f"unknown config path {path!r}")
    else:
        raise PatchError(f"path {path!r} goes through a scalar")
    return node, last


def _index(node: list, tok: str, path: str) -> int:
    if not tok.isdigit() or int(tok) >= len(node):
        raise PatchError(f"bad list index in {path!r}")
    return int(tok)


def _child(node: Any, tok: str, path: str) -> Any:
    if isinstance(node, dict):
        if tok not in node:
            raise PatchError(f"unknown config path {path!r}")
        return node[tok]
    if isinstance(node, list):
        return node[_index(node, tok, path)]
    raise PatchError(f"path {path!r} goes through a scalar")


# -- patches ------------------------------------------------------------------

@dataclass(frozen=True)
class ConfigPatch:
    """A config diff. ``ops`` = [{"op": "replace", "path": "/key", "value": ...}, ...]."""

    ops: tuple[dict[str, Any], ...]
    source: str = ""          # e.g. "none", "generic:PLAN_DRIFT", "critic:<arm>"
    note: str = ""            # free text for reports; not part of the hash

    @staticmethod
    def none() -> ConfigPatch:
        return ConfigPatch(ops=(), source="none")

    @property
    def is_empty(self) -> bool:
        return not self.ops

    def canonical_ops(self) -> list[dict[str, Any]]:
        out = []
        for op in self.ops:
            if set(op) != {"op", "path", "value"} or op["op"] != "replace":
                raise PatchError(f"only {{op: replace, path, value}} ops are supported: {op}")
            out.append({"op": "replace", "path": str(op["path"]), "value": op["value"]})
        return out

    @property
    def patch_hash(self) -> str:
        """Content hash of the diff alone (the same diff has the same hash wherever it came from)."""
        return sha256_of(self.canonical_ops())

    def to_json(self) -> dict[str, Any]:
        return {"ops": self.canonical_ops(), "source": self.source, "note": self.note,
                "patch_hash": self.patch_hash}

    @staticmethod
    def from_json(d: dict[str, Any]) -> ConfigPatch:
        p = ConfigPatch(ops=tuple(d["ops"]), source=d.get("source", ""), note=d.get("note", ""))
        if "patch_hash" in d and d["patch_hash"] != p.patch_hash:
            raise PatchError("patch_hash does not match the ops")
        return p


def apply_patch(cfg: dict[str, Any], patch: ConfigPatch) -> dict[str, Any]:
    """Return a patched deep copy of ``cfg``. Never mutates ``cfg``; never executes text."""
    out = copy.deepcopy(cfg)
    for op in patch.canonical_ops():
        parent, key = _resolve(out, op["path"])
        old, new = parent[key], copy.deepcopy(op["value"])
        if type(new) is not type(old):
            raise PatchError(f"{op['path']}: value type {type(new).__name__} does not match "
                             f"{type(old).__name__}")
        parent[key] = new
    validate_config(out)
    return out


def validate_config(cfg: dict[str, Any]) -> None:
    if set(cfg) != set(CONFIG_KEYS):
        raise PatchError(f"config keys must be exactly {CONFIG_KEYS}")
    if not isinstance(cfg["system_prompt"], str) or not cfg["system_prompt"].strip():
        raise PatchError("system_prompt must be a non-empty string")
    ms = cfg["MAX_STEPS"]
    if not isinstance(ms, int) or isinstance(ms, bool) or not 1 <= ms <= MAX_STEPS_LIMIT:
        raise PatchError(f"MAX_STEPS must be an int in [1, {MAX_STEPS_LIMIT}]")
    specs = cfg["TOOL_SPECS"]
    if not isinstance(specs, list) or not all(
            isinstance(t, dict) and isinstance(t.get("name"), str)
            and isinstance(t.get("args"), dict) and isinstance(t.get("description"), str)
            for t in specs):
        raise PatchError("TOOL_SPECS must be a list of {name, args, description}")
    canonical_json(cfg)  # JSON-serialisable, no NaN


def from_phase3(target_component: str, patch_content: str) -> ConfigPatch:
    """Adapt a Phase 3 critic proposal (whole-key replacement) to a ConfigPatch.

    String keys take ``patch_content`` verbatim; other keys take it as JSON
    (the same rule as ``services/critic/registry.ConfigRegistry.apply``).
    """
    key = PHASE3_KEY_ALIASES.get(target_component, target_component)
    if key not in CONFIG_KEYS:
        raise PatchError(f"unknown config key {target_component!r}")
    value: Any = patch_content if key == "system_prompt" else json.loads(patch_content)
    return ConfigPatch(ops=({"op": "replace", "path": f"/{key}", "value": value},),
                       source=f"phase3:{target_component}")


# -- injection tag (pre-registration 1e) -----------------------------------------

def _injected_segments(clean: str, faulted: str) -> list[str]:
    sm = difflib.SequenceMatcher(a=clean, b=faulted, autojunk=False)
    return [faulted[j1:j2].strip() for tag, _, _, j1, j2 in sm.get_opcodes()
            if tag in ("insert", "replace") and faulted[j1:j2].strip()]


def injection_tag(patch: ConfigPatch, fault: str) -> str:
    """``reverts_injection`` or ``other_fix``, by a deterministic diff against the clean config.

    A patch reverts the injection if, for some path where the faulted config
    differs from the clean one, the patched value equals the clean value or (for
    strings) no longer contains every injected segment verbatim. Faults that are
    not in the config (all but HALLUCINATION) have no injected paths, so every
    patch for them is ``other_fix``. The empty patch is ``none``.
    """
    if patch.is_empty:
        return "none"
    clean, faulted = clean_config(), faulted_config(fault)
    patched = apply_patch(faulted, patch)
    for key in CONFIG_KEYS:
        if clean[key] == faulted[key]:
            continue
        if patched[key] == clean[key]:
            return "reverts_injection"
        if isinstance(faulted[key], str):
            segs = _injected_segments(clean[key], faulted[key])
            if any(s not in patched[key] for s in segs):
                return "reverts_injection"
    return "other_fix"
