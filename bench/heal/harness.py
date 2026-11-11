"""Healing harness: apply a config diff, re-run the NexusBench agent, score with the checkers.

A run is one (patch, base config, environment fault, task, provider, seed). Its
id is a pure function of those six values and includes the patch hash, so:

* a run id never names two different experiments. On resume, a stored record
  with the same id but a different intended config hash raises ``RunIdCollision``;
* re-running is idempotent: completed run ids are skipped, and identical runs
  requested by several failures (e.g. the no-patch regression set) execute once;
* after every run the hash of the config the agent actually used (prompt string
  sent, step budget enforced, tool list rendered) must equal the intended hash,
  or the run is not recorded (``ConfigMismatch``).

Records go to ``results/heal_runs.jsonl`` (append-only, one JSON per line).
The LLM response cache and the cost ledger are local state under
``bench/heal/_state/`` (untracked, DECISIONS D48). The phase spend cap is checked
before every paid call against the worst case, over all providers.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import nexus_agent as nexus

from bench.agent import AGENT_NAME, SpanCollector
from bench.generate import MODELS
from bench.heal.agent import ConfiguredAgent
from bench.heal.config import (ConfigPatch, apply_patch, base_tag, config_hash,
                               faulted_config)
from bench.heal.sets import assert_dev, dev_splits
from bench.labeler import label_run
from bench.llm import BudgetExceeded, CostLedger, LLMClient, ResponseCache, load_env
from bench.tasks import COMPATIBLE, build_tasks
from bench.tools import Toolbox
from bench.world import build_world

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
STATE_DIR = os.path.join(os.path.dirname(__file__), "_state")
RUNS_PATH = os.path.join(REPO, "results", "heal_runs.jsonl")
# v2 (amendment A1): records also store each tool output (truncated), which the H6 judges
# read. Run ids, config hashes and scoring are unchanged from v1.
HARNESS_VERSION = "heal-harness-v2"
TOOL_OUTPUT_CHARS = 2000
PHASE4_CAP_USD = 1.50        # preparation (baselines): ledger cost_ledger.jsonl, closed at $0.247
REST_CAP_USD = 3.00          # rest of Phase 4 (critic arms, confirmations, H6), user 2026-11-11
REST_LEDGER = "cost_ledger_rest.jsonl"
MAX_ATTEMPTS = 3  # provider errors (stop_reason llm_error) are retried, then recorded as failed

RULE_FLAG = {"HALLUCINATION": "hallucination", "CONTEXT_BLEED": "bleed", "PLAN_DRIFT": "drift",
             "TOOL_MISFIRE": "misfire", "LOOP_DETECTED": "loop"}


class RunIdCollision(RuntimeError):
    pass


class ConfigMismatch(RuntimeError):
    pass


@dataclass(frozen=True)
class RunSpec:
    patch: ConfigPatch
    base_fault: str     # decides the deployed config the patch is applied to
    env_fault: str      # the fault injected in the tool backend for this run ("NONE" = clean)
    task_id: str
    provider: str
    seed: int

    @property
    def run_id(self) -> str:
        return (f"h4-{self.patch.patch_hash[:16]}-{base_tag(self.base_fault)}-{self.env_fault}"
                f"-{self.task_id}-{self.provider}-s{self.seed}")

    @property
    def trace_id(self) -> str:
        return "hl-" + hashlib.sha1(self.run_id.encode()).hexdigest()[:16]

    def intended_config(self) -> dict[str, Any]:
        return apply_patch(faulted_config(self.base_fault), self.patch)

    def intended_hash(self) -> str:
        return config_hash(self.intended_config())

    def identity(self) -> tuple:
        """What the experiment is: the config actually run and where it runs."""
        return (self.patch.patch_hash, self.intended_hash(), self.env_fault, self.task_id,
                self.provider, self.seed)


class PhaseLedger(CostLedger):
    """Cost ledger with one cap over every provider (Phase 4 preparation: $1.50)."""

    def __init__(self, path: str, cap_usd: float) -> None:
        super().__init__(path)
        self.cap_usd = cap_usd

    def total(self) -> float:
        return sum(r["cost_usd"] for r in self.rows)

    def check(self, provider: str, model: str, worst_case_usd: float) -> None:
        if provider == "ollama":
            return
        if self.total() + worst_case_usd > self.cap_usd:
            raise BudgetExceeded(f"phase 4 cap: spent ${self.total():.4f}, next call could cost "
                                 f"${worst_case_usd:.4f}, cap ${self.cap_usd:.2f}")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=REPO,
                                       text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


class RunStore:
    """Append-only JSONL of completed runs, indexed by run id."""

    def __init__(self, path: str) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.by_id: dict[str, dict[str, Any]] = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        rec = json.loads(line)
                        if rec["run_id"] in self.by_id:
                            raise RunIdCollision(f"run id recorded twice: {rec['run_id']}")
                        self.by_id[rec["run_id"]] = rec

    def check(self, spec: RunSpec, intended_hash: str) -> bool:
        """True if ``spec`` is already done; raises if its id was used for another config."""
        rec = self.by_id.get(spec.run_id)
        if rec is None:
            return False
        if rec["intended_config_hash"] != intended_hash or rec["patch_hash"] != spec.patch.patch_hash:
            raise RunIdCollision(f"{spec.run_id} already names a run with another config")
        return True

    def add(self, rec: dict[str, Any]) -> None:
        with self._lock:
            if rec["run_id"] in self.by_id:
                raise RunIdCollision(f"run id reused: {rec['run_id']}")
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(rec, sort_keys=True) + "\n")
            self.by_id[rec["run_id"]] = rec


class Harness:
    def __init__(self, *, runs_path: str = RUNS_PATH, state_dir: str = STATE_DIR,
                 cap_usd: float = REST_CAP_USD, ledger_file: str = REST_LEDGER, workers: dict[str, int] | None = None,
                 clients: dict[str, Any] | None = None, env_file: str | None = None) -> None:
        load_env(env_file or os.environ.get("NEXUS_ENV_FILE", os.path.join(REPO, ".env")))
        self.world = build_world()
        self.tasks = {t.task_id: t for t in build_tasks(self.world)}
        self.splits = dev_splits()
        self.store = RunStore(runs_path)
        self.ledger = PhaseLedger(os.path.join(state_dir, ledger_file), cap_usd)
        self.cache = ResponseCache(os.path.join(state_dir, "llm_cache.jsonl"))
        self._clients = clients or {}
        self.workers = workers or {"deepseek": 8, "ollama": 2}
        self.commit = _git_commit()
        self._stop = threading.Event()
        nexus.shutdown()
        client = nexus.init(agent_name=AGENT_NAME, async_export=False,
                            environment="nexusbench-heal")
        self.collector = SpanCollector()
        client._exporter = self.collector

    def client(self, provider: str):
        key_var = {"deepseek": "DEEPSEEK_API_KEY", "gemini": "GEMINI_API_KEY"}.get(provider)
        if provider not in self._clients and key_var and not os.environ.get(key_var):
            # Fail fast: a missing key would otherwise be recorded as run_error records.
            raise RuntimeError(f"{key_var} is not set (pass --env-file); no run recorded")
        if provider not in self._clients:
            self._clients[provider] = LLMClient(provider, MODELS[provider], ledger=self.ledger,
                                                cache=self.cache)
        return self._clients[provider]

    # -- one run ------------------------------------------------------------
    def execute(self, spec: RunSpec) -> dict[str, Any]:
        task = self.tasks[spec.task_id]
        assert_dev([spec.task_id], self.splits)
        if spec.env_fault not in COMPATIBLE[task.family]:
            raise ValueError(f"{spec.env_fault} is not injectable for {task.family} tasks")
        intended = spec.intended_config()
        intended_hash = config_hash(intended)
        t0 = time.perf_counter()
        attempts = 0
        while True:
            attempts += 1
            tb = Toolbox(self.world, fault=spec.env_fault, session_id=task.session_id or "s-anon",
                         user_id=task.user_id or "u-anon", target_company=task.target_company)
            agent = ConfiguredAgent(self.client(spec.provider), seed=spec.seed,
                                    sample_tag=f"heal-s{spec.seed}")
            res = agent.run(task, tb, spec.trace_id, config=intended)
            self.collector.pop(spec.trace_id)
            if res.stop_reason != "llm_error" or attempts >= MAX_ATTEMPTS:
                break
        applied_hash = agent.effective_config_hash()
        if applied_hash != intended_hash:
            raise ConfigMismatch(f"{spec.run_id}: applied {applied_hash[:12]} != intended "
                                 f"{intended_hash[:12]}")
        lab = label_run(task, spec.env_fault, res, self.world)
        flags = lab.as_dict()
        return {
            "run_id": spec.run_id, "trace_id": spec.trace_id,
            "patch_hash": spec.patch.patch_hash, "patch_source": spec.patch.source,
            "base": base_tag(spec.base_fault),
            "env_fault": spec.env_fault, "task_id": spec.task_id, "family": task.family,
            "provider": spec.provider, "model": MODELS[spec.provider], "seed": spec.seed,
            "intended_config_hash": intended_hash, "applied_config_hash": applied_hash,
            "status": "ok" if res.stop_reason != "llm_error" else "run_error",
            "attempts": attempts,
            **flags,
            "env_rule_fired": bool(flags.get(RULE_FLAG.get(spec.env_fault, ""), False)),
            "stop_reason": res.stop_reason, "n_steps": len(res.steps),
            "steps": [{"tool": s.tool, "args": s.args, "error": s.error,
                       "output": None if s.output is None else s.output[:TOOL_OUTPUT_CHARS]}
                      for s in res.steps],
            "final_answer": (res.final_answer or "")[:300],
            "llm_calls": res.llm_calls, "invalid_json": res.invalid_json,
            "cost_usd": round(res.cost_usd, 8), "wall_s": round(time.perf_counter() - t0, 3),
            "harness_version": HARNESS_VERSION, "git_commit": self.commit,
            "ts": round(time.time(), 3),
        }

    # -- many runs ----------------------------------------------------------
    def run_all(self, specs: Iterable[RunSpec], *, progress: bool = True) -> dict[str, int]:
        unique: dict[str, RunSpec] = {}
        for s in specs:
            prev = unique.get(s.run_id)
            # Specs from different failures may describe the same experiment (e.g. two
            # non-HALLUCINATION faults share the clean base); identity is what must agree.
            if prev is not None and prev.identity() != s.identity():
                raise RunIdCollision(f"two different specs share {s.run_id}")
            unique[s.run_id] = s
        assert_dev({s.task_id for s in unique.values()}, self.splits)
        pending = [s for s in unique.values() if not self.store.check(s, s.intended_hash())]
        stats = {"requested": len(unique), "already_done": len(unique) - len(pending),
                 "ran": 0, "run_error": 0}
        if progress:
            print(f"[harness] {len(unique)} runs, {stats['already_done']} done, "
                  f"{len(pending)} to run", flush=True)
        lock = threading.Lock()
        errors: list[BaseException] = []

        def work(spec: RunSpec) -> None:
            if self._stop.is_set():
                return
            try:
                rec = self.execute(spec)
            except BudgetExceeded as exc:
                self._stop.set()
                errors.append(exc)
                return
            except Exception as exc:  # ConfigMismatch etc. stop everything
                self._stop.set()
                errors.append(exc)
                return
            self.store.add(rec)
            with lock:
                stats["ran"] += 1
                stats["run_error"] += rec["status"] != "ok"
                if progress and (stats["ran"] % 25 == 0 or stats["ran"] == len(pending)):
                    print(f"[harness] {stats['ran']}/{len(pending)} "
                          f"spend ${self.ledger.total():.4f}", flush=True)

        by_provider: dict[str, list[RunSpec]] = {}
        for s in pending:
            by_provider.setdefault(s.provider, []).append(s)
        pools = [ThreadPoolExecutor(max_workers=self.workers.get(p, 2)) for p in by_provider]
        try:
            futures = [pool.submit(work, s) for pool, (p, ss) in zip(pools, by_provider.items())
                       for s in ss]
            for f in futures:
                f.result()
        finally:
            for pool in pools:
                pool.shutdown(wait=True)
        if errors:
            raise errors[0]
        return stats

    def records(self) -> dict[str, dict[str, Any]]:
        return self.store.by_id
