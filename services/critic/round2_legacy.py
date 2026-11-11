"""Execute exact Phase 1 critic sources with isolated imports and observation hooks."""
from __future__ import annotations

import builtins
import hashlib
import subprocess
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Pinned commit of the phase-1-nexusbench branch tip (in main's history), so a
# fresh clone or CI checkout resolves it without the local branch.
BASE = "75c17e2e168afed5a66e0fab2fd2112cdbf83ec5"


def git_source(path):
    return subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}",
                                    "show", f"{BASE}:{path}"], cwd=ROOT)


class OriginalCritic:
    def __init__(self):
        self.sources = {}
        self.hashes = {}
        for name in ("graph.py", "validator.py", "fallback.py", "prompts/root_cause.txt", "prompts/patch_proposer.txt"):
            source = git_source(f"services/critic/{name}")
            self.sources[name] = source
            self.hashes[name] = hashlib.sha256(source).hexdigest()
            if name.startswith("prompts/"):
                # The original graph opens relative prompt paths. Refuse drift.
                current = (ROOT / "services/critic" / name).read_bytes().replace(b"\r\n", b"\n")
                if current != source.replace(b"\r\n", b"\n"):
                    raise RuntimeError("Original prompt differs from on-disk prompt")
        modules = {}
        for short in ("validator", "fallback", "graph"):
            module_name = f"services.critic._round2_phase1_{short}"
            module = types.ModuleType(module_name)
            module.__file__ = str(ROOT / "services/critic" / f"{short}.py")
            sys.modules[module_name] = module
            original_import = builtins.__import__

            def isolated_import(name, globals=None, locals=None, fromlist=(), level=0, *, lookup=modules, importer=original_import):
                if name in lookup:
                    return lookup[name]
                return importer(name, globals, locals, fromlist, level)

            module.__dict__["__builtins__"] = {**vars(builtins), "__import__": isolated_import}
            exec(compile(self.sources[f"{short}.py"], module.__file__, "exec"), module.__dict__)
            modules[f"services.critic.{short}"] = module
        self.graph = modules["services.critic.graph"]
        self.graph._MAX_RETRIES = 2  # original default; eliminate inherited environment changes
        self.original_validator = self.graph.validator_node
        self.original_fallback = self.graph.make_fallback_node

    def run(self, alert, store, provider):
        attempts = []
        used_fallback = []

        def observed_validator(state):
            result = self.original_validator(state)
            attempts.append({"passed": result["validation_passed"],
                             "reason": result["rejection_reason"],
                             "raw_proposal": state.get("patch_proposal")})
            return result

        def observed_fallback_factory():
            original = self.original_fallback()

            def observed(state):
                used_fallback.append(True)
                return original(state)
            return observed

        self.graph.validator_node = observed_validator
        self.graph.make_fallback_node = observed_fallback_factory
        try:
            proposal = self.graph.run_critic(alert, store, llm_factory=lambda **_: provider)
            return proposal, bool(used_fallback), attempts
        finally:
            self.graph.validator_node = self.original_validator
            self.graph.make_fallback_node = self.original_fallback
