"""The detector-to-critic contract, independent of any detector implementation."""

from pydantic import BaseModel, ConfigDict, Field, model_validator
from nexus_agent.models import FailureType


class FailureEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    # Detector evidence is observation-only; its predicted type lives in Alert.
    # Historical, explicitly enabled oracle evidence may still carry a type.
    failure_type: FailureType | None = None
    span_id: str | None = None
    step: int | None = Field(default=None, ge=0)
    supporting_text: str = Field(min_length=1)

    @model_validator(mode="after")
    def located(self):
        if self.span_id is None and self.step is None:
            raise ValueError("Evidence must identify a span or step")
        if self.failure_type == FailureType.NORMAL:
            raise ValueError("NORMAL is not failure evidence")
        return self
