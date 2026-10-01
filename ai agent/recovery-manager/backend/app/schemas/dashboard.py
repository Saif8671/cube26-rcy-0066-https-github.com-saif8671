"""Pydantic schemas for Phase 8a Read API - Dashboard Metrics and Pending Review."""

from decimal import Decimal
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from app.schemas.charges_read import ChargeSummarySchema


class DashboardMetricsResponseSchema(BaseModel):
    """Real-time operational dashboard metrics computed via direct database aggregation."""

    total_charges: int = Field(..., ge=0, description="Total number of charges in the database")
    total_potential_recovery: Decimal = Field(
        ...,
        description="Sum of claim_amount where status = 'READY_FOR_REVIEW' and assessment = 'CONTRADICTED'",
    )
    total_claims: int = Field(..., ge=0, description="Total number of claims records in the database")
    claims_by_assessment: Dict[str, int] = Field(
        ...,
        description="Counts of evaluations grouped by assessment type (CONTRADICTED, SUPPORTED, SILENT, UNCERTAIN) from assessment_log",
    )
    claims_by_status: Dict[str, int] = Field(
        ...,
        description="Counts of claims grouped by status (READY_FOR_REVIEW, DUPLICATE, ALREADY_REIMBURSED, REJECTED, APPROVED)",
    )
    unprocessed_charges_count: int = Field(
        ...,
        ge=0,
        description="Charges with no assessment_log row (never evaluated by the pipeline)",
    )
    processed_no_claim_charges_count: int = Field(
        ...,
        ge=0,
        description="Charges evaluated in assessment_log that resulted in no claims row (e.g. SUPPORTED, SILENT, UNCERTAIN)",
    )
    persistence_gap_notice: Optional[str] = Field(
        None,
        description="Deprecated persistence gap notice, null now that assessment_log audit trail is active",
    )
    seed_charges: int = Field(default=0, ge=0)
    seed_claims: int = Field(default=0, ge=0)


class PendingReviewChargesResponseSchema(BaseModel):
    """Charges pending review (UNCERTAIN assessment with no claims row)."""

    total: int = Field(..., ge=0, description="Total charges pending human review")
    items: List[ChargeSummarySchema] = Field(default_factory=list, description="List of charges pending review")
    persistence_gap_notice: Optional[str] = Field(
        None,
        description="Deprecated persistence gap notice, null now that assessment_log audit trail is active",
    )
