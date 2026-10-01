"""Pydantic schemas for Phase 7 Claim Engine."""

from decimal import Decimal
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field

from app.ai.schemas import (
    AIAssessmentResponse,
    EvidenceInputSchema,
    ProcessingStateSchema,
)
from app.rules.schemas import RuleValidationResult


class ClaimEngineRequest(BaseModel):
    """Input payload for Claim Engine execution."""
    model_config = ConfigDict(extra="forbid")

    charge_id: str = Field(..., min_length=1, description="External marketplace charge identifier")
    validation_result: RuleValidationResult = Field(..., description="Computed output from Phase 6 Rule Validation")
    assessment_response: AIAssessmentResponse = Field(..., description="Computed output from Phase 5 AI Reasoning")
    evidence: List[EvidenceInputSchema] = Field(
        default_factory=list,
        description="Evidence list supplied during assessment and validation",
    )
    processing_state: ProcessingStateSchema = Field(
        default_factory=ProcessingStateSchema,
        description="Operational processing flags",
    )


class ClaimEngineResult(BaseModel):
    """Strict structured output model for Phase 7 Claim Engine."""
    model_config = ConfigDict(extra="forbid")

    outcome: Literal[
        "CLAIM_CREATED",
        "ALREADY_CLAIMED",
        "NO_CLAIM",
        "HUMAN_REVIEW",
        "BLOCKED",
        "REJECTED_AT_CLAIM_ENGINE",
    ] = Field(..., description="High-level processing outcome of the Claim Engine")
    charge_id: str = Field(..., description="External marketplace charge identifier")
    claim_id: Optional[str] = Field(default=None, description="External human-readable claim tracking ID (e.g. CLM-...)")
    status: Optional[str] = Field(default=None, description="The claims.status value if a row exists in the claims table")
    reason: str = Field(..., min_length=1, description="Detailed explanatory text for the outcome")
    claim_amount: Optional[Decimal] = Field(default=None, description="Persisted financial claim amount if eligible")
    evidence_ids: List[str] = Field(default_factory=list, description="Validated evidence IDs linked to the claim")
