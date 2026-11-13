# Nexus — Data Models & Schemas

All Pydantic models are the single source of truth in
[`sdk/nexus_llmops/models.py`](../sdk/nexus_llmops/models.py) (also importable as `nexus_agent.models`).
The Postgres DDL lives in [`infra/init/postgres_init.sql`](../infra/init/postgres_init.sql). The flow between
services is in the README's architecture diagram.

## Span (core SDK model)

```python
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
    span_id: str                       # default: span_<uuid12>
    trace_id: str                      # groups all spans of one run
    parent_span_id: str | None = None
    agent_name: str
    span_type: SpanType
    input: str                         # serialized, max 2000 chars
    output: str | None = None          # serialized, max 2000 chars
    duration_ms: float
    error_type: str | None = None
    error_message: str | None = None   # max 500 chars
    metadata: dict[str, Any] = {}
    client_timestamp: datetime
    server_timestamp: datetime | None = None  # set by collector
    environment: str = "development"
    sdk_version: str

class SpanBatch(BaseModel):
    spans: list[Span]                  # max_length=100
    batch_id: str                      # default: uuid hex
```

### Metadata keys the service reads

| Key | Set by | Meaning |
|---|---|---|
| `final` | SDK on the root span; collector on a parentless OTLP span | Complete the trace on arrival instead of waiting for the idle timeout |
| `nexus.synthetic` (boolean) | Load tools | Classified, but never published to `nexus.alerts` (counted as `synthetic_suppressed`) |
| `otel.legacy_aliases` | Collector, OTLP path | Legacy GenAI attribute names that were mapped |
| `nexus.content_refs`, `nexus.content_missing` | Collector, OTLP path | Message content was referenced but not sent; a loop verdict resting only on such spans is dropped |

## Trace assembly

```python
class TraceStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"

class CompleteTrace(BaseModel):
    trace_id: str
    agent_name: str
    environment: str = "development"
    root_input: str | None = None
    final_output: str | None = None
    span_count: int = 0
    total_duration_ms: float | None = None
    started_at: datetime
    completed_at: datetime | None = None
    status: TraceStatus = IN_PROGRESS
    spans: list[Span] = []
```

The assembler and the classifier each assemble traces from `nexus.spans.raw` with their own
`TraceBuffer` ([`services/common/trace_buffer.py`](../services/common/trace_buffer.py)), which drops replayed
spans by `span_id`.

## Failure Taxonomy

```python
class FailureType(str, Enum):
    HALLUCINATION = "HALLUCINATION"   # output contradicts retrieved context/facts
    TOOL_MISFIRE  = "TOOL_MISFIRE"    # bad args, error, identical retry
    CONTEXT_BLEED = "CONTEXT_BLEED"   # memory inconsistent with task context
    PLAN_DRIFT    = "PLAN_DRIFT"      # execution deviated from planner subtasks
    LOOP_DETECTED = "LOOP_DETECTED"   # same tool+args >= 3 times
    NORMAL        = "NORMAL"
```

## Classification & Alert

The live classifier publishes each `Classification` to `nexus.spans.classified` and, for a non-`NORMAL`,
non-synthetic trace, an `Alert` to `nexus.alerts` (keyed by `agent_name`).

```python
class Classification(BaseModel):
    classification_id: str
    trace_id: str
    failure_type: FailureType
    anomaly_score: float | None       # PatchCore distance
    confidence: float | None          # 0-1
    triggered_rule: str | None        # rule name, or 'patchcore'
    failure_span_id: str | None
    created_at: datetime

class ClassifiedSpan(BaseModel):     # defined, but the classifier publishes Classification
    span: Span
    failure_type: FailureType
    anomaly_score: float | None = None
    triggered_rule: str | None = None

class Alert(BaseModel):
    alert_id: str
    trace_id: str
    classification_id: str | None
    agent_name: str
    failure_type: FailureType
    severity: AlertSeverity = HIGH    # HIGH | MEDIUM | LOW
    status: AlertStatus = OPEN        # OPEN | ACKNOWLEDGED | RESOLVED
    created_at: datetime
    resolved_at: datetime | None
```

## PatchProposal

```python
class PatchType(str, Enum):
    PROMPT_PATCH       = "PROMPT_PATCH"
    TOOL_CONFIG_PATCH  = "TOOL_CONFIG_PATCH"
    MEMORY_PATCH       = "MEMORY_PATCH"
    RETRY_POLICY_PATCH = "RETRY_POLICY_PATCH"

class PatchProposal(BaseModel):
    proposal_id: str                  # default: patch_<uuid8>
    alert_id: str
    trace_id: str
    failure_type: FailureType
    patch_type: PatchType
    target_component: str
    explanation: str                  # 2-3 sentences
    patch_content: str                # copy-pasteable patch
    confidence: Literal["HIGH","MEDIUM","LOW"]
    estimated_impact: str
    root_cause_analysis: str
    created_at: datetime
    status: Literal["PENDING_REVIEW","APPROVED","REJECTED","APPLIED"] = "PENDING_REVIEW"
```

## Eval & Health

```python
class EvalResult(BaseModel):
    composite_score: float
    per_metric: dict[str, float]

class EvalRun(BaseModel):
    run_id: str
    patch_id: str | None
    trace_id: str
    agent_name: str
    before_score: float | None
    after_score: float | None
    score_delta: float | None         # DB: GENERATED (after - before)
    per_metric_scores: dict[str, float]
    eval_duration_ms: float | None
    mlflow_run_id: str | None
    created_at: datetime

class HealthDiff(BaseModel):
    agent_name: str
    before_score: float
    after_score: float
    score_delta: float
    failure_type: FailureType
    patch_id: str | None
    created_at: datetime

class AgentConfig(BaseModel):          # Config Store row (agent_configs)
    config_id: str
    agent_name: str
    component_name: str
    config_type: Literal["prompt","tool_config","retry_policy"]
    content: str
    version: int = 1
    applied_patch_id: str | None
    created_at: datetime
    updated_at: datetime
```

## Postgres Tables

| Table | Purpose | Written by (live stack) |
|---|---|---|
| `traces` | One row per agent execution run | assembler |
| `spans` | TimescaleDB hypertable, partitioned on `server_timestamp` | assembler |
| `classifications` | Per-trace failure classification result | not written on the live path (classifications go to Kafka) |
| `alerts` | Fired alerts for non-NORMAL classifications | not written on the live path (alerts go to Kafka) |
| `patches` | Critic-produced patch proposals (`PENDING_REVIEW` only for an LLM patch that passed the dry run) | critic; status set to `APPLIED` by the healer only with `NEXUS_HEALER_AUTO_APPLY=true`, and by the API on approve/reject |
| `eval_runs` | Before/after eval scores (auto-computed `score_delta`) | healer (also marks a proposal as evaluated when auto-apply is off) |
| `agent_configs` | Config Store: active prompt/tool/retry content per component | healer, only with `NEXUS_HEALER_AUTO_APPLY=true` (legacy, unverified: no promotion gate); off by default |

Lite mode does not use Postgres: one SQLite file holds spans and the `traces`, `alerts`, `proposals` and
`gate_decisions` artifacts ([`services/collector/lite.py`](../services/collector/lite.py)).
