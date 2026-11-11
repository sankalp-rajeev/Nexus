"""Rule-defined detectors: TOOL_MISFIRE and LOOP_DETECTED.

Changes from the v3 Stage-1 rules (services/classifier/rules.py), both general:

* The retry window is counted in *tool calls*, not raw spans. A span window
  depends on how densely a trace is instrumented (LLM and step spans sit
  between tool calls), so the same behaviour fell inside or outside the window
  depending on instrumentation, not on the agent.
* LOOP counts consecutive identical *successful* calls; identical calls that
  keep erroring are a misfire (bad call retried), not a loop.
"""

from __future__ import annotations

from nexus_agent.models import CompleteTrace

from services.detectors.common import tool_calls

RETRY_WINDOW_CALLS = 2
LOOP_MIN_REPEATS = 3


def misfire(trace: CompleteTrace) -> bool:
    calls = tool_calls(trace)
    for i, c in enumerate(calls):
        if c.ok:
            continue
        key = (c.tool, c.args_text)
        if any((n.tool, n.args_text) == key for n in calls[i + 1:i + 1 + RETRY_WINDOW_CALLS]):
            return True
    return False


def loop(trace: CompleteTrace) -> bool:
    calls = tool_calls(trace)
    streak = 1
    for prev, cur in zip(calls, calls[1:]):
        if cur.ok and prev.ok and (cur.tool, cur.args_text) == (prev.tool, prev.args_text):
            streak += 1
            if streak >= LOOP_MIN_REPEATS:
                return True
        else:
            streak = 1
    return False
