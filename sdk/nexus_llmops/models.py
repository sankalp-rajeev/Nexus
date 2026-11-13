"""Nexus shared data models — single source of truth for all schemas.

Locked in Phase 1. Covers Section 13.1 (SDK core), plus the shared enums and
artifacts (FailureType, PatchProposal, Alert, Classification, etc.) referenced
across the classifier, critic, healer, and API services.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────────────────
# Span (Section 13.1) — core SDK model
# ──────────────────────────────────────────────────────────────────────────
class SpanType(str, Enum):
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    AGENT_STEP = "agent_step"
    MEMORY_READ = "memory_read"
    MEMORY_WRITE = "memory_write"
    AGENT_HANDOFF = "agent_handoff"
    RETRIEVAL = "retrieval"
    CUSTOM = "custom"


class Span(BaseModel):
    span_id: str = Field(default_factory=lambda: f"span_{uuid4().hex[:12]}")
    trace_id: str  # Groups all spans of one agent run
    parent_span_id: str | None = None  # For nested spans
    agent_name: str  # Top-level agent system name
    span_type: SpanType
    input: str  # Serialized input, max 2000 chars
    output: str | None = None  # Serialized output, max 2000 chars
    duration_ms: float
    error_type: str | None = None  # Exception class name if raised
    error_message: str | None = None  # Exception message, max 500 chars
    metadata: dict[str, Any] = {}  # Arbitrary: model, tokens, tool_name, etc.
    client_timestamp: datetime
    server_timestamp: datetime | None = None  # Set by collector on receipt
    environment: str = "development"
    sdk_version: str


class SpanBatch(BaseModel):
    spans: list[Span] = Field(max_length=100)
    batch_id: str = Field(default_factory=lambda: uuid4().hex)


# ──────────────────────────────────────────────────────────────────────────
# Trace assembly (Section 8.4 / 13.2)
# ──────────────────────────────────────────────────────────────────────────
class TraceStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class CompleteTrace(BaseModel):
    """A fully assembled trace: the trace row + all its spans."""

    trace_id: str
    agent_name: str
    environment: str = "development"
    root_input: str | None = None
    final_output: str | None = None
    span_count: int = 0
    total_duration_ms: float | None = None
    started_at: datetime
    completed_at: datetime | None = None
    status: TraceStatus = TraceStatus.IN_PROGRESS
    spans: list[Span] = []


# ──────────────────────────────────────────────────────────────────────────
# Failure taxonomy (Section 8.1)
# ──────────────────────────────────────────────────────────────────────────
class FailureType(str, Enum):
    HALLUCINATION = "HALLUCINATION"  # output contradicts retrieved context / facts
    TOOL_MISFIRE = "TOOL_MISFIRE"  # bad args, returned error, retried identically
    CONTEXT_BLEED = "CONTEXT_BLEED"  # memory read inconsistent with task context
    PLAN_DRIFT = "PLAN_DRIFT"  # execution deviated from planner subtasks
    LOOP_DETECTED = "LOOP_DETECTED"  # same tool+args called >= 3 times
    NORMAL = "NORMAL"  # no anomaly detected


# ──────────────────────────────────────────────────────────────────────────
# Classification & alerts (Section 13.2)
# ──────────────────────────────────────────────────────────────────────────
class Classification(BaseModel):
    classification_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str
    failure_type: FailureType
    anomaly_score: float | None = None  # PatchCore distance
    confidence: float | None = None  # 0-1
    triggered_rule: str | None = None  # rule name, or 'patchcore'
    failure_span_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ClassifiedSpan(BaseModel):
    """Value published to nexus.spans.classified."""

    span: Span
    failure_type: FailureType
    anomaly_score: float | None = None
    triggered_rule: str | None = None


class AlertSeverity(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class AlertStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class Alert(BaseModel):
    alert_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str
    classification_id: str | None = None
    agent_name: str
    failure_type: FailureType
    severity: AlertSeverity = AlertSeverity.HIGH
    status: AlertStatus = AlertStatus.OPEN
    created_at: datetime = Field(default_factory=datetime.utcnow)
    resolved_at: datetime | None = None


# ──────────────────────────────────────────────────────────────────────────
# Patch proposals (Section 9.4)
# ──────────────────────────────────────────────────────────────────────────
class PatchType(str, Enum):
    PROMPT_PATCH = "PROMPT_PATCH"
    TOOL_CONFIG_PATCH = "TOOL_CONFIG_PATCH"
    MEMORY_PATCH = "MEMORY_PATCH"
    RETRY_POLICY_PATCH = "RETRY_POLICY_PATCH"


class PatchProposal(BaseModel):
    proposal_id: str = Field(default_factory=lambda: f"patch_{uuid4().hex[:8]}")
    alert_id: str
    trace_id: str
    failure_type: FailureType
    patch_type: PatchType
    target_component: str  # e.g. "planner_system_prompt", "search_tool_validator"
    explanation: str  # 2-3 sentences
    patch_content: str  # the actual patch — prompt text, config JSON, snippet
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    estimated_impact: str  # e.g. "eval score expected to improve by 0.2-0.4"
    root_cause_analysis: str  # preserved from root_cause node
    created_at: datetime = Field(default_factory=datetime.utcnow)
    status: Literal["PENDING_REVIEW", "APPROVED", "REJECTED", "APPLIED"] = "PENDING_REVIEW"


# ──────────────────────────────────────────────────────────────────────────
# Eval + health (Section 10 / 11)
# ──────────────────────────────────────────────────────────────────────────
class EvalResult(BaseModel):
    composite_score: float
    per_metric: dict[str, float] = {}


class EvalRun(BaseModel):
    run_id: str = Field(default_factory=lambda: uuid4().hex)
    patch_id: str | None = None
    trace_id: str
    agent_name: str
    before_score: float | None = None
    after_score: float | None = None
    score_delta: float | None = None
    per_metric_scores: dict[str, float] = {}
    eval_duration_ms: float | None = None
    mlflow_run_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class HealthDiff(BaseModel):
    agent_name: str
    before_score: float
    after_score: float
    score_delta: float
    failure_type: FailureType
    patch_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class AgentConfig(BaseModel):
    config_id: str = Field(default_factory=lambda: uuid4().hex)
    agent_name: str
    component_name: str
    config_type: Literal["prompt", "tool_config", "retry_policy"]
    content: str
    version: int = 1
    applied_patch_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
