"""LangGraph state machine for the nexus-critic agent (Section 9.2).

Graph topology:
  START → context_loader → root_cause → patch_proposer → validator
    ↪ (rejected, retry_count < 2) → root_cause
    ↪ (rejected, retry_count >= 2) → fallback → publisher → END
    ↪ (passed)                    → publisher → END
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import TypedDict

logger = logging.getLogger("nexus.critic.graph")

TOPIC_PATCHES = "nexus.patches"
_MAX_RETRIES = int(os.getenv("CRITIC_MAX_RETRIES", "2"))


# ── State ────────────────────────────────────────────────────────────────────

class CriticState(TypedDict, total=False):
    alert_id: str
    trace_id: str
    agent_name: str
    failure_type: str
    failure_span_id: str | None
    trace: object          # CompleteTrace | None
    root_cause_analysis: str
    patch_proposal: dict | None
    validation_passed: bool
    rejection_reason: str
    retry_count: int
    final_proposal: object  # PatchProposal | None


# ── Node implementations ──────────────────────────────────────────────────────

def make_context_loader(db):
    def context_loader(state: CriticState) -> CriticState:
        trace = db.load_trace(state["trace_id"])
        if trace is None:
            logger.warning("nexus-critic: trace %s not found in Postgres", state["trace_id"])
        return {**state, "trace": trace}
    return context_loader


def make_root_cause_node(llm_factory):
    from services.critic.validator import format_trace_for_prompt

    def _load_prompt() -> str:
        path = os.path.join(os.path.dirname(__file__), "prompts", "root_cause.txt")
        with open(path, encoding="utf-8") as f:
            return f.read()

    prompt_template = _load_prompt()

    def root_cause(state: CriticState) -> CriticState:
        trace = state.get("trace")
        failure_type = state["failure_type"]
        failure_span_id = state.get("failure_span_id")

        if trace is None:
            rca = (
                f"Trace {state['trace_id']} not found in Postgres. "
                f"Failure type {failure_type} detected by classifier but trace unavailable for analysis."
            )
            return {**state, "root_cause_analysis": rca}

        formatted = format_trace_for_prompt(trace)
        prompt = prompt_template.format(
            failure_type=failure_type,
            span_count=len(trace.spans),
            formatted_trace=formatted,
        )
        span_id = failure_span_id or (trace.spans[-1].span_id if trace.spans else "unknown")
        provider = llm_factory(failure_type=failure_type, span_id=span_id)
        rca = provider.complete(prompt)
        logger.debug("nexus-critic: root_cause done (%d chars)", len(rca))
        return {**state, "root_cause_analysis": rca}

    return root_cause


def make_patch_proposer_node(llm_factory):
    from services.critic.validator import format_failure_span

    def _load_prompt() -> str:
        path = os.path.join(os.path.dirname(__file__), "prompts", "patch_proposer.txt")
        with open(path, encoding="utf-8") as f:
            return f.read()

    prompt_template = _load_prompt()

    def patch_proposer(state: CriticState) -> CriticState:
        trace = state.get("trace")
        rca = state.get("root_cause_analysis", "")
        failure_type = state["failure_type"]
        failure_span_id = state.get("failure_span_id")

        failure_span_content = format_failure_span(trace, failure_span_id) if trace else "unavailable"
        prompt = prompt_template.format(
            root_cause_analysis=rca,
            failure_type=failure_type,
            failure_span_content=failure_span_content,
        )
        span_id = failure_span_id or "span_00"
        provider = llm_factory(failure_type=failure_type, span_id=span_id)
        raw = provider.complete(prompt)

        # Extract JSON from the response (handle markdown code blocks).
        match = re.search(r"\{[\s\S]+\}", raw)
        if match:
            try:
                proposal = json.loads(match.group())
                return {**state, "patch_proposal": proposal}
            except json.JSONDecodeError:
                pass
        logger.warning("nexus-critic: patch_proposer JSON parse failed; raw=%r", raw[:200])
        return {**state, "patch_proposal": None}

    return patch_proposer


def validator_node(state: CriticState) -> CriticState:
    from services.critic.validator import validate_patch_proposal

    proposal = state.get("patch_proposal")
    if proposal is None:
        return {**state, "validation_passed": False, "rejection_reason": "No proposal produced",
                "retry_count": state.get("retry_count", 0) + 1}
    valid, reason = validate_patch_proposal(proposal)
    new_retry = state.get("retry_count", 0) + (0 if valid else 1)
    return {**state, "validation_passed": valid, "rejection_reason": reason,
            "retry_count": new_retry}


def make_fallback_node():
    from services.critic.fallback import make_fallback_proposal
    from nexus_agent.models import FailureType

    def fallback(state: CriticState) -> CriticState:
        logger.info("nexus-critic: using fallback proposal for %s", state["failure_type"])
        try:
            ft = FailureType(state["failure_type"])
        except ValueError:
            ft = FailureType.NORMAL
        proposal = make_fallback_proposal(
            alert_id=state["alert_id"],
            trace_id=state["trace_id"],
            failure_type=ft,
            root_cause_analysis=state.get("root_cause_analysis", ""),
        )
        return {**state, "final_proposal": proposal}

    return fallback


def make_publisher_node(db, kafka_producer=None):
    from nexus_agent.models import FailureType, PatchProposal, PatchType

    def publisher(state: CriticState) -> CriticState:
        proposal = state.get("final_proposal")
        if proposal is None:
            raw = state.get("patch_proposal") or {}
            try:
                ft = FailureType(state["failure_type"])
                pt = PatchType(raw.get("patch_type", "PROMPT_PATCH"))
            except ValueError:
                ft = FailureType.NORMAL
                pt = PatchType.PROMPT_PATCH
            proposal = PatchProposal(
                alert_id=state["alert_id"],
                trace_id=state["trace_id"],
                failure_type=ft,
                patch_type=pt,
                target_component=raw.get("target_component", "unknown"),
                explanation=raw.get("explanation", ""),
                patch_content=raw.get("patch_content", ""),
                confidence=raw.get("confidence", "LOW"),
                estimated_impact=raw.get("estimated_impact", "unknown"),
                root_cause_analysis=state.get("root_cause_analysis", ""),
            )
        db.write_patch(proposal)
        if kafka_producer is not None:
            import json as _json
            kafka_producer.produce(
                TOPIC_PATCHES, key=proposal.trace_id.encode(),
                value=proposal.model_dump_json().encode(),
            )
            kafka_producer.poll(0)
        return {**state, "final_proposal": proposal}

    return publisher


# ── Graph builder ─────────────────────────────────────────────────────────────

def build_graph(db, llm_factory=None, kafka_producer=None):
    """Build and compile the LangGraph StateGraph for the critic pipeline."""
    from langgraph.graph import StateGraph, END

    if llm_factory is None:
        from services.critic.llm import make_provider as llm_factory

    graph = StateGraph(CriticState)

    graph.add_node("context_loader", make_context_loader(db))
    graph.add_node("root_cause", make_root_cause_node(llm_factory))
    graph.add_node("patch_proposer", make_patch_proposer_node(llm_factory))
    graph.add_node("validator", validator_node)
    graph.add_node("fallback", make_fallback_node())
    graph.add_node("publisher", make_publisher_node(db, kafka_producer))

    graph.set_entry_point("context_loader")
    graph.add_edge("context_loader", "root_cause")
    graph.add_edge("root_cause", "patch_proposer")
    graph.add_edge("patch_proposer", "validator")

    def _after_validator(state: CriticState) -> str:
        if state.get("validation_passed"):
            return "publisher"
        if state.get("retry_count", 0) < _MAX_RETRIES:
            return "root_cause"
        return "fallback"

    graph.add_conditional_edges("validator", _after_validator)
    graph.add_edge("fallback", "publisher")
    graph.add_edge("publisher", END)

    return graph.compile()


def run_critic(alert, db, llm_factory=None, kafka_producer=None) -> object:
    """Run the full critic graph for one Alert; returns the PatchProposal."""
    app = build_graph(db, llm_factory=llm_factory, kafka_producer=kafka_producer)
    failure_span_id = getattr(alert, "failure_span_id", None) or None
    initial: CriticState = {
        "alert_id": alert.alert_id,
        "trace_id": alert.trace_id,
        "agent_name": alert.agent_name,
        "failure_type": alert.failure_type.value,
        "failure_span_id": failure_span_id,
        "retry_count": 0,
        "validation_passed": False,
        "patch_proposal": None,
        "final_proposal": None,
        "root_cause_analysis": "",
    }
    result = app.invoke(initial)
    return result.get("final_proposal")
