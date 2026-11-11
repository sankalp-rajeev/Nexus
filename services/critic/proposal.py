"""Strict model response and provenance, without changing shared SDK schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from nexus_agent.models import PatchProposal, PatchType

PROMPT_VERSION = "critic-groundwork-v1"


class StructuredPatch(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    patch_type: PatchType
    target_component: str
    explanation: str
    patch_content: str
    confidence: Literal["HIGH", "MEDIUM", "LOW"]
    estimated_impact: str
    root_cause_analysis: str


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


class CriticProposal(PatchProposal):
    provenance: Provenance
    valid_without_fallback: bool = False
    dry_run_applied: bool = False
    rejection_reasons: list[str] = Field(default_factory=list)
