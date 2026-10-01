"""Pydantic schemas for Phase 5 AI Reasoning / Recovery Assessment."""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AssessmentType(str, Enum):
    """The four valid assessment states under the 'Evidence first, claim second' principle."""
    CONTRADICTED = "CONTRADICTED"
    SUPPORTED = "SUPPORTED"
    SILENT = "SILENT"
    UNCERTAIN = "UNCERTAIN"


class ChargeInputSchema(BaseModel):
    """Structured charge input supplied to the AI reasoning engine."""
    model_config = ConfigDict(extra="forbid")

    charge_id: str = Field(..., min_length=1, description="External marketplace charge identifier")
    charge_type: str = Field(..., min_length=1, description="Classification or fee reason")
    amount: Decimal = Field(..., gt=Decimal("0.00"), description="Monetary charge amount")
    shipment_id: Optional[str] = Field(default=None, description="Associated shipment identifier")
    order_id: Optional[str] = Field(default=None, description="Associated order identifier")
    sku: Optional[str] = Field(default=None, description="Associated SKU identifier")
    asin: Optional[str] = Field(default=None, description="Associated ASIN identifier")
    unit_id: Optional[str] = Field(default=None, description="Associated UNIT identifier")
    fnsku: Optional[str] = Field(default=None, description="Associated FNSKU identifier")
    charge_date: Optional[datetime] = Field(default=None, description="Timestamp of the charge")


class EvidenceInputSchema(BaseModel):
    """Deterministically retrieved operational evidence supplied to the AI reasoning engine."""
    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(..., min_length=1, description="Operational evidence identifier")
    source_manager: str = Field(..., min_length=1, description="Department that produced proof")
    evidence_type: str = Field(..., min_length=1, description="Type of operational check")
    evidence_timestamp: datetime = Field(..., description="Timestamp of evidence collection")
    evidence_content: Dict[str, Any] = Field(..., description="Proof payload findings")
    matched_by: str = Field(..., min_length=1, description="Deterministic match key")
    match_value: str = Field(..., min_length=1, description="Exact match value")
    matched_keys: Optional[List[str]] = Field(default=None, description="All matching keys")


class ProcessingStateSchema(BaseModel):
    """Current processing state of the charge."""
    model_config = ConfigDict(extra="forbid")

    duplicate: bool = Field(default=False, description="Whether charge is a duplicate")
    already_reimbursed: bool = Field(default=False, description="Whether charge was already reimbursed")


class AIAssessmentRequest(BaseModel):
    """Top-level structured input for AI recovery assessment."""
    model_config = ConfigDict(extra="forbid")

    charge: ChargeInputSchema
    evidence: List[EvidenceInputSchema] = Field(
        default_factory=list,
        description="Deterministically retrieved relevant evidence records",
    )
    processing_state: ProcessingStateSchema = Field(
        default_factory=ProcessingStateSchema,
        description="Duplicate and reimbursement status",
    )


class AIAssessmentResponse(BaseModel):
    """Strict structured output model for AI recovery assessment."""
    model_config = ConfigDict(extra="forbid")

    assessment: AssessmentType = Field(..., description="Assessment classification: CONTRADICTED, SUPPORTED, SILENT, UNCERTAIN")
    claim_supported: bool = Field(..., description="Whether a recovery claim is supported by evidence")
    claim_amount: Optional[Decimal] = Field(default=None, description="Recommended claim amount if recovery supported")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score between 0.0 and 1.0")
    reason: str = Field(..., min_length=1, description="Detailed reasoning explaining the assessment")
    evidence_ids: List[str] = Field(default_factory=list, description="IDs of evidence supporting this assessment")

    @field_validator("reason")
    @classmethod
    def validate_reason_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Reason must be a non-empty string.")
        return v.strip()

    @field_validator("claim_amount")
    @classmethod
    def validate_claim_amount_non_negative(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v < Decimal("0.00"):
            raise ValueError("Claim amount cannot be negative.")
        return v

    @model_validator(mode="after")
    def validate_assessment_invariants(self) -> "AIAssessmentResponse":
        if self.assessment in (AssessmentType.SUPPORTED, AssessmentType.SILENT, AssessmentType.UNCERTAIN):
            if self.claim_supported:
                raise ValueError(f"Assessment '{self.assessment.value}' cannot produce a supported recovery claim.")
            if self.claim_amount is not None and self.claim_amount > Decimal("0.00"):
                raise ValueError(f"Assessment '{self.assessment.value}' cannot have a claim_amount greater than zero.")
        elif self.assessment == AssessmentType.CONTRADICTED:
            if not self.claim_supported and self.claim_amount is not None and self.claim_amount > Decimal("0.00"):
                raise ValueError("When claim_supported is false, claim_amount must be null or zero.")
        return self
