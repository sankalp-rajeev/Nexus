"""Post-hoc diagnostics on TRAIL-A (development data after scoring).

Never writes scored results or original checkpoints. All per-trace/claim
observations stay under the excluded diagnostics directory. A fresh, authorized
offline run is observational and is never a replacement accuracy evaluation.
"""
from __future__ import annotations

from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import difflib
import functools
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "sdk"), str(ROOT)]
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"

from scripts.external import score_trail as scoring
from scripts.external.trail_dev_check_a1 import applicability
from services.detectors import hallucination, pipeline
from nexus_agent.models import SpanType

PRIVATE = scoring.PRIVATE
DIAG = PRIVATE / "diagnostics"
RESULT = ROOT / "results/external/trail_test.json"
REPORT = ROOT / "reports/external/trail_results.md"
_ID = re.compile(r"\b(?:[A-Za-z]{1,6}-\d{3,8}|[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}|[0-9a-fA-F]{32})\b")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def distribution(values):
    values = sorted(values)
    if not values:
        return {"n": 0}
    def quantile(p):
        pos = (len(values) - 1) * p
        lo, hi = math.floor(pos), math.ceil(pos)
        return values[lo] + (values[hi] - values[lo]) * (pos - lo)
    return {"n": len(values), "min": values[0], "p25": quantile(.25), "median": quantile(.5),
            "p75": quantile(.75), "p90": quantile(.9), "p95": quantile(.95), "max": values[-1],
            "mean": sum(values) / len(values), "sum": sum(values)}


def scrub_ids(value):
    if isinstance(value, dict):
        return {k: "<ID>" if k.lower() in {"id", "uuid"} or k.lower().endswith("_id") else scrub_ids(v)
                for k, v in value.items()}
    if isinstance(value, list):
        return [scrub_ids(v) for v in value]
    if isinstance(value, str):
        return _ID.sub("<ID>", value)
    return value


def argument_difference(a, b):
    """Post-hoc descriptions only; never used for detection or classification."""
    try:
        left, right = json.loads(a), json.loads(b)
    except (TypeError, ValueError):
        left, right = a, b
    ca, cb = json.dumps(left, sort_keys=True), json.dumps(right, sort_keys=True)
    if ca == cb:
        if a == b:
            return "exact"
        return "whitespace_only" if re.sub(r"\s+", "", a) == re.sub(r"\s+", "", b) else "json_formatting_or_key_order_only"
    if json.dumps(scrub_ids(left), sort_keys=True) == json.dumps(scrub_ids(right), sort_keys=True):
        return "ID_pattern_or_ID_field_only"
    if max(len(ca), len(cb)) <= 20000 and difflib.SequenceMatcher(None, ca, cb).ratio() >= .90:
        return "small_edit_similarity_at_least_0.90"
    return "other_changed_arguments"


def steps_for(view, *, original_tool=False):
    out = []
    for position, span in enumerate(view.spans):
        raw = span.metadata.get("otel.attributes", {})
        is_original = str(raw.get("openinference.span.kind", "")).upper() == "TOOL"
        if original_tool:
            if not is_original:
                continue
        elif span.span_type not in (SpanType.TOOL_CALL, SpanType.MEMORY_READ):
            continue
        try:
            args = json.loads(span.input) if span.input else {}
        except (ValueError, TypeError):
            args = span.input
        out.append({"span_id": span.span_id, "position": position,
            "tool": str(span.metadata.get("tool_name") or span.span_type.value),
            "args_text": json.dumps(args, sort_keys=True), "raw_input": span.input,
            "ok": span.error_type is None, "error_type": span.error_type,
            "parent_span_id": span.parent_span_id, "nexus_kind": span.span_type.value})
    return out


def sequence_features(steps):
    longest = streak = 0
    previous = None
    exact_at, tool_at = {}, {}
    changes = Counter()
    exact_nonconsecutive = gaps_between_equal = 0
    run_lengths = []
    for index, step in enumerate(steps):
        key = step["tool"], step["args_text"]
        if step["ok"]:
            streak = streak + 1 if previous and previous["ok"] and key == (previous["tool"], previous["args_text"]) else 1
        else:
            streak = 0
        longest = max(longest, streak)
        run_lengths.append(streak)
        if key in exact_at:
            prior = exact_at[key]
            exact_nonconsecutive += index - prior > 1
        exact_at[key] = index
        if step["tool"] in tool_at:
            prior = steps[tool_at[step["tool"]]]
            changes[argument_difference(prior["raw_input"], step["raw_input"])] += 1
        tool_at[step["tool"]] = index
        if previous and step["ok"] and previous["ok"] and key == (previous["tool"], previous["args_text"]):
            gaps_between_equal += step["position"] - previous["position"] > 1
        previous = step
    return {"tool_steps": len(steps), "longest_successful_identical_consecutive_run": longest,
        "exact_repeat_pairs_separated_by_other_tool_steps": exact_nonconsecutive,
        "equal_consecutive_tool_pairs_with_other_spans_between": gaps_between_equal,
        "argument_changes_between_successive_calls_of_same_tool": dict(changes),
        "per_call_successful_run_length": run_lengths}


def nesting(view, steps):
    by_id = {s.span_id: s for s in view.spans}
    nested = 0
    for step in steps:
        parent, seen = step["parent_span_id"], set()
        while parent in by_id and parent not in seen:
            seen.add(parent)
            span = by_id[parent]
            if span.span_type == SpanType.AGENT_STEP:
                nested += 1
                break
            parent = span.parent_span_id
    return {"tool_steps": len(steps), "with_agent_ancestor": nested}


def safe_error_type(value):
    value = str(value)
    if re.fullmatch(r"(?:[A-Za-z_]\w*\.)*[A-Za-z_]\w{0,127}", value):
        return value
    return "non_class_string_sha256_" + hashlib.sha256(value.encode()).hexdigest()


def error_features(view, original, visible):
    errors = [s for s in view.spans if s.error_type is not None]
    types = Counter(safe_error_type(s.error_type) for s in errors)
    original_errors = [s for s in original if not s["ok"]]
    visible_errors = [s for s in visible if not s["ok"]]
    retry = Counter()
    for i, step in enumerate(original):
        if step["ok"]:
            continue
        following = original[i+1:i+3]
        same = [n for n in following if n["tool"] == step["tool"]]
        retry["error_events_with_same_tool_in_next_2_original_tool_calls"] += bool(same)
        retry["error_events_with_identical_args_retry_in_next_2_original_tool_calls"] += any(n["args_text"] == step["args_text"] for n in same)
        retry["error_events_with_changed_args_retry_in_next_2_original_tool_calls"] += any(n["args_text"] != step["args_text"] for n in same)
        retry["error_events_followed_by_successful_same_tool_in_next_2_original_tool_calls"] += any(n["ok"] for n in same)
    return {"all_span_error_types": dict(types), "original_tool_error_types": dict(Counter(safe_error_type(s["error_type"]) for s in original_errors)),
        "visible_tool_error_types": dict(Counter(safe_error_type(s["error_type"]) for s in visible_errors)),
        "all_span_errors": len(errors), "original_tool_errors": len(original_errors),
        "visible_tool_errors": len(visible_errors), "retagged_retrieval_errors": sum(s["nexus_kind"] == "retrieval" for s in original_errors),
        "retry_patterns": dict(retry)}


def label_locations(label, view):
    positions = {s.span_id.lower(): i for i, s in enumerate(view.spans)}
    carriers = {i for i, s in enumerate(view.spans) if s.output and s.output == view.final_output}
    counts = Counter()
    for error in label.get("errors", []):
        if not isinstance(error, dict) or not isinstance(error.get("category"), str):
            continue
        if scoring.CATEGORY_CLASS.get(scoring.normalize_category(error["category"])) != "HALLUCINATION":
            continue
        position = scoring.resolve_location(error.get("location"), positions)
        if position is None:
            counts["unresolved_annotation_location"] += 1
        else:
            counts["final_output_carrier" if position in carriers else "non_final_output_carrier"] += 1
            raw = view.spans[position].metadata.get("otel.attributes", {})
            kind = raw.get("openinference.span.kind", "UNSPECIFIED")
            counts["raw_kind_" + (kind if kind in {"LLM","TOOL","AGENT","CHAIN","RETRIEVER"} else "UNSPECIFIED")] += 1
    return dict(counts)


def observe_claims(pairs, probs, claims, premises, tokenizer, max_length):
    """Observe the returned probabilities unchanged, using the frozen gate."""
    k = len(premises)
    if len(pairs) != len(claims) * k:
        raise RuntimeError("Unexpected frozen NLI pair layout")
    full = tokenizer([p for p, _ in pairs], [c for _, c in pairs], truncation=False, padding=False, add_special_tokens=True)
    cut = tokenizer([p for p, _ in pairs], [c for _, c in pairs], truncation="longest_first",
                    max_length=max_length, padding=False, add_special_tokens=True)
    premise_tokens = [len(tokenizer(p, add_special_tokens=False)["input_ids"]) for p in premises]
    claim_tokens = [len(tokenizer(c, add_special_tokens=False)["input_ids"]) for c in claims]
    pair_info = []
    for index, (a, b) in enumerate(zip(full["input_ids"], cut["input_ids"])):
        seqs = cut.encodings[index].sequence_ids
        pair_info.append({"full_tokens": len(a), "kept_tokens": len(b), "removed_tokens": len(a)-len(b),
            "removed_premise_tokens": premise_tokens[index % k] - seqs.count(0),
            "removed_claim_tokens": claim_tokens[index // k] - seqs.count(1)})
    claim_info = []
    for i, claim in enumerate(claims):
        entities = hallucination.entities(claim)
        raw = [float(probs[i*k+j][hallucination._ENTAIL_IDX]) for j in range(k)]
        allowed = [all(e in p.lower() for e in entities) for p in premises]
        gated = [value if ok else 0.0 for value, ok in zip(raw, allowed)]
        claim_info.append({"claim_index": i, "source": "CompleteTrace.final_output", "characters": len(claim),
            "tokens": claim_tokens[i], "entity_count": len(entities), "allowed_premise_units": sum(allowed),
            "raw_best_entailment": max(raw), "best_entailment_after_entity_gate": max(gated),
            "per_premise_entailment": raw, "entity_gate_allowed": allowed})
    return {"claims": claim_info, "pairs": pair_info, "premise_unit_tokens": premise_tokens,
            "premise_unit_characters": [len(p) for p in premises]}


def save_json(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temp, path)


def main():
    preflight, catalog, ids = scoring.preflight()
    result = json.loads(RESULT.read_text())
    sanity = json.loads((PRIVATE / "part3_sanity.json").read_text())
    immutable = {str(p): sha(p) for p in (RESULT, REPORT, scoring.STATE)}
    if immutable[str(RESULT)] != sanity["result_sha256_before"]:
        raise RuntimeError("Scored result changed since sanity check")
    expected_ids = ids - set(result["conversion_failure_ids"])
    if len(expected_ids) != 63 or any(result["classes"][c]["tp"] + result["classes"][c]["fp"] for c in ("LOOP_DETECTED", "TOOL_MISFIRE")):
        raise RuntimeError("Original decision reconstruction assumptions differ")
    if result["classes"]["HALLUCINATION"]["tp"] + result["classes"]["HALLUCINATION"]["fp"] != result["classes"]["HALLUCINATION"]["evaluated"]:
        raise RuntimeError("Original eligible hallucination decisions cannot all be reconstructed as positive")
    DIAG.mkdir(parents=True, exist_ok=True)
    marker = DIAG / "run_state.json"
    if marker.exists():
        raise RuntimeError("Existing diagnostic run; inspect before repeating")
    state = {"status": "running", "scope": "post-hoc diagnostics on TRAIL-A (development data after scoring)",
        "started_at_utc": datetime.now(timezone.utc).isoformat(), "completed_ids": [], "expected": 63,
        "immutable_sha256": immutable, "preflight": preflight,
        "diagnostic_code_commit": scoring.git("rev-parse", "HEAD").decode().strip(),
        "diagnostic_script_sha256": sha(Path(__file__))}
    save_json(marker, state)
    started = time.perf_counter()
    logging.getLogger("transformers").setLevel(logging.ERROR)
    try:
        with (DIAG / "runtime.log").open("a", encoding="utf-8") as log:
            with redirect_stdout(log), redirect_stderr(log):
                model = hallucination._nli()
                tokenizer = model.tokenizer
                max_length = int(model.max_length or tokenizer.model_max_length)
            state["model_max_pair_tokens"] = max_length
            thresholds = pipeline.load_thresholds()
            for tid, split, source, label in scoring.load_requested(catalog["entries"], expected_ids, PRIVATE / "a2_source"):
                with redirect_stdout(log), redirect_stderr(log):
                    view = scoring.convert_for_evaluation(source)
                    if view is None:
                        raise RuntimeError("Previously converted A trace no longer converts")
                    gold, _, _ = scoring.map_labels(label, view)
                    reached, reason = applicability(view)
                    claims = hallucination.claims(view.final_output or "", view.root_input or "")
                    context = hallucination.retrieved_context(view)
                    units = hallucination.premise_units(context)
                    observed = {}
                    original_predict = model.predict
                    # Synchronous hook for this iteration, restored in finally below.
                    @functools.wraps(original_predict)
                    def capture(pairs, *args, **kwargs):
                        probabilities = original_predict(pairs, *args, **kwargs)  # noqa: B023
                        observed.update(observe_claims(pairs, probabilities, claims, units, tokenizer, max_length))  # noqa: B023
                        return probabilities  # Original object, unchanged, to frozen code.
                    model.predict = capture
                    try:
                        scores = pipeline.compute_scores(view)
                    finally:
                        model.predict = original_predict
                    flags = pipeline.fired(scores, thresholds)
                    fresh_label = pipeline.label(scores, thresholds)
                    expected = {"LOOP_DETECTED": False, "TOOL_MISFIRE": False,
                                "HALLUCINATION": True if reached and reason is None else None}
                    actual = {"LOOP_DETECTED": bool(scores.loop), "TOOL_MISFIRE": bool(scores.misfire),
                              "HALLUCINATION": bool(flags["HALLUCINATION"]) if reached and reason is None else None}
                    changed = [cls for cls in scoring.CLASSES if expected[cls] != actual[cls]]
                    if reached and scores.halluc is not None:
                        reconstructed = 1 - min(c["best_entailment_after_entity_gate"] for c in observed["claims"])
                        if not math.isclose(reconstructed, scores.halluc, abs_tol=1e-12):
                            raise RuntimeError("Observer disagrees with unchanged frozen NLI aggregation")
                    original_steps = steps_for(view, original_tool=True)
                    visible_steps = steps_for(view)
                    raw_steps = [{k: v for k, v in step.items() if k not in {"args_text", "raw_input"}}
                                 | {"args_sha256": hashlib.sha256(step["args_text"].encode()).hexdigest()} for step in original_steps]
                    record = {"trace_id": tid, "split": split, "gold_classes": gold,
                        "raw_pipeline_label": fresh_label, "flags": flags,
                        "raw_outputs": {"loop": bool(scores.loop), "misfire": bool(scores.misfire),
                            "bleed": scores.bleed, "drift": scores.drift, "hallucination": scores.halluc},
                        "expected_scored_decisions_reconstructed": expected, "decision_differences": changed,
                        "hallucination_applicability": {"reached": reached, "reason": reason},
                        "original_tool_steps": raw_steps,
                        "loop_visible": sequence_features(visible_steps), "loop_original_tool": sequence_features(original_steps),
                        "nesting_original_tools": nesting(view, original_steps), "nesting_visible_tools": nesting(view, visible_steps),
                        "errors": error_features(view, original_steps, visible_steps),
                        "hallucination_labels_on_eligible": label_locations(label, view) if reached and reason is None else {},
                        "claim_count": len(claims), "retrieved_characters": sum(map(len, context)),
                        "nli_observations": observed}
                    save_json(DIAG / f"{tid}.json", record)
                state["completed_ids"].append(tid)
                save_json(marker, state)
                print(json.dumps({"diagnostic_A_completed": len(state["completed_ids"]), "of": 63}), flush=True)
        if set(state["completed_ids"]) != expected_ids:
            raise RuntimeError("Diagnostic A membership incomplete")
        for name, expected_sha in immutable.items():
            if sha(name) != expected_sha:
                raise RuntimeError("Read-only scored artifact changed")
        state["status"] = "complete"
        state["runtime_seconds"] = time.perf_counter() - started
        save_json(marker, state)
        print(json.dumps({"diagnostic_status": "complete", "runtime_seconds": state["runtime_seconds"]}), flush=True)
    except BaseException as exc:
        state["status"] = "failed"
        state["failure_type"] = type(exc).__name__
        last = traceback.extract_tb(exc.__traceback__)[-1]
        state["failure_location"] = {"file": Path(last.filename).name, "function": last.name, "line": last.lineno}
        state["runtime_seconds"] = time.perf_counter() - started
        save_json(marker, state)
        raise


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        print(json.dumps({"STOP": "diagnostic run failed", "exception_type": type(exc).__name__}))
        raise SystemExit(1) from None
