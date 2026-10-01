"""Pydantic schemas for Phase 6 Deterministic Rule Validation."""

from decimal import Decimal
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.ai.schemas import (
    AIAssessmentRequest,
    AIAssessmentResponse,
    AssessmentType,
    ChargeInputSchema,
    EvidenceInputSchema,
    ProcessingStateSchema,
)


class ValidationDecision(str, Enum):
    """The four deterministic validation decisions under Phase 6 business rules."""
    ELIGIBLE = "ELIGIBLE"
    BLOCKED = "BLOCKED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    NON_CLAIM = "NON_CLAIM"


class RuleValidationRequest(BaseModel):
    """Structured request for Phase 6 deterministic rule validation."""
    model_config = ConfigDict(extra="forbid")

    charge: ChargeInputSchema = Field(
        ...,
        description="Marketplace charge under evaluation",
    )
    assessment: Optional[AssessmentType] = Field(
        default=None,
        description="AI assessment classification (CONTRADICTED, SUPPORTED, SILENT, UNCERTAIN)",
    )
    claim_supported: bool = Field(
        default=False,
        description="Whether a claim is supported by the AI assessment",
    )
    claim_amount: Optional[Decimal] = Field(
        default=None,
        description="Recommended claim amount from AI assessment (allows non-positive for validator inspection)",
    )
    evidence_ids: List[str] = Field(
        default_factory=list,
        description="Evidence IDs referenced by the assessment",
    )
    reason: Optional[str] = Field(
        default=None,
        description="Reasoning text from AI assessment",
    )
    confidence: Optional[float] = Field(
        default=None,
        description="Confidence score from AI assessment",
    )
    evidence: List[EvidenceInputSchema] = Field(
        default_factory=list,
        description="Deterministically retrieved evidence supplied to the assessment",
    )
    supplied_evidence: Optional[List[EvidenceInputSchema]] = Field(
        default=None,
        description="Alternative field name for supplied evidence",
    )
    supplied_evidence_ids: Optional[List[str]] = Field(
        default=None,
        description="Auxiliary/deprecated field; does NOT grant evidence authority. Only request.evidence objects authorize evidence IDs.",
    )
    processing_state: ProcessingStateSchema = Field(
        default_factory=ProcessingStateSchema,
        description="Operational processing flags (duplicate, already_reimbursed)",
    )
    assessment_response: Optional[AIAssessmentResponse] = Field(
        default=None,
        description="Optional full AIAssessmentResponse from Phase 5 to populate assessment fields",
    )

    @model_validator(mode="after")
    def populate_and_validate_fields(self) -> "RuleValidationRequest":
        # If assessment_response is supplied, pull relevant fields from it
        if self.assessment_response is not None:
            if self.assessment is None:
                self.assessment = self.assessment_response.assessment
            self.claim_supported = self.assessment_response.claim_supported
            if self.claim_amount is None:
                self.claim_amount = self.assessment_response.claim_amount
            if not self.evidence_ids:
                self.evidence_ids = list(self.assessment_response.evidence_ids)
            if self.reason is None:
                self.reason = self.assessment_response.reason
            if self.confidence is None:
                self.confidence = self.assessment_response.confidence

        # If supplied_evidence provided and evidence empty, copy it
        if self.supplied_evidence is not None and not self.evidence:
            self.evidence = self.supplied_evidence

        # Ensure assessment is provided
        if self.assessment is None:
            raise ValueError("Field 'assessment' or 'assessment_response' must be provided.")

        return self

    @classmethod
    def from_ai_context(
        cls,
        request: AIAssessmentRequest,
        response: AIAssessmentResponse,
    ) -> "RuleValidationRequest":
        """Construct a validation request directly from Phase 5 request and response."""
        return cls(
            charge=request.charge,
            assessment=response.assessment,
            claim_supported=response.claim_supported,
            claim_amount=response.claim_amount,
            evidence_ids=list(response.evidence_ids),
            reason=response.reason,
            confidence=response.confidence,
            evidence=request.evidence,
            processing_state=request.processing_state,
        )


class RuleValidationResult(BaseModel):
    """Strict structured output model for Phase 6 deterministic rule validation."""
    model_config = ConfigDict(extra="forbid")

    charge_id: Optional[str] = Field(
        default=None,
        description="External marketplace charge identifier",
    )
    assessment: AssessmentType = Field(
        ...,
        description="Assessment classification: CONTRADICTED, SUPPORTED, SILENT, UNCERTAIN",
    )
    eligible_for_recovery: bool = Field(
        ...,
        description="Whether the charge is eligible to proceed toward recovery",
    )
    human_review_required: bool = Field(
        ...,
        description="Whether manual human review is required before any further action",
    )
    claim_amount: Optional[Decimal] = Field(
        default=None,
        description="Validated recovery claim amount if eligible; otherwise None",
    )
    evidence_ids: List[str] = Field(
        default_factory=list,
        description="Validated evidence IDs referenced by the assessment",
    )
    decision: ValidationDecision = Field(
        ...,
        description="Deterministic validation decision: ELIGIBLE, BLOCKED, HUMAN_REVIEW, NON_CLAIM",
    )
    status: ValidationDecision = Field(
        ...,
        description="Compatibility alias for decision (identical value to decision)",
    )
    reason: str = Field(
        ...,
        min_length=1,
        description="Deterministic explanation of the validation outcome",
    )
    rule_code: str = Field(
        ...,
        min_length=1,
        description="Machine-readable rule code identifying the triggered rule",
    )
