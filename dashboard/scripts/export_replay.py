"""Build dashboard/public/replay.json (schema v2) from recorded DEV evidence only.

What goes in, and from where:

* DEV traces and DEV labels: only through ``services/critic/dev_adapter.py``, which discards TEST
  payloads before they are decoded. The span text shown is the detector view (what the detectors and
  the critic were given), not the raw benchmark record.
* Detector verdicts: ``results/phase2_dev_predictions.json`` (the scored Phase 2 detectors; the live
  classifier reproduces them 359/359, see ``results/phase6/live_detectors_equivalence_with_final.json``).
  Evidence spans come from the same ``services/critic/detector_adapter.py`` the critic used.
* Heals: the Phase 5 DEV overnight runs (read only, outside this repository). Their record files hold
  the critic's real proposal, the gate checks and the decision. Only selected fields of the selected
  heals are copied; no raw record, call log or ledger is copied.
* Headline numbers: the Phase 4 finding comes from ``results/phase4/headline_transcribed.json``
  (transcribed from the committed ``reports/phase4/test_scoring.md``, each number with its report
  line); the rest are parsed from committed ``RESULTS.md`` rows and ``results/phase5``/
  ``results/phase6`` JSON. No NexusBench ``*_test*`` result file and nothing under ``reports/phase4/test/`` is opened.
* TRAIL: only the approved committed ``trail_a_scored.json`` / ``trail_b_scored.json``
  aggregates and development summary. Their filenames pass the unchanged shared TEST guard. No TRAIL trace,
  prompt, output or annotation description is read or exported.

No benchmark execution, no model loading, no provider calls, no network.

Run ``python dashboard/scripts/export_replay.py`` (from any directory, with the project's Python).
``--check`` rebuilds in memory and fails if the committed replay.json is stale.
The Phase 5 run directory is not part of the repository; pass ``--phase5-runs`` or set
``NEXUS_PHASE5_RUNS`` when it lives elsewhere.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _path in (str(ROOT), str(ROOT / "sdk")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from scripts.trail_publication import A_RESULT, B_RESULT, DEV_SUMMARY, build_external_trail

DEFAULT_PHASE5_RUNS = Path(os.environ.get("NEXUS_PHASE5_RUNS", r"C:\Umich\Projects\nexus-phase5\data\phase5\runs"))
DESTINATION = ROOT / "dashboard/public/replay.json"
SCHEMA_VERSION = 2

PREDICTIONS = "results/phase2_dev_predictions.json"
LABELS = "data/nexusbench/labels.csv"
TRACES = "data/nexusbench/traces.jsonl"
RESULTS_MD = "RESULTS.md"
HEAL_COST = "results/phase5/heal_latency_cost.json"
GEMINI_SIDE = "results/phase5/gemini_side.json"
HEADLINE_P5 = "results/phase5/headline.json"
EQUIVALENCE = "results/phase6/live_detectors_equivalence_with_final.json"
BEFORE_AFTER = "results/phase6/live_detectors_before_after.json"
L4_RERUN = "results/phase6/l4_rerun.json"
HEADLINE_P4 = "results/phase4/headline_transcribed.json"
PREREG_P4 = "reports/phase4/preregistration.md"
CRITIC_C1 = "results/critic_dev/c1.json"
DATASHEET = "bench/DATASHEET.md"
# Everything whose content shapes replay.json and lives in this repository. Each is recorded by git
# blob id (``git hash-object`` of the working file, which is stable across CRLF/LF checkouts).
SOURCES = (
    RESULTS_MD, PREDICTIONS, HEAL_COST, GEMINI_SIDE, HEADLINE_P5, EQUIVALENCE, BEFORE_AFTER, L4_RERUN,
    HEADLINE_P4, PREREG_P4, CRITIC_C1, DATASHEET, LABELS, TRACES,
    "bench/agent.py", "bench/detector_view.py",
    "services/critic/dev_adapter.py", "services/critic/detector_adapter.py",
    "services/healer/gate.py",
    A_RESULT, B_RESULT, DEV_SUMMARY, "reports/external/trail_prereg_a3.md",
)

TRACE_CLASSES = ("NORMAL", "HALLUCINATION", "TOOL_MISFIRE", "CONTEXT_BLEED", "PLAN_DRIFT", "LOOP_DETECTED")
TRACES_PER_CLASS = 2
TEXT_LIMIT = 1500
EVIDENCE_LIMIT = 600
DATA_STATEMENT = ("DEV data; TEST numbers shown only as already reported in RESULTS.md; "
                  "TRAIL numbers are aggregate-only committed external results")
TRAIL_NOTICE = "TRAIL is aggregate evidence only: no external trace, prompt, output or annotation is shipped."
UNPUBLISHABLE_MARKER = re.compile(r"placeholder|mock", re.IGNORECASE)

# Heal selection: for each rule, in this order, the first heal (lowest id) of its run that matches.
# The rules describe outcomes, never quality; nothing is ranked or hand-picked.
HEAL_RULES = (
    ("promoted_hallucination", "main", "Promoted, HALLUCINATION",
     lambda r: r.get("gate_decision") == "promoted" and r.get("failure_class") == "HALLUCINATION"),
    ("promoted_loop", "main", "Promoted, LOOP_DETECTED",
     lambda r: r.get("gate_decision") == "promoted" and r.get("failure_class") == "LOOP_DETECTED"),
    ("promoted_tool_misfire", "main", "Promoted, TOOL_MISFIRE",
     lambda r: r.get("gate_decision") == "promoted" and r.get("failure_class") == "TOOL_MISFIRE"),
    ("blocked_at_heldout", "main", "Fixed its own task, blocked at the held-out check",
     lambda r: (r.get("gate") or {}).get("check1_own_task") is True and (r.get("gate") or {}).get("check2_heldout") is False),
    ("blocked_by_regression", "main", "Fixed its own task, blocked by the regression check (broke a passing task)",
     lambda r: (r.get("gate") or {}).get("check1_own_task") is True and bool((r.get("gate") or {}).get("regression_breaks"))),
    ("rejected_at_repair_check", "gemini", "Rejected at the repair check (separate Gemini critic side row)",
     lambda r: (r.get("gate") or {}).get("check1_own_task") is False),
    ("no_patch_tool_misfire", "main", "No usable patch, TOOL_MISFIRE (rejected before the gate)",
     lambda r: r.get("proposal_status") == "no_patch" and r.get("failure_class") == "TOOL_MISFIRE"),
    ("no_patch_context_bleed", "main", "No usable patch, CONTEXT_BLEED (rejected before the gate)",
     lambda r: r.get("proposal_status") == "no_patch" and r.get("failure_class") == "CONTEXT_BLEED"),
    ("detector_missed", "main", "Detector predicted NORMAL on a real fault (no critic call)",
     lambda r: r.get("failure_class") == "NORMAL"),
)
RUN_LABELS = {
    "main": "100-heal overnight DEV run (DeepSeek critic, concurrency 2)",
    "gemini": "20-heal Gemini critic side row (separate from the headline)",
}
RUN_SUBDIRS = {"main": "", "gemini": "gemini_side"}


# ── guard ────────────────────────────────────────────────────────────────────────────────────────
def assert_publishable(replay: dict) -> None:
    """Fail closed on placeholder/mock markers anywhere, including keys and provenance."""
    markers: list[str] = []

    def visit(value, path: str) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                child = f"{path}.{key}"
                if UNPUBLISHABLE_MARKER.search(str(key)):
                    markers.append(child)
                if key in {"illustrative", "excerpt_only"} and item is True:
                    markers.append(child)
                visit(item, child)
        elif isinstance(value, list):
            for index, item in enumerate(value):
                visit(item, f"{path}[{index}]")
        elif isinstance(value, str) and UNPUBLISHABLE_MARKER.search(value):
            markers.append(path)

    visit(replay, "$")
    if markers:
        unique = list(dict.fromkeys(markers))
        locations = ", ".join(unique[:8])
        if len(unique) > 8:
            locations += f", and {len(unique) - 8} more locations"
        raise ValueError(
            "Replay publication blocked: placeholder/mock or illustrative markers remain at "
            f"{locations}. Replace them with recorded, evaluated DEV artifacts before building."
        )


# ── helpers ──────────────────────────────────────────────────────────────────────────────────────
def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "-c", f"safe.directory={ROOT.as_posix()}", *args], cwd=ROOT, text=True,
    ).strip()


def repository_url() -> str:
    """https URL of the origin repository (links to the exact commit are built from it)."""
    remote = git("remote", "get-url", "origin")
    match = re.search(r"[:/]([\w.-]+/[\w.-]+?)(?:\.git)?$", remote)
    if not match:
        raise ValueError("Cannot derive the repository URL from the origin remote")
    return f"https://github.com/{match.group(1)}"


def blob_id(path: str) -> str:
    """Git blob id of the working-tree file (filters applied), without exposing its content."""
    return git("hash-object", "--", path)


def read_json(path: str):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def clip(text: str | None, limit: int = TEXT_LIMIT) -> tuple[str | None, int | None]:
    if text is None or len(text) <= limit:
        return text, None
    return text[:limit], len(text)


def sha256_bytes(*chunks: bytes) -> str:
    digest = hashlib.sha256()
    for chunk in chunks:
        digest.update(chunk)
    return digest.hexdigest()


# ── DEV traces and detector verdicts ─────────────────────────────────────────────────────────────
def load_dev_context() -> dict:
    from services.critic.dev_adapter import dev_labels

    labels = {row["trace_id"]: row for row in dev_labels(ROOT / LABELS)}
    predictions_doc = read_json(PREDICTIONS)
    predictions = predictions_doc["predictions"]
    if not set(predictions) <= set(labels):
        raise ValueError("Prediction source contains non-DEV trace IDs")
    return {"labels": labels, "predictions": predictions, "thresholds": predictions_doc["thresholds"]}


def rule_selected_trace_ids(predictions: dict) -> list[str]:
    selected: list[str] = []
    for label in TRACE_CLASSES:
        selected += sorted(tid for tid, p in predictions.items() if p["pred"] == label)[:TRACES_PER_CLASS]
    return selected


def _detector_block(trace_id: str, view, ctx: dict) -> dict:
    from services.critic.detector_adapter import from_detector

    prediction = ctx["predictions"][trace_id]
    label = ctx["labels"][trace_id]["label"]
    pred = prediction["pred"]
    evidence = from_detector(prediction, view)
    block = {
        "verdict": pred,
        "dev_label": label,
        # OTHER_FAILURE is outside the detectors' five classes: reported, not scored.
        "agrees_with_dev_label": None if label == "OTHER_FAILURE" else pred == label,
        "nli": {"ran": bool(prediction.get("nli_ran")), "score": prediction.get("nli_score"),
                "flag": bool(prediction.get("nli_flag"))},
        "entity_rule": prediction.get("entity_rule"),
        "threshold": ctx["thresholds"].get(pred),
        "evidence": None,
    }
    if evidence is not None:
        excerpt, total = clip(evidence.supporting_text, EVIDENCE_LIMIT)
        block["evidence"] = {"span_id": evidence.span_id, "step": evidence.step, "text": excerpt}
        if total:
            block["evidence"]["text_chars"] = total
    return block


def _span_block(span: dict) -> dict:
    out = {key: span.get(key) for key in ("span_id", "parent_span_id", "span_type", "agent_name",
                                           "duration_ms", "error_type", "error_message", "client_timestamp")
           if span.get(key) is not None}
    for key in ("input", "output"):
        text, total = clip(span.get(key))
        if text is not None:
            out[key] = text
        if total:
            out[f"{key}_chars"] = total
    metadata = {k: v for k, v in (span.get("metadata") or {}).items()}
    if metadata:
        out["metadata"] = metadata
    return out


def build_trace_blocks(ids: list[str], ctx: dict) -> list[dict]:
    from bench.detector_view import detector_view, view_id_for
    from services.critic.dev_adapter import dev_traces
    from services.critic.detector_adapter import critic_view

    wanted = sorted(set(ids))
    missing = [tid for tid in wanted if tid not in ctx["labels"] or tid not in ctx["predictions"]]
    if missing:
        raise ValueError(f"Not DEV traces with a detector verdict: {missing}")
    traces = dev_traces(ROOT / TRACES, set(wanted))
    blocks = []
    for tid in wanted:
        trace = traces[tid]
        label = ctx["labels"][tid]
        view = detector_view(trace.model_dump(mode="json"))
        shown = critic_view(view)
        root_input, root_total = clip(trace.root_input)
        final_output, final_total = clip(trace.final_output)
        block = {
            "trace_id": tid, "view_id": view_id_for(tid), "agent_name": trace.agent_name,
            "task_id": label["task_id"], "family": label["family"],
            "started_at": trace.started_at.isoformat() if trace.started_at else None,
            "root_input": root_input, "final_output": final_output,
            "detector": _detector_block(tid, view, ctx),
            "spans": [_span_block(s.model_dump(mode="json")) for s in shown.spans],
        }
        if root_total:
            block["root_input_chars"] = root_total
        if final_total:
            block["final_output_chars"] = final_total
        blocks.append(block)
    return blocks


# ── headline numbers (parsed, never typed) ───────────────────────────────────────────────────────
def results_md_rows() -> dict[str, dict]:
    rows = {}
    for line in (ROOT / RESULTS_MD).read_text(encoding="utf-8").splitlines():
        if not line.startswith("| ") or line.startswith("| ID") or line.startswith("|---"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        if len(cells) >= 7:
            rows[cells[0]] = {"id": cells[0], "result": cells[1], "provider_model": cells[2], "date": cells[4],
                              "commit": cells[5].strip("`")}
    return rows


def _search(pattern: str, text: str, group: int = 1) -> str:
    match = re.search(pattern, text)
    if not match:
        raise ValueError(f"RESULTS.md row no longer matches /{pattern}/: {text[:120]}")
    return match.group(group)


def build_headline() -> dict:
    rows = results_md_rows()
    cost = read_json(HEAL_COST)
    p5 = read_json(HEADLINE_P5)
    equivalence = read_json(EQUIVALENCE)["equivalence"]
    before_after = read_json(BEFORE_AFTER)
    l4 = read_json(L4_RERUN)

    def row_source(row_id: str) -> dict:
        row = rows[row_id]
        return {"path": RESULTS_MD, "locator": f"row {row_id} ({row['date']}, commit {row['commit']})"}

    def item(item_id, label, value, scope, source_path, locator, note=None):
        entry = {"id": item_id, "label": label, "value": value, "scope": scope,
                 "source": {"path": source_path, "locator": locator}}
        if note:
            entry["note"] = note
        return entry

    d_dev, d1 = rows["D-dev"]["result"], rows["D1"]["result"]
    a2, a3 = rows["A2 critic v1_structured"]["result"], rows["A3 test v1_structured"]["result"]
    decisions = cost["gate_decisions"]["by_detector_failure_class"]
    promoted = sum(v.get("promoted", 0) for v in decisions.values())
    rejected = sum(v.get("rejected", 0) for v in decisions.values())
    all_heals = cost["L1"]["all_heals"]["total_s"]
    ingestion_stable = p5["L3_ingestion_max_stable_lag_events_s"]
    ingestion_strict = p5["L3_ingestion_max_events_s"]
    l4_p5 = p5["L4_added_healthy_ms"]
    l4_p6 = l4["collector_healthy"]["paired_added_per_step"]

    p4 = read_json(HEADLINE_P4)
    p4_num = {n["id"]: n for n in p4["numbers"]}
    p4_commit = p4["provenance"]["git_commit"][:7]
    p4_scope = "TEST, scored once; transcribed from the committed Phase 4 report, not recomputed"

    def p4_item(item_id, label, ids, value, note=None):
        """One Phase 4 headline card. Source: the transcribed JSON; locator: report path and line."""
        cites = "; ".join(
            f"{i}: {p4_num[i]['source']['path']} line {p4_num[i]['source']['line']}" for i in ids)
        intervals = "; ".join(
            f"{p4_num[i]['k']}/{p4_num[i]['n']} Wilson 95% {p4_num[i]['wilson95'][0]:.2f}-"
            f"{p4_num[i]['wilson95'][1]:.2f}" for i in ids)
        text = f"{note + ' ' if note else ''}95% intervals: {intervals}."
        return item(item_id, label, value, p4_scope, HEADLINE_P4,
                    f"numbers[{', '.join(ids)}], from {cites} (commit {p4_commit})", text)

    def frac(i):
        return f"{p4_num[i]['k']}/{p4_num[i]['n']}"

    per_class = [r for r in p4["per_class_critic_vs_generic"]["rows"] if r["class"] != "all"]
    per_class_value = ", ".join(
        f"{r['class']} {r['promoted_per_eligible_failure']['v1_structured']['k']}/"
        f"{r['promoted_per_eligible_failure']['v1_structured']['n']} vs "
        f"{r['promoted_per_eligible_failure']['generic']['k']}/"
        f"{r['promoted_per_eligible_failure']['generic']['n']}" for r in per_class)
    pc_lines = f"{per_class[0]['source']['line']}-{per_class[-1]['source']['line']}"
    d5_text = rows["D5"]["result"]

    groups = [
        {"title": "The Phase 4 finding: the promotion gate (sealed TEST, scored once)", "items": [
            p4_item("p4_gate_promoted", "Gate promoted, per eligible failure: critic vs generic vs no patch",
                    ["gate_promoted_v1_structured", "gate_promoted_generic", "gate_promoted_no_patch"],
                    f"{frac('gate_promoted_v1_structured')} vs {frac('gate_promoted_generic')} "
                    f"vs {frac('gate_promoted_no_patch')}",
                    "51 eligible failures. The same 25 promotions are 25/48 of the scored patches in the "
                    "A3 row below."),
            p4_item("p4_other_fix_repaired", "other_fix patches: own task repaired, critic vs no patch",
                    ["other_fix_v1_repaired", "other_fix_no_patch_same_failures"],
                    f"{frac('other_fix_v1_repaired')} vs {frac('other_fix_no_patch_same_failures')}",
                    "The 36 patches that change something other than reverting the injected prompt."),
            p4_item("p4_other_fix_breaks", "other_fix patches that broke a passing task; blocked by the gate",
                    ["other_fix_h3_breaks", "other_fix_breakers_blocked_by_gate"],
                    f"{frac('other_fix_h3_breaks')} broke one; gate blocked "
                    f"{frac('other_fix_breakers_blocked_by_gate')}",
                    "'Blocked 12/12' follows from the gate definition (12 breakers, 0 gate false "
                    "promotions); the report does not print it."),
            p4_item("p4_old_rule", "The old 'same input improved' rule: promoted, and false promotions",
                    ["old_rule_promoted", "old_rule_false_promotions"],
                    f"{frac('old_rule_promoted')} promoted, {p4_num['old_rule_false_promotions']['k']} false",
                    "The 6 were promoted by the old rule and rejected by the gate. The report does not "
                    "say whether each broke a passing task."),
            p4_item("p4_fresh_seeds", "Gate-promoted patches that failed on fresh seeds",
                    ["gate_false_promotions_fresh_seeds"], frac("gate_false_promotions_fresh_seeds")),
            p4_item("p4_regression", "Regression breaks per scored patch: DEV vs TEST",
                    ["regression_breaks_dev", "regression_breaks_test"],
                    f"{frac('regression_breaks_dev')} vs {frac('regression_breaks_test')}",
                    "Both on the A2 regression set; all 12 TEST breaks are other_fix patches."),
            item("p4_per_class", "Promoted per eligible failure, critic vs generic, by class",
                 per_class_value, p4_scope, HEADLINE_P4,
                 f"per_class_critic_vs_generic, from reports/phase4/test_scoring.md lines {pc_lines} "
                 f"(commit {p4_commit})",
                 "Small cells (3 to 12 failures); the intervals are in results/phase4/headline_transcribed.json."),
        ]},
        {"title": "Detection", "items": [
            item("detect_test_precision", "Detector HALLUCINATION precision, sealed TEST (reported once)",
                 f"{_search(r'H P=([0-9.]+)', d1)} (target 0.90 missed)", "TEST, as reported in RESULTS.md",
                 RESULTS_MD, row_source("D1")["locator"],
                 "Below the pre-registered 0.90 precision target. The v1.1 relabelling sensitivity is a "
                 "separate row in RESULTS.md."),
            item("detect_test_false_alerts", "False alerts per 1,000 NORMAL traces, sealed TEST (reported once)",
                 _search(r"per 1,000 NORMAL: ([0-9.]+)", d5_text), "TEST, as reported in RESULTS.md",
                 RESULTS_MD, row_source("D5")["locator"],
                 "Primary result on the v1 labels; the v1.1 sensitivity is reported separately."),
            item("detect_dev_macro", "Detector headline macro recall",
                 _search(r"headline macro ([0-9.]+)", d_dev), "DEV", RESULTS_MD, row_source("D-dev")["locator"]),
            item("detect_test_macro", "Detector headline macro recall, sealed TEST (reported once)",
                 _search(r"headline macro recall ([0-9.]+)", d1), "TEST, as reported in RESULTS.md",
                 RESULTS_MD, row_source("D1")["locator"]),
            item("live_equivalence", "Live classifier matches the scored detectors",
                 f"{equivalence['service_match']}/{equivalence['traces']} DEV traces", "DEV", EQUIVALENCE,
                 "equivalence.service_match / equivalence.traces",
                 "Same predictions as results/phase2_dev_predictions.json, spans delivered with the final flag."),
            item("legacy_vs_detectors", "Macro recall, legacy classifier to scored detectors",
                 f"{before_after['legacy']['headline_macro_recall']:.3f} to {before_after['detectors']['headline_macro_recall']:.3f}",
                 "DEV", BEFORE_AFTER, "legacy.headline_macro_recall / detectors.headline_macro_recall"),
            item("false_alerts_normal", "False alerts on NORMAL DEV traces, legacy to scored detectors",
                 f"{before_after['legacy']['false_alerts_on_normal']} to {before_after['detectors']['false_alerts_on_normal']}",
                 "DEV", BEFORE_AFTER, "legacy.false_alerts_on_normal / detectors.false_alerts_on_normal"),
        ]},
        {"title": "Healing", "items": [
            item("heal_dev_gate", "Critic v1_structured, DEV: first-run repairs, gate promotions, false promotions",
                 f"H1 {_search(r'H1 ([0-9]+/[0-9]+)', a2)}, gate {_search(r'gate ([0-9]+),', a2)}, "
                 f"false promotions {_search(r'false promotions ([0-9]+)', a2)}", "DEV", RESULTS_MD,
                 row_source("A2 critic v1_structured")["locator"]),
            item("heal_test_gate", "Critic v1_structured, sealed TEST (reported once)",
                 f"H1 {_search(r'H1 ([0-9]+/[0-9]+)', a3)}, gate {_search(r'gate ([0-9]+),', a3)}, "
                 f"false promotions {_search(r'false promotions ([0-9]+)', a3)}", "TEST, as reported in RESULTS.md",
                 RESULTS_MD, row_source("A3 test v1_structured")["locator"],
                 "Denominator is the 48 scored patches; the Phase 4 finding above uses the 51 eligible "
                 "failures (same 25 promotions)."),
            item("overnight_decisions", "Overnight DEV run: promoted / rejected",
                 f"{promoted} / {rejected} of {promoted + rejected}", "DEV", HEAL_COST,
                 "gate_decisions.by_detector_failure_class",
                 "Descriptive counts only, not a re-estimate of the Phase 4 rates."),
        ]},
        {"title": "Speed and cost (Phase 5, one machine, one night)", "items": [
            item("time_to_heal", "Time to heal, p50 / p90",
                 f"{all_heals['p50']:.1f} s / {all_heals['p90']:.1f} s", "DEV", HEAL_COST, "L1.all_heals.total_s",
                 "100 heals at concurrency 2; the regression check dominates."),
            item("heal_cost", "Provider usage-priced cost per heal (mean)",
                 f"${cost['L2']['provider_usd']['mean']:.6f}", "DEV", HEAL_COST, "L2.provider_usd.mean",
                 "API-reported usage at published rates, not an invoice."),
            item("ingestion", "Ingestion without growing lag / passing every strict checkpoint",
                 f"{ingestion_stable:.3f} / {ingestion_strict:.3f} events/s", "DEV", HEADLINE_P5,
                 "L3_ingestion_max_stable_lag_events_s / L3_ingestion_max_events_s"),
            item("sdk_overhead_p5", "SDK overhead per step, Phase 5 (p50 / p99)",
                 f"{l4_p5['p50_ms']:.4f} ms / {l4_p5['p99_ms']:.4f} ms", "DEV", HEADLINE_P5, "L4_added_healthy_ms",
                 "Recorded-response replay, collector up."),
            item("sdk_overhead_p6", "SDK overhead per step, hardened SDK re-run (p50 / p99)",
                 f"{l4_p6['p50_ms']:.4f} ms / {l4_p6['p99_ms']:.4f} ms", "DEV", L4_RERUN,
                 "collector_healthy.paired_added_per_step"),
            item("gemini_side", "Gemini critic side row: heals completed",
                 f"{p5['gemini_completed']}/20", "DEV", HEADLINE_P5, "gemini_completed",
                 "Reported apart from the headline run."),
        ]},
    ]
    return {"groups": groups, "hero": build_hero(rows, p4_num, p4_commit, p4_scope), "story": build_story()}


def wilson95(k: int, n: int) -> list[float]:
    """Wilson 95% interval, rounded as in results/phase4/headline_transcribed.json (used only for sums of its cells)."""
    z = 1.959963984540054
    p_hat = k / n
    centre = (p_hat + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p_hat * (1 - p_hat) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def _line_of(path: str, needle: str) -> int:
    """1-based line of the first line containing ``needle``; the page links there."""
    for number, line in enumerate((ROOT / path).read_text(encoding="utf-8").splitlines(), 1):
        if needle in line:
            return number
    raise ValueError(f"{path} no longer contains {needle!r}")


def _results_row(rows: dict, row_id: str) -> dict:
    row = rows[row_id]
    return {"source": {"path": RESULTS_MD, "locator": f"row {row_id} ({row['date']}, commit {row['commit']})"},
            "cite": {"path": RESULTS_MD, "line": _line_of(RESULTS_MD, f"| {row_id} |")}}


def _p4_fraction(p4_num: dict, number_id: str, p4_commit: str) -> dict:
    number = p4_num[number_id]
    source = number["source"]
    return {"k": number["k"], "n": number["n"], "wilson95": number["wilson95"], "split": number["split"],
            "source": {"path": HEADLINE_P4,
                       "locator": f"numbers[{number_id}], from {source['path']} line {source['line']} "
                                  f"(commit {p4_commit})"},
            # Where a reader lands: the committed report row the number was transcribed from.
            "cite": {"path": source["path"], "line": source["line"]}}


def _kn(fraction: dict) -> dict:
    return {key: fraction[key] for key in ("k", "n", "wilson95")}


def build_hero(rows: dict, p4_num: dict, p4_commit: str, p4_scope: str) -> dict:
    """The landing hero's proof numbers, as numbers (k, n, value) so the page computes its words from them.

    Same sources as the cards above: the transcribed Phase 4 TEST finding and the RESULTS.md D2 row.
    """
    def p4_proof(proof_id: str, number_id: str) -> dict:
        return {"id": proof_id, "kind": "fraction", **_p4_fraction(p4_num, number_id, p4_commit), "scope": p4_scope}

    d2 = rows["D2"]["result"]
    failure_classes = [r["class"] for r in read_json(HEADLINE_P4)["per_class_critic_vs_generic"]["rows"]
                       if r["class"] != "all"]
    recall = {"id": "detection_recall", "kind": "comparison",
              "value": float(_search(r"headline macro recall ([0-9.]+)", d2)),
              "baseline": float(_search(r"vs SVM baseline ([0-9.]+)", d2)),
              "classes": len(failure_classes),
              "split": "test", "scope": "TEST, as reported in RESULTS.md", **_results_row(rows, "D2")}
    old_rule = p4_proof("old_rule_false_promotions", "old_rule_false_promotions")
    old_rule["definition"] = {"path": PREREG_P4, "line": _line_of(PREREG_P4, "An old-rule false promotion")}
    fresh = p4_proof("fresh_seed_failures", "gate_false_promotions_fresh_seeds")
    fresh["definition"] = {"path": PREREG_P4, "line": _line_of(PREREG_P4, "every gate-promoted patch is re-run")}
    return {"proof": [
        p4_proof("llm_patches_broke", "regression_breaks_test"),
        p4_proof("genuine_patches_broke", "other_fix_h3_breaks"),
        old_rule,
        fresh,
        recall,
    ]}


def _find_key(value, key: str):
    """First value of ``key`` anywhere in a JSON document."""
    if isinstance(value, dict):
        if key in value:
            return value[key]
        value = list(value.values())
    if isinstance(value, list):
        for item in value:
            found = _find_key(item, key)
            if found is not None:
                return found
    return None


def build_story() -> dict:
    """Every number the story sections below the hero print, keyed by id, each with its source row."""
    rows = results_md_rows()
    results_lines = (ROOT / RESULTS_MD).read_text(encoding="utf-8").splitlines()
    p4 = read_json(HEADLINE_P4)
    p4_num = {n["id"]: n for n in p4["numbers"]}
    p4_commit = p4["provenance"]["git_commit"][:7]
    p4_scope = "TEST, scored once; transcribed from the committed Phase 4 report, not recomputed"
    per_class = {r["class"]: r for r in p4["per_class_critic_vs_generic"]["rows"]}
    cost = read_json(HEAL_COST)
    p5 = read_json(HEADLINE_P5)
    l4 = read_json(L4_RERUN)["collector_healthy"]["paired_added_per_step"]

    def frac(number_id: str) -> dict:
        return _p4_fraction(p4_num, number_id, p4_commit)

    def class_arms(classes: list[str]) -> dict:
        """Promoted per eligible failure, critic vs generic, summed over ``classes``."""
        arms = {}
        for arm, name in (("v1_structured", "critic"), ("generic", "generic")):
            cells = [per_class[c]["promoted_per_eligible_failure"][arm] for c in classes]
            k, n = sum(c["k"] for c in cells), sum(c["n"] for c in cells)
            interval = cells[0]["wilson95"] if len(cells) == 1 else wilson95(k, n)
            arms[name] = {"k": k, "n": n, "wilson95": interval}
        return {"kind": "versus", **arms, "classes": classes, "split": "test", "scope": p4_scope,
                "interval_note": None if len(classes) == 1 else "Wilson 95% computed here from the summed counts",
                "source": {"path": HEADLINE_P4,
                           "locator": f"per_class_critic_vs_generic[{', '.join(classes)}] (commit {p4_commit})"},
                "cite": {"path": per_class[classes[0]]["source"]["path"],
                         "line": min(per_class[c]["source"]["line"] for c in classes)}}

    def row_line(row_id: str) -> str:
        return next(line for line in results_lines if line.startswith(f"| {row_id} |"))

    d1, d5, v11 = rows["D1"]["result"], rows["D5"]["result"], rows["S-v1.1-test"]["result"]
    tta = rows["P6-time-to-alert"]["result"]
    full_gate = cost["L1"]["full_gate"]["total_s"]
    promoted = sum(v.get("promoted", 0) for v in cost["gate_decisions"]["by_detector_failure_class"].values())
    provider = cost["L2"]["provider_usd"]
    repaired = frac("other_fix_v1_repaired")

    figures = [
        {"id": "repaired_vs_no_patch", "kind": "versus", "critic": _kn(repaired),
         "no_patch": _kn(frac("other_fix_no_patch_same_failures")),
         "split": "test", "scope": p4_scope, "source": repaired["source"], "cite": repaired["cite"]},
        {"id": "loop_tool_misfire", **class_arms(["LOOP_DETECTED", "TOOL_MISFIRE"])},
        {"id": "hallucination", **class_arms(["HALLUCINATION"])},
        {"id": "plan_drift", **class_arms(["PLAN_DRIFT"])},
        {"id": "regression_dev_test", "kind": "versus",
         "dev": _kn(frac("regression_breaks_dev")), "test": _kn(frac("regression_breaks_test")),
         "split": "test", "scope": "DEV and TEST, both on the A2 regression set",
         "source": frac("regression_breaks_test")["source"], "cite": frac("regression_breaks_dev")["cite"]},
        {"id": "time_to_alert", "kind": "values", "unit": "s",
         "values": {"p50": float(_search(r"native p50/p95 ([0-9.]+)/", tta)),
                    "p95": float(_search(r"native p50/p95 [0-9.]+/([0-9.]+)", tta)),
                    "n": int(_search(r"\(([0-9]+) DEV traces", tta))},
         "split": "dev", "scope": "DEV, live stack", **_results_row(rows, "P6-time-to-alert")},
        {"id": "time_to_verified_decision", "kind": "values", "unit": "s",
         "values": {"p50": round(full_gate["p50"], 1), "p90": round(full_gate["p90"], 1), "n": full_gate["n"]},
         "split": "dev", "scope": "DEV, one machine, one night",
         "source": {"path": HEAL_COST, "locator": "L1.full_gate.total_s"},
         "cite": {"path": HEAL_COST, "line": _line_of(HEAL_COST, '"full_gate"')}},
        {"id": "cost_per_fix", "kind": "values", "unit": "usd",
         "values": {"per_heal_mean": round(provider["mean"], 4), "total": round(provider["total"], 4),
                    "promoted": promoted, "per_promoted": round(provider["total"] / promoted, 4),
                    "heals": provider["n"]},
         "split": "dev", "scope": "DEV, provider usage-priced, not an invoice",
         "interval_note": "per_promoted is computed here: total provider cost divided by promoted heals",
         "source": {"path": HEAL_COST, "locator": "L2.provider_usd, gate_decisions.by_detector_failure_class"},
         "cite": {"path": HEAL_COST, "line": _line_of(HEAL_COST, '"provider_usd"')}},
        {"id": "sdk_overhead", "kind": "values", "unit": "ms",
         "values": {"p50": l4["p50_ms"], "p99": l4["p99_ms"]},
         "split": "dev", "scope": "DEV", **_results_row(rows, "P6-L4")},
        {"id": "ingestion", "kind": "values", "unit": "events/s",
         "values": {"sustained": p5["L3_ingestion_max_events_s"]},
         "split": "dev", "scope": "DEV, one laptop",
         "source": {"path": HEADLINE_P5, "locator": "L3_ingestion_max_events_s"},
         "cite": {"path": HEADLINE_P5, "line": _line_of(HEADLINE_P5, '"L3_ingestion_max_events_s"')}},
        {"id": "hallucination_precision", "kind": "values", "unit": "ratio",
         "values": {"primary": float(_search(r"H P=([0-9.]+)", d1)),
                    "target": float(_search(r"target P >= ([0-9.]+)", row_line("D1"))),
                    "v11": float(_search(r"H P=([0-9.]+)", v11))},
         "split": "test", "scope": "TEST, as reported in RESULTS.md (D1 primary, S-v1.1-test sensitivity)",
         **_results_row(rows, "D1")},
        {"id": "false_alerts", "kind": "values", "unit": "per 1,000 normal traces",
         "values": {"primary": float(_search(r"per 1,000 NORMAL: ([0-9.]+)", d5)),
                    "target": float(_search(r"target of <= ([0-9.]+) per 1,000", row_line("D5"))),
                    "v11": float(_search(r"FA/1000 ([0-9.]+)", v11))},
         "split": "test", "scope": "TEST, as reported in RESULTS.md (D5 primary, S-v1.1-test sensitivity)",
         **_results_row(rows, "D5")},
        {"id": "v11_registration", "kind": "values", "unit": "none", "values": {},
         "split": "test", "scope": "criterion registered before TEST scoring; labels applied after, to stored predictions",
         **_results_row(rows, "S-v1.1-test")},
        {"id": "critic_temperature", "kind": "values", "unit": "none",
         "values": {"temperature": _find_key(read_json(CRITIC_C1), "temperature")},
         "split": "dev", "scope": "critic settings",
         "source": {"path": CRITIC_C1, "locator": "temperature"},
         "cite": {"path": CRITIC_C1, "line": _line_of(CRITIC_C1, '"temperature"')}},
        {"id": "lite_limits", "kind": "values", "unit": "none", "values": {},
         "split": "dev", "scope": "lite mode", **_results_row(rows, "P6-lite-limits")},
        {"id": "invented_world", "kind": "values", "unit": "none", "values": {},
         "split": "dev", "scope": "benchmark datasheet",
         "source": {"path": DATASHEET, "locator": "World"},
         "cite": {"path": DATASHEET, "line": _line_of(DATASHEET, "fully fictional world")}},
    ]
    return {"figures": figures}


# ── heals (Phase 5 recorded runs) ────────────────────────────────────────────────────────────────
def _run_dir(phase5_runs: Path, run: str) -> Path:
    return phase5_runs / RUN_SUBDIRS[run] if RUN_SUBDIRS[run] else phase5_runs


def _load_run(phase5_runs: Path, run: str) -> dict[str, tuple[dict, dict, bytes, bytes]]:
    base = _run_dir(phase5_runs, run)
    records_dir, items_dir = base / "records", base / "items"
    if not records_dir.is_dir() or not items_dir.is_dir():
        raise ValueError(f"Phase 5 run directory not found: {base} (pass --phase5-runs or set NEXUS_PHASE5_RUNS)")
    loaded = {}
    for path in sorted(records_dir.glob("heal-*.json")):
        raw_record = path.read_bytes()
        raw_item = (items_dir / path.name).read_bytes()
        loaded[path.stem] = (json.loads(raw_record), json.loads(raw_item), raw_record, raw_item)
    return loaded


def _verify_main_run(main: dict) -> dict:
    """The raw records must be exactly the ones the committed Phase 5 results were computed from."""
    cost = read_json(HEAL_COST)
    if len(main) != 100:
        raise ValueError(f"Expected the 100 recorded heals, found {len(main)}")
    digest = sha256_bytes(*(main[key][2] for key in sorted(main)))
    committed = cost["methodology"]["source_records_sha256"]
    if digest != committed:
        raise ValueError(f"Phase 5 records differ from the committed results: {digest} != {committed}")
    counts: dict[str, dict[str, int]] = {}
    for record, _item, _raw, _raw_item in main.values():
        bucket = counts.setdefault(record["failure_class"], {})
        bucket[record["gate_decision"]] = bucket.get(record["gate_decision"], 0) + 1
    if counts != cost["gate_decisions"]["by_detector_failure_class"]:
        raise ValueError("Per-class gate decisions in the records differ from the committed results")
    return {"records_sha256": digest, "verified_against": f"{HEAL_COST}#methodology.source_records_sha256",
            "gate_decisions_by_class": counts, "records": len(main)}


def _verify_gemini_run(gemini: dict) -> dict:
    side = read_json(GEMINI_SIDE)
    paired = {p["item_id"]: p for p in side["paired_decisions"]}
    if len(gemini) != 20 or set(gemini) != set(paired):
        raise ValueError("Gemini side-row records do not match the committed paired decisions")
    for key, (record, *_rest) in gemini.items():
        if record["gate_decision"] != paired[key]["now"]:
            raise ValueError(f"Gemini side-row decision differs from {GEMINI_SIDE}: {key}")
    return {"verified_against": f"{GEMINI_SIDE}#paired_decisions", "records": len(gemini)}


def _outcome(value) -> str:
    return "skipped" if value is None else "pass" if value else "fail"


def _percent(rate) -> str:
    return "n/a" if rate is None else f"{rate * 100:.0f}%"


def _diff_for(target: str, patch: str | None, fault: str) -> str | None:
    """Unified diff of the recorded patch against the benchmark agent's system prompt it replaces."""
    if not patch or target not in {"_BASE_SYSTEM", "_GUESS_SYSTEM"}:
        return None
    from bench import agent

    original = getattr(agent, target)
    lines = difflib.unified_diff(original.splitlines(), patch.splitlines(),
                                 fromfile=f"bench/agent.py:{target} (as run)", tofile=f"{target} (critic patch)",
                                 lineterm="", n=2)
    text = "\n".join(lines)
    return text or None


def _critic_block(record: dict, fault: str) -> dict:
    proposal = record.get("proposal")
    status = record.get("proposal_status")
    if proposal is None:
        return {"status": "not_called", "reason": record.get("reason")}
    provenance = proposal.get("provenance") or {}
    patch, patch_total = clip(proposal.get("patch_content"), 3000)
    block = {
        "status": status,
        "provider": "Google Gemini" if str(provenance.get("model", "")).startswith("gemini") else "DeepSeek",
        "model": provenance.get("model"), "model_version": provenance.get("model_version"),
        "prompt_version": provenance.get("prompt_version"), "source": provenance.get("source"),
        "temperature": provenance.get("temperature"),
        "patch_type": proposal.get("patch_type"), "target_component": proposal.get("target_component"),
        "confidence": proposal.get("confidence"),
        "diagnosed_failure_type": proposal.get("diagnosed_failure_type"),
        "cited_span_id": proposal.get("cited_span_id"), "cited_step": proposal.get("cited_step"),
        "explanation": proposal.get("explanation"), "root_cause_analysis": proposal.get("root_cause_analysis"),
        "estimated_impact": proposal.get("estimated_impact"),
        "patch_content": patch,
        "diff": _diff_for(proposal.get("target_component", ""), proposal.get("patch_content"), fault),
        "dry_run_applied": proposal.get("dry_run_applied"),
        "critic_notes": list(proposal.get("rejection_reasons") or []),
        "usage": {"input_tokens": provenance.get("input_tokens"), "output_tokens": provenance.get("output_tokens"),
                  "latency_ms": provenance.get("latency_ms"), "cost_usd": provenance.get("cost_usd")},
    }
    if patch_total:
        block["patch_content_chars"] = patch_total
    return block


def _gate_block(record: dict) -> dict:
    gate = record.get("gate") or {}
    stage = record["stage_status"]
    own = record.get("own_runs")
    breaks = list(gate.get("regression_breaks") or [])
    checks = [
        {"id": "repair", "label": "Repair check",
         "rule": "The failing task must pass at least 2 of 3 re-runs with the patch.",
         "outcome": _outcome(gate.get("check1_own_task")), "stage_seconds": record["stages_s"]["gate_repair"],
         "detail": None if own is None else f"{sum(bool(x) for x in own)} of {len(own)} re-runs passed",
         "facts": {"runs": own}},
        {"id": "heldout", "label": "Held-out check",
         "rule": "The pass rate with the patch must be strictly above the no-patch rate on the same held-out tasks.",
         "outcome": _outcome(gate.get("check2_heldout")), "stage_seconds": record["stages_s"]["gate_heldout"],
         "detail": None if not gate else (f"with patch {_percent(gate.get('heldout_rate_patch'))} vs no patch "
                                          f"{_percent(gate.get('heldout_rate_nopatch'))} on {gate.get('heldout_n')} tasks"),
         "facts": {"patch_rate": gate.get("heldout_rate_patch"), "nopatch_rate": gate.get("heldout_rate_nopatch"),
                   "tasks": gate.get("heldout_n")}},
        {"id": "regression", "label": "Regression check",
         "rule": "No task that passed without the patch may fail with it.",
         "outcome": _outcome(gate.get("check3_no_regression")), "stage_seconds": record["stages_s"]["gate_regression"],
         "detail": None if not gate else (f"{gate.get('regression_checked')} passing tasks re-run; "
                                          f"{len(breaks)} broke" + (f": {', '.join(breaks)}" if breaks else "")),
         "facts": {"checked": gate.get("regression_checked"), "broken": breaks}},
    ]
    for check, key in zip(checks, ("gate_repair", "gate_heldout", "gate_regression"), strict=True):
        if stage[key] == "skipped":
            check["outcome"] = "skipped"
    decision = record["gate_decision"]
    failed = [c["label"] for c in checks if c["outcome"] == "fail"]
    if decision == "promoted":
        reason = "All three checks passed, so the patch is promoted."
    elif failed:
        names = [name.lower() for name in failed]
        joined = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        reason = f"Rejected: {joined} failed."
    else:
        reason = f"Rejected before the gate: {record.get('reason')}."
    return {"checks": checks, "decision": decision, "reason": reason, "promoted": bool(gate.get("promoted"))}


def _heal_block(heal_id: str, run: str, rule_id: str, rule_text: str, loaded, ctx: dict, side_paired: dict) -> dict:
    record, item, raw_record, raw_item = loaded
    trace_id = item["trace_id"]
    if trace_id not in ctx["labels"] or record.get("split") != "dev":
        raise ValueError(f"Heal {heal_id} is not a DEV heal")
    stages = record["stages_s"]
    usage = record.get("provider") if isinstance(record.get("provider"), dict) else {}
    block = {
        "heal_id": heal_id, "run": run, "run_label": RUN_LABELS[run], "category": rule_id,
        "selected_because": f"first {heal_id[:4]} in {RUN_LABELS[run]} matching: {rule_text}",
        "trace_id": trace_id, "task_id": record["task_id"], "family": item.get("family"),
        "dev_label": ctx["labels"][trace_id]["label"], "fault": record["fault"],
        "detector_failure_class": record["failure_class"],
        "critic": _critic_block(record, record["fault"]),
        "gate": _gate_block(record),
        "timing": {"total_s": record["total_s"], "stages_s": {k: stages[k] for k in
                   ("detect", "classify", "critic_call", "gate_repair", "gate_heldout", "gate_regression")}},
        "cost": {"provider_usd": usage.get("cost_usd"), "input_tokens": usage.get("input_tokens"),
                 "output_tokens": usage.get("output_tokens")},
        "source": {"run": RUN_LABELS[run], "record": f"{RUN_SUBDIRS[run] + '/' if RUN_SUBDIRS[run] else ''}records/{heal_id}.json",
                   "record_sha256": sha256_bytes(raw_record), "item_sha256": sha256_bytes(raw_item),
                   "execution_commit": record.get("git_commit"), "frozen_reference": record.get("frozen_reference")},
    }
    if run == "gemini":
        block["paired_headline_run"] = {"decision": side_paired[heal_id]["baseline"],
                                         "source": f"{GEMINI_SIDE}#paired_decisions"}
    return block


def build_heals(phase5_runs: Path, ctx: dict) -> tuple[list[dict], dict]:
    main = _load_run(phase5_runs, "main")
    gemini = _load_run(phase5_runs, "gemini")
    provenance = {"main_run": _verify_main_run(main), "gemini_run": _verify_gemini_run(gemini)}
    side_paired = {p["item_id"]: p for p in read_json(GEMINI_SIDE)["paired_decisions"]}
    runs = {"main": main, "gemini": gemini}
    heals, selection = [], []
    for rule_id, run, rule_text, predicate in HEAL_RULES:
        matches = [key for key in sorted(runs[run]) if predicate(runs[run][key][0])]
        if not matches:
            raise ValueError(f"No heal matches selection rule {rule_id}")
        heal_id = matches[0]
        selection.append({"rule": rule_id, "run": run, "describes": rule_text, "matches": len(matches),
                          "selected": heal_id})
        heals.append(_heal_block(heal_id, run, rule_id, rule_text, runs[run][heal_id], ctx, side_paired))
    provenance["selection"] = selection
    return heals, provenance


# ── assembly ─────────────────────────────────────────────────────────────────────────────────────
def selection_rule_text() -> dict:
    return {
        "traces": (f"For each predicted class in {', '.join(TRACE_CLASSES)}, the first {TRACES_PER_CLASS} DEV trace "
                   "ids in ascending order among the detector's DEV predictions. Chosen by id, not by how the run looks; "
                   "the detector verdict is shown next to the DEV label even where they disagree."),
        "heals": ("For each outcome rule below, in order, the lowest-numbered heal of the named run that matches. "
                  "Heals are chosen by outcome category, never by quality of the patch. The Phase 5 DEV runs hold no "
                  "heal that failed the repair check in the 100-heal run, so that category is taken from the separate "
                  "Gemini critic side row, which is labelled as such. No PLAN_DRIFT heal exists in the Phase 5 DEV runs."),
        "heal_rules": [{"rule": r[0], "run": r[1], "describes": r[2]} for r in HEAL_RULES],
    }


def build_replay(phase5_runs: Path) -> dict:
    ctx = load_dev_context()
    heals, heal_provenance = build_heals(phase5_runs, ctx)
    trace_ids = rule_selected_trace_ids(ctx["predictions"]) + [h["trace_id"] for h in heals]
    traces = build_trace_blocks(trace_ids, ctx)
    verdicts = {t["trace_id"]: t["detector"] for t in traces}
    for heal in heals:
        heal["detector"] = verdicts[heal["trace_id"]]
    selected_by_rule = rule_selected_trace_ids(ctx["predictions"])
    return {
        "schema_version": SCHEMA_VERSION, "mode": "replay", "split": "dev", "read_only": True,
        "notices": [
            "A recorded replay of DEV data. Nothing runs live: there is no backend, no key and no model call behind this page.",
            "Detector verdicts are the scored Phase 2 detectors' recorded DEV predictions; the live classifier reproduces them on all 359 DEV traces.",
            "Heals are the recorded Phase 5 overnight DEV runs: the critic's patch text, the gate checks and the decision are the recorded ones.",
            "Numbers marked TEST are shown only as already reported in RESULTS.md; no TEST trace or result file is read.",
            TRAIL_NOTICE,
        ],
        "provenance": {
            "generated_from_commit": git("rev-parse", "HEAD"),
            "repository": repository_url(),
            "exporter": "dashboard/scripts/export_replay.py",
            "data_statement": DATA_STATEMENT,
            "selection_rule": selection_rule_text(),
            "selected_trace_ids_by_rule": selected_by_rule,
            "sources": {path: blob_id(path) for path in SOURCES},
            "phase5_runs": heal_provenance,
            "phase5_runs_location": "nexus-phase5 repository, data/phase5/runs (outside this repository, read only)",
            "llm_calls": 0,
        },
        "headline": build_headline(),
        "external_trail": build_external_trail(ROOT),
        "traces": traces,
        "heals": heals,
    }


def render(replay: dict) -> str:
    return json.dumps(replay, ensure_ascii=False, separators=(",", ":")) + "\n"


def comparable(replay: dict) -> dict:
    """Everything except the commit the export ran on (it moves with every commit)."""
    clone = json.loads(json.dumps(replay))
    clone["provenance"].pop("generated_from_commit", None)
    return clone


def refresh_aggregates(committed: dict) -> dict:
    """Refresh published numbers without opening out-of-repo Phase 5 runs.

    Recorded DEV trace/heal bodies are retained and verify_committed checks
    them against in-repository DEV sources before this mode can publish.
    """
    result = json.loads(json.dumps(committed))
    result["headline"] = build_headline()
    result["external_trail"] = build_external_trail(ROOT)
    result["provenance"].update(generated_from_commit=git("rev-parse", "HEAD"),
        data_statement=DATA_STATEMENT, sources={path: blob_id(path) for path in SOURCES})
    if TRAIL_NOTICE not in result["notices"]:
        result["notices"].append(TRAIL_NOTICE)
    problems = verify_committed(result)
    if problems:
        raise ValueError("Aggregate refresh failed verification: " + "; ".join(problems))
    return result


def verify_committed(committed: dict) -> list[str]:
    """Problems with a replay.json, re-derived from in-repository sources only (no Phase 5 runs needed).

    Used by CI. Empty list means: DEV only, publishable, every source blob is the current one, and the
    traces, headline numbers and the heal bookkeeping all re-derive from the committed results.
    """
    problems: list[str] = []
    if (committed.get("schema_version"), committed.get("mode"), committed.get("split"), committed.get("read_only")) \
            != (SCHEMA_VERSION, "replay", "dev", True):
        problems.append("replay.json is not a read-only DEV replay of the current schema version")
        return problems
    try:
        assert_publishable(committed)
    except ValueError as exc:
        problems.append(str(exc))
    provenance = committed["provenance"]
    if provenance.get("llm_calls") != 0:
        problems.append("provenance.llm_calls must be 0")
    if provenance.get("data_statement") != DATA_STATEMENT:
        problems.append("provenance.data_statement changed")
    if set(provenance["sources"]) != set(SOURCES):
        problems.append("provenance.sources does not list the exporter's source files")
    for path in SOURCES:
        if provenance["sources"].get(path) != blob_id(path):
            problems.append(f"stale: {path} changed since replay.json was exported")
    if problems:
        return problems

    if committed.get("external_trail") != build_external_trail(ROOT):
        problems.append("stale: external TRAIL aggregates differ or contain unapproved fields")

    ctx = load_dev_context()
    by_rule = rule_selected_trace_ids(ctx["predictions"])
    if provenance["selected_trace_ids_by_rule"] != by_rule:
        problems.append("stale: rule-selected trace ids differ from the current detector predictions")
    heal_trace_ids = [h["trace_id"] for h in committed["heals"]]
    shown = {t["trace_id"] for t in committed["traces"]}
    if not set(by_rule + heal_trace_ids) <= shown or not shown <= set(ctx["labels"]):
        problems.append("traces must be exactly the DEV traces selected by rule plus the heals' traces")
    fresh = {t["trace_id"]: t for t in build_trace_blocks(sorted(shown & set(ctx["labels"])), ctx)}
    if {t["trace_id"]: t for t in committed["traces"]} != fresh:
        problems.append("stale: trace blocks differ from the DEV adapter and detector predictions")
    if committed["headline"] != build_headline():
        problems.append("stale: headline numbers differ from RESULTS.md and results/*.json")

    cost = read_json(HEAL_COST)
    main_run = provenance["phase5_runs"]["main_run"]
    if main_run["records_sha256"] != cost["methodology"]["source_records_sha256"] \
            or main_run["gate_decisions_by_class"] != cost["gate_decisions"]["by_detector_failure_class"]:
        problems.append("stale: heal provenance differs from results/phase5/heal_latency_cost.json")
    paired = {p["item_id"]: p for p in read_json(GEMINI_SIDE)["paired_decisions"]}
    if {r["rule"] for r in provenance["phase5_runs"]["selection"]} != {r[0] for r in HEAL_RULES}:
        problems.append("selection rules differ from the exporter's HEAL_RULES")
    verdicts = {t["trace_id"]: t["detector"] for t in committed["traces"]}
    for heal in committed["heals"]:
        name = heal["heal_id"]
        checks = heal["gate"]["checks"]
        outcomes = [c["outcome"] for c in checks]
        if [c["id"] for c in checks] != ["repair", "heldout", "regression"]:
            problems.append(f"{name}: gate must list the repair, held-out and regression checks")
        if heal["gate"]["decision"] != ("promoted" if outcomes == ["pass"] * 3 else "rejected"):
            problems.append(f"{name}: decision is inconsistent with the three check outcomes")
        if heal["critic"]["status"] != "patch" and outcomes != ["skipped"] * 3:
            problems.append(f"{name}: a heal without a patch cannot have run gate checks")
        if heal["detector"] != verdicts.get(heal["trace_id"]):
            problems.append(f"{name}: detector block differs from its trace")
        if heal["run"] == "gemini" and heal["gate"]["decision"] != paired[name]["now"]:
            problems.append(f"{name}: decision differs from {GEMINI_SIDE}")
    return problems


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--phase5-runs", type=Path, default=DEFAULT_PHASE5_RUNS)
    parser.add_argument("--check", action="store_true", help="fail if the committed replay.json is stale")
    parser.add_argument("--refresh-aggregates", action="store_true",
                        help="refresh numbers from committed sources, retaining verified DEV trace/heal bodies")
    parser.add_argument("--verify", action="store_true",
                        help="CI check: re-derive everything that needs no Phase 5 runs from in-repository sources")
    args = parser.parse_args(argv)
    if args.verify:
        if not DESTINATION.is_file():
            raise ValueError("replay.json is missing; run python dashboard/scripts/export_replay.py")
        problems = verify_committed(json.loads(DESTINATION.read_text(encoding="utf-8")))
        if problems:
            raise ValueError("replay.json failed verification:\n- " + "\n- ".join(problems))
        print("replay.json verified against in-repository sources")
        return
    replay = (refresh_aggregates(json.loads(DESTINATION.read_text(encoding="utf-8")))
              if args.refresh_aggregates else build_replay(args.phase5_runs))
    # Validate before writing anything, even when exporting without Vite.
    assert_publishable(replay)
    if args.check:
        if not DESTINATION.is_file():
            raise ValueError("replay.json is missing; run python dashboard/scripts/export_replay.py")
        committed = json.loads(DESTINATION.read_text(encoding="utf-8"))
        if comparable(committed) != comparable(replay):
            raise ValueError("replay.json is stale: it differs from a fresh export of the current sources")
        print("replay.json is current")
        return
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    text = render(replay)
    DESTINATION.write_text(text, encoding="utf-8")
    print(f"Exported {len(replay['heals'])} heals, {len(replay['traces'])} DEV traces to {DESTINATION} "
          f"({len(text.encode('utf-8')):,} bytes)")


if __name__ == "__main__":
    try:
        main()
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc
