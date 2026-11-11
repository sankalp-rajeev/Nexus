"""DEV-only label adapter and snapshot of existing NexusBench configuration constants.

TEST label payloads are discarded before CSV deserialization; TEST traces are
skipped by their top-level trace ID before JSON deserialization. No cache, gold
answers, manifest, TEST labels or TEST trace objects are loaded by this module.
"""
from __future__ import annotations

import copy
import csv
import itertools
import json
import re
from pathlib import Path

from nexus_agent.models import CompleteTrace

from services.critic.evidence import FailureEvidence

CLASSES = ("HALLUCINATION", "TOOL_MISFIRE", "CONTEXT_BLEED", "PLAN_DRIFT", "LOOP_DETECTED")


def dev_labels(path):
    """Gate on the first five identifier columns before decoding any label fields."""
    with Path(path).open("r", encoding="utf-8", newline="") as stream:
        header = next(csv.reader([stream.readline()]))
        if header[:5] != ["run_id", "trace_id", "task_id", "family", "split"]:
            raise ValueError("Unrecognized labels layout: refusing to inspect records")
        while True:
            prefix = ""
            for _ in range(5):
                field = ""
                while True:
                    char = stream.read(1)
                    if not char:
                        if prefix or field:
                            raise ValueError("Truncated label identifiers")
                        return
                    field += char
                    if char == ",":
                        break
                    if char in '\n\r"':
                        raise ValueError("Unexpected identifier encoding; refusing record")
                prefix += field
            split = prefix.rstrip(",").rsplit(",", 1)[-1]
            if split == "dev":
                # csv.reader consumes continuation lines of this DEV record only.
                row = next(csv.reader(itertools.chain([prefix + stream.readline()], stream)))
                yield dict(zip(header, row, strict=True))
            elif split == "test":
                # Discard opaque bytes/text; do not construct a row or inspect labels.
                # Quoted fields may contain line breaks, so advance to the CSV boundary.
                quoted = False
                while True:
                    chunk = stream.readline()
                    if not chunk:
                        break
                    quoted ^= bool(chunk.count('"') % 2)
                    if not quoted:
                        break
            else:
                raise ValueError("Unknown split; refusing to read label payload")


def dev_traces(path, allowed_ids):
    """Only deserialize whitelisted DEV traces; fail closed on unexpected layout."""
    found = {}
    with Path(path).open("rb") as stream:
        for raw in stream:
            # The committed generator sorts keys, placing top-level trace_id last.
            # Raw non-DEV records pass through this gate without JSON decoding.
            match = re.search(rb', "trace_id": "([^"\r\n]+)"\}\r?\n?$', raw)
            if not match:
                match = re.match(rb'^\{"trace_id": "([^"\r\n]+)"', raw)
            if not match:
                raise ValueError("Unrecognized top-level trace ID; refusing to load payload")
            trace_id = match[1].decode("ascii")
            if trace_id in allowed_ids:
                found[trace_id] = CompleteTrace.model_validate_json(raw)
    if found.keys() != set(allowed_ids):
        raise ValueError("Some requested DEV traces were unavailable")
    return found


def current_config(label):
    """Existing module keys, with the active system prompt from this run's fault.

    These are read-only snapshots of real constants, not newly invented runtime
    knobs. Runtime config injection and replay belong to a later phase.
    """
    from bench import agent
    active = "_GUESS_SYSTEM" if label["fault"] == "HALLUCINATION" else "_BASE_SYSTEM"
    return {active: getattr(agent, active), "MAX_STEPS": agent.MAX_STEPS,
            "TOOL_SPECS": copy.deepcopy(agent.TOOL_SPECS)}


def evidence_from_dev(label, trace):
    if label.get("split") != "dev":
        raise ValueError("Only DEV labels may enter the critic adapter")
    failure_type = label["label"]
    if failure_type not in CLASSES:
        raise ValueError("A five-class failure label is required")
    spans = trace.spans
    if failure_type == "HALLUCINATION":
        candidates = [s for s in spans if s.metadata.get("role") == "root"]
    elif failure_type == "CONTEXT_BLEED":
        candidates = [s for s in spans if s.span_type.value == "memory_read"]
    elif failure_type == "TOOL_MISFIRE":
        candidates = [s for s in spans if s.error_type]
    elif failure_type == "PLAN_DRIFT":
        from bench.tools import DRIFT_CUSTOMER
        candidates = [s for s in spans if s.span_type.value == "tool_call" and DRIFT_CUSTOMER in s.input]
    else:
        candidates = []
        calls = [s for s in spans if s.span_type.value in {"tool_call", "memory_read"}]
        for a, b, c in zip(calls, calls[1:], calls[2:]):
            if (a.metadata.get("tool_name"), a.input) == (b.metadata.get("tool_name"), b.input) == (c.metadata.get("tool_name"), c.input):
                candidates = [c]
                break
    if not candidates:
        raise ValueError(f"Cannot locate supporting span for {failure_type}")
    span = candidates[0]
    # Only observed trace content + DEV rule; never the gold answer or fault name.
    text = json.dumps({"dev_label": failure_type, "input": span.input, "output": span.output,
                       "error": span.error_message, "metadata": span.metadata}, ensure_ascii=False)
    return FailureEvidence(failure_type=failure_type, span_id=span.span_id,
                           supporting_text=text)
