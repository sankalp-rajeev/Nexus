"""Strict model response and provenance, without changing shared SDK schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from nexus_agent.models import FailureType, PatchProposal, PatchType

PROMPT_VERSION = "critic-round3-v1"


class CriticConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    critic_arm: Literal["new", "v1_structured"] = "new"


class StructuredDiagnosis(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    diagnosed_failure_type: FailureType
    cited_span_id: str | None
    cited_step: int | None = Field(ge=0)
    root_cause_analysis: str


class StructuredPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    patch_type: PatchType
    target_component: str
    explanation: str
    patch_content: str
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    estimated_impact: str
    root_cause_analysis: str
    # Nullable for historical responses. Never infer these from the alert/evidence.
    diagnosed_failure_type: FailureType | None = None
    cited_span_id: str | None = None
    cited_step: int | None = Field(default=None, ge=0)


def response_schema(model=StructuredPatch):
    """Inline references and require nullable properties for strict transports."""
    raw = model.model_json_schema()
    def inline(node):
        if isinstance(node, list):
            return [inline(v) for v in node]
        if not isinstance(node, dict):
            return node
        if "$ref" in node:
            return inline(raw["$defs"][node["$ref"].rsplit("/", 1)[-1]])
        result = {k: inline(v) for k, v in node.items() if k not in {"$defs", "default"}}
        if result.get("type") == "object":
            result["required"] = list(result.get("properties", {}))
        return result
    return inline(raw)


class Provenance(BaseModel):
    source: Literal["llm", "fallback"]
    model: str
    model_version: str
    temperature: float
    prompt_version: str = PROMPT_VERSION
    input_tokens: int | None = Field(default=0, ge=0)
    output_tokens: int | None = Field(default=0, ge=0)
    cost_usd: float = Field(default=0, ge=0)
    latency_ms: float = Field(default=0, ge=0)
    mock: bool = False
    prompt_hashes: dict[str, str] = Field(default_factory=dict)


class CriticProposal(PatchProposal):
    critic_arm: Literal["new", "v1_structured", "original"] = "new"
    diagnosed_failure_type: FailureType | None = None
    cited_span_id: str | None = None
    cited_step: int | None = Field(default=None, ge=0)
    provenance: Provenance
    valid_without_fallback: bool = False
    dry_run_applied: bool = False
    rejection_reasons: list[str] = Field(default_factory=list)
