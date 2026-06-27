"""Phase 4 manual evaluation: run the critic on 20 synthetic traces and produce
a human-reviewable report.

Selects 4 traces per failure type (from the synthetic dataset), runs the critic
(mock LLM by default), and writes docs/critic_eval_report.md.

    python tests/fixtures/run_critic_eval.py
"""

from __future__ import annotations

import importlib.util
import os
import sys
from unittest.mock import MagicMock

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "sdk"))

from nexus_agent.models import Alert, FailureType
from services.critic.graph import run_critic

OUT_PATH = os.path.join(_REPO, "docs", "critic_eval_report.md")

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
                                 "error": "no proposal", "actionable": False})
                continue
            # Automated actionability check: patch_content >= 50 chars and explanation >= 50 chars.
            actionable = (len(proposal.patch_content) >= 50 and len(proposal.explanation) >= 50
                          and proposal.confidence in ("HIGH", "MEDIUM", "LOW"))
            results.append({
                "trace_id": trace.trace_id,
                "failure_type": ft.value,
                "patch_type": proposal.patch_type.value,
                "target_component": proposal.target_component,
                "confidence": proposal.confidence,
                "explanation_excerpt": proposal.explanation[:120] + ("..." if len(proposal.explanation) > 120 else ""),
                "patch_content_excerpt": proposal.patch_content[:120] + ("..." if len(proposal.patch_content) > 120 else ""),
                "actionable": actionable,
            })

    n_actionable = sum(1 for r in results if r.get("actionable"))
    _write_report(results, n_actionable)
    print(f"Evaluated {len(results)} proposals: {n_actionable}/{len(results)} actionable")
    print(f"Gate: >=15 actionable -> {'PASS' if n_actionable >= 15 else 'FAIL'}")
    print(f"Report: {OUT_PATH}")
    return 0 if n_actionable >= 15 else 1


def _write_report(results, n_actionable):
    lines = [
        "# Nexus Critic Agent - Manual Evaluation Report",
        "",
        f"- Total proposals evaluated: {len(results)}",
        f"- Actionable (patch_content >= 50 chars, explanation >= 50 chars): **{n_actionable}/{len(results)}**",
        f"- Gate: >= 15 actionable -> {'PASS' if n_actionable >= 15 else 'FAIL'}",
        "",
        "## Proposals",
        "",
        "| # | Trace ID | Failure Type | Patch Type | Confidence | Actionable |",
        "|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        lines.append(
            f"| {i} | {r['trace_id'][-12:]} | {r['failure_type']} | "
            f"{r.get('patch_type','ERROR')} | {r.get('confidence','N/A')} | "
            f"{'YES' if r.get('actionable') else 'NO'} |"
        )
    lines += ["", "## Sample Explanations", ""]
    for r in results:
        if r.get("actionable"):
            lines += [
                f"### {r['failure_type']} - {r['trace_id'][-12:]}",
                f"**Target:** `{r.get('target_component', 'N/A')}`",
                f"**Explanation:** {r.get('explanation_excerpt', 'N/A')}",
                f"**Patch:** `{r.get('patch_content_excerpt', 'N/A')}`",
                "",
            ]
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))


if __name__ == "__main__":
    raise SystemExit(main())
