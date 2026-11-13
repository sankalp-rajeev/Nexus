"""Critic PIPELINE SMOKE TEST (not an evaluation of diagnosis quality).

Runs the critic graph on 20 synthetic traces (4 per failure type) with the
deterministic mock LLM selected explicitly (NEXUS_LLM=mock), and records for
each proposal whether it came from the LLM path or the generic fallback
template. It checks that the pipeline produces schema-valid proposals end to
end; it says nothing about whether a real LLM diagnoses failures correctly
(that is experiment C1-C5 in the improvement plan).

    python tests/fixtures/run_critic_eval.py

Writes docs/history/critic_smoke_test_report.md (legacy, pre-rework) and results/critic_smoke_mock.json.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from unittest.mock import MagicMock

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "sdk"))

os.environ.setdefault("NEXUS_LLM", "mock")

from nexus_agent.models import Alert, FailureType  # noqa: E402
from services.common import llm_config  # noqa: E402
from services.common.results import provenance, report_header, write_result  # noqa: E402
from services.critic.fallback import _FALLBACKS  # noqa: E402
from services.critic.graph import run_critic  # noqa: E402

OUT_PATH = os.path.join(_REPO, "docs", "history", "critic_smoke_test_report.md")
RESULT_FILE = "critic_smoke_mock.json"


def _source(ft: FailureType, proposal) -> str:
    tpl = _FALLBACKS.get(ft)
    if tpl and proposal.explanation == tpl["explanation"]:
        return "fallback"
    return "llm"

_FIX = os.path.join(_REPO, "tests", "fixtures", "generate_synthetic_traces.py")
spec = importlib.util.spec_from_file_location("synth", _FIX)
synth = importlib.util.module_from_spec(spec)
spec.loader.exec_module(synth)

FAILURE_TYPES = [
    FailureType.HALLUCINATION,
    FailureType.CONTEXT_BLEED,
    FailureType.PLAN_DRIFT,
    FailureType.TOOL_MISFIRE,
    FailureType.LOOP_DETECTED,
]
SAMPLES_PER_TYPE = 4  # 5 types x 4 = 20 total


def _mock_db_with_trace(trace):
    mock_db = MagicMock()
    mock_db.load_trace.return_value = trace
    mock_db.write_patch.return_value = None
    return mock_db


def main():
    traces, labels = synth.load_dataset()
    by_type: dict[FailureType, list] = {ft: [] for ft in FAILURE_TYPES}
    for trace, label in zip(traces, labels):
        if label in by_type and len(by_type[label]) < SAMPLES_PER_TYPE:
            by_type[label].append(trace)

    results = []
    for ft in FAILURE_TYPES:
        for trace in by_type[ft]:
            alert = Alert(trace_id=trace.trace_id, agent_name=trace.agent_name, failure_type=ft)
            db = _mock_db_with_trace(trace)
            proposal = run_critic(alert, db)
            if proposal is None:
                results.append({"trace_id": trace.trace_id, "failure_type": ft.value,
                                 "error": "no proposal", "source": "none"})
                continue
            results.append({
                "source": _source(ft, proposal),
                "trace_id": trace.trace_id,
                "failure_type": ft.value,
                "patch_type": proposal.patch_type.value,
                "target_component": proposal.target_component,
                "confidence": proposal.confidence,
                "explanation_excerpt": proposal.explanation[:120] + ("..." if len(proposal.explanation) > 120 else ""),
                "patch_content_excerpt": proposal.patch_content[:120] + ("..." if len(proposal.patch_content) > 120 else ""),
            })

    desc = llm_config.describe()
    n = len(results)
    n_fallback = sum(1 for r in results if r["source"] == "fallback")
    n_llm = sum(1 for r in results if r["source"] == "llm")
    n_none = sum(1 for r in results if r["source"] == "none")
    summary = (f"SMOKE TEST (mock LLM): {n - n_none}/{n} traces produced a schema-valid "
               f"proposal; {n_fallback}/{n} were the generic fallback template")
    write_result(
        "critic-smoke", RESULT_FILE,
        {"n": n, "llm": n_llm, "fallback": n_fallback, "no_proposal": n_none,
         "proposals": results},
        provenance_info=provenance(provider=desc["provider"], model=desc["model"],
                                   mock=desc["mock"] == "true", seed=None),
        summary=summary,
    )
    _write_report(results, desc, n_llm, n_fallback, n_none)
    print(summary)
    print(f"Report: {OUT_PATH}")
    return 0 if n_none == 0 else 1


def _write_report(results, desc, n_llm, n_fallback, n_none):
    n = len(results)
    lines = [
        "# Nexus Critic - Pipeline Smoke Test (mock LLM)",
        "",
        *report_header(provider=desc["provider"], model=desc["model"],
                       mock=desc["mock"] == "true",
                       generator="python tests/fixtures/run_critic_eval.py",
                       result_file=f"results/{RESULT_FILE}"),
        "",
        "> **This is not an evaluation of the critic.** It runs the LangGraph pipeline with a "
        "deterministic mock LLM to check that every failure type yields a schema-valid "
        "`PatchProposal`. It provides no evidence about real diagnosis or patch quality. "
        "Real-model experiments (C1-C5) are tracked in [RESULTS.md](../RESULTS.md).",
        "",
        f"- Traces: {n} synthetic (4 per failure type)",
        f"- Schema-valid proposal produced: {n - n_none}/{n}",
        f"- Proposal source: LLM path {n_llm}/{n}, generic fallback template {n_fallback}/{n}",
        "",
        "## Proposals",
        "",
        "| # | Trace ID | Failure Type | Patch Type | Confidence | Source |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        lines.append(
            f"| {i} | {r['trace_id'][-12:]} | {r['failure_type']} | "
            f"{r.get('patch_type', 'ERROR')} | {r.get('confidence', 'N/A')} | {r['source']} |"
        )
    lines.append("")
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
