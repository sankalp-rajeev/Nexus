"""Dev-only adapter and detector smoke check; exports aggregate coverage only.

No labels, detector values, predictions, trace content, or test spans are
exported. HALLUCINATION can abstain when its frozen evidence path is absent.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "sdk"), str(ROOT)]
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"

from scripts.external.prepare_trail import DEV_COUNTS, EXPECTED, PRIVATE, REVISION, SPLITS, parquet_files
from services.collector.openinference import complete_trace
from services.detectors import hallucination, pipeline, rules
from services.detectors.common import planned_tools, tool_calls
from bench.detector_view import detector_view


def git(*args) -> bytes:
    return subprocess.check_output(["git", "-c", f"safe.directory={ROOT.as_posix()}", *args], cwd=ROOT)


def check_frozen() -> dict:
    from scripts.phase5.check_frozen import PATHS, TAG

    if git("branch", "--show-current").decode().strip() != "external-validation":
        raise RuntimeError("Wrong branch")
    checked = 0
    for tag, paths in (("phase2-detectors-frozen", ("services/detectors/",)), (TAG, PATHS)):
        if git("diff", "--name-only", tag, "--", *paths):
            raise RuntimeError("Frozen Git content differs")
        excluded = {p.removeprefix(":(exclude)") for p in paths if p.startswith(":(exclude)")}
        names = git("ls-tree", "-r", "--name-only", tag, "--",
                    *(p for p in paths if not p.startswith(":"))).decode().splitlines()
        for name in names:
            if name in excluded:
                continue
            if (ROOT / name).read_bytes().replace(b"\r\n", b"\n") != git("show", f"{tag}:{name}").replace(b"\r\n", b"\n"):
                raise RuntimeError("Frozen working bytes differ")
            checked += 1
    return {"normalized_file_comparisons": checked, "phase2_detectors_unchanged": True,
            "phase4_shared_freeze_unchanged": True}


def dev_ids() -> dict[str, set[str]]:
    manifest = json.loads((SPLITS / "manifest.json").read_text())
    if manifest["revision"] != REVISION or manifest["source_counts"] != EXPECTED:
        raise RuntimeError("Unexpected manifest")
    partitions = {}
    for filename, digest in manifest["sha256"].items():
        blob = (SPLITS / filename).read_bytes()
        if hashlib.sha256(blob).hexdigest() != digest:
            raise RuntimeError("Sealed split digest mismatch")
        partitions[filename] = set(blob.decode("ascii").splitlines())
    result = {}
    for split in EXPECTED:
        dev, test = partitions[f"dev_{split}.txt"], partitions[f"test_{split}.txt"]
        if dev & test or len(dev) != DEV_COUNTS[split] or len(dev | test) != EXPECTED[split]:
            raise RuntimeError("Invalid sealed partition")
        result[split] = dev
    return result


def dev_traces():
    import pyarrow.parquet as pq

    selections = dev_ids()
    for split, path in parquet_files().items():
        found = set()
        # Read only the trace column, never labels. Check its leading ID before
        # JSON deserialization, so sealed test span objects are never inspected.
        for blob in pq.read_table(path, columns=["trace"]).column("trace").to_pylist():
            match = re.match(r'\s*\{\s*"trace_id"\s*:\s*"([0-9a-f]{32})"', blob)
            if not match:
                raise RuntimeError("Unexpected leading trace ID schema")
            if match[1] not in selections[split]:
                continue
            if match[1] in found:
                raise RuntimeError("Duplicate dev trace")
            found.add(match[1])
            yield split, json.loads(blob)
        if found != selections[split]:
            raise RuntimeError("Missing dev traces")


def readable_source(text: str | None) -> bool:
    """Label-independent conservative text gate, fixed before external scoring."""
    return bool(text and len(text.strip()) >= 20 and len(re.findall(r"[^\W\d_]{2,}", text)) >= 3)


def main() -> None:
    frozen = check_frozen()
    totals = Counter()
    by_split = {}
    attrs = Counter()
    kinds = Counter()
    th = pipeline.load_thresholds()
    for split, source in dev_traces():
        counts = by_split.setdefault(split, Counter())
        trace = complete_trace(source)
        calls = tool_calls(trace)
        premises = hallucination.retrieved_context(trace)
        plan = planned_tools(trace)
        available = {
            "traces": 1, "spans": len(trace.spans), "tool_spans": len(calls),
            "root_input_present": bool(trace.root_input), "final_output_present": bool(trace.final_output),
            "loop_three_or_more_captured_tool_steps": len(calls) >= rules.LOOP_MIN_REPEATS and all(c.span.input.strip() for c in calls),
            "misfire_tool_error_present": any(not c.ok for c in calls),
            "misfire_error_then_same_tool_within_retry_window": any(
                not c.ok and any(n.tool == c.tool for n in calls[i+1:i+1+rules.RETRY_WINDOW_CALLS])
                for i, c in enumerate(calls)),
            "successful_tool_output_readable": any(c.ok and readable_source(c.span.output) for c in calls),
            "frozen_nli_source_present": any(readable_source(p) for p in premises),
            "frozen_nli_claims_present": bool(hallucination.claims(trace.final_output or "", trace.root_input or "")),
            "explicit_declared_tool_plan": bool(plan and all(t.strip() for t in plan)),
        }
        for span in trace.spans:
            raw = span.metadata["otel.attributes"]
            # Only allow known schema names into aggregates. Values stay private.
            for key in ("input.value", "output.value", "tool.name", "tool.parameters",
                        "llm.model_name", "llm.token_count.prompt", "llm.token_count.completion",
                        "nexus.agent.role", "nexus.agent.plan_steps"):
                attrs[key] += key in raw
            for direction in ("input", "output"):
                attrs[f"llm.{direction}_messages.*"] += any(k.startswith(f"llm.{direction}_messages") for k in raw)
            kind = raw.get("openinference.span.kind", "UNSPECIFIED")
            kinds[kind if kind in {"AGENT", "CHAIN", "LLM", "TOOL", "RETRIEVER"} else "UNSPECIFIED"] += 1
        # Smoke only: discard numeric scores and predicted classes immediately.
        view = detector_view(trace.model_dump(mode="json"))
        output = pipeline.compute_scores(view)
        assert isinstance(output.loop, bool) and isinstance(output.misfire, bool)
        assert isinstance(output.drift, dict)
        assert output.halluc is None or isinstance(output.halluc, float)
        assert pipeline.label(output, th) in {*pipeline.ORDER, "NORMAL"}
        available["pipeline_output_produced"] = 1
        available["hallucination_abstained_no_evidence_or_claims"] = output.halluc is None
        counts.update({k: int(v) for k, v in available.items()})
        totals.update({k: int(v) for k, v in available.items()})
    if totals["traces"] != 15:
        raise RuntimeError("Dev trace count mismatch")
    report = {"scope": "dev-only; no labels or predictions exported", "revision": REVISION,
              "frozen_checks": frozen, "aggregate": dict(totals),
              "by_split": {k: dict(v) for k, v in by_split.items()},
              "attribute_span_counts": dict(attrs), "span_kind_counts": dict(kinds)}
    target = ROOT / "reports/external/trail_dev_coverage.json"
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Validation exceptions may include captured input. Never print them.
        print(json.dumps({"STOP": "dev check failed", "exception_type": type(exc).__name__}))
        raise SystemExit(1) from None
