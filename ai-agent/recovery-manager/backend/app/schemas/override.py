from typing import Optional
from pydantic import BaseModel, Field, field_validator


class ChargeOverrideRequest(BaseModel):
    """Payload for human operator override."""
    new_verdict: str = Field(..., min_length=1, description="Operator verdict: e.g. APPROVED, REJECTED, CLAIM_ELIGIBLE, NOT_ELIGIBLE")
    reason: str = Field(..., min_length=1, description="Required non-empty justification for overriding the automated verdict")
    reviewer_id: str = Field(default="operator", min_length=1, description="Freeform operator/reviewer identifier")

    @field_validator("reason")
    @classmethod
    def validate_non_empty_reason(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Reason must be non-empty")
        return v.strip()


class ChargeOverrideResponse(BaseModel):
    """Response returned upon capturing an immutable override audit record."""
    id: str
    charge_id: str
    claim_id: Optional[str] = None
    org_id: str
    original_assessment: Optional[str] = None
    original_status: Optional[str] = None
    new_verdict: str
    reason: str
    reviewer_id: str
    created_at: str
    action_taken: str
