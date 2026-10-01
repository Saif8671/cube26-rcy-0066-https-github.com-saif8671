"""Pydantic schemas for Phase 8a Read API - Charges."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ChargeSummarySchema(BaseModel):
    """Summary of a marketplace charge with latest claim lifecycle status."""

    charge_id: str = Field(..., description="External fee identifier")
    shipment_id: Optional[str] = Field(None, description="External shipment identifier")
    order_id: Optional[str] = Field(None, description="External order identifier")
    sku: Optional[str] = Field(None, description="Seller SKU")
    asin: Optional[str] = Field(None, description="Marketplace ASIN")
    charge_type: str = Field(..., description="Category or reason for the fee")
    amount: Decimal = Field(..., description="Charge monetary fee amount")
    currency: str = Field(default="USD", description="Currency ISO code")
    charge_date: datetime = Field(..., description="Date/timestamp the marketplace imposed the charge")
    source_report: Optional[str] = Field(None, description="Source report filename or batch identifier")
    data_origin: str = Field(default="judge_data", description="Provenance label for this row")
    status: str = Field(..., description="Processing status of the charge (e.g. PENDING, PROCESSED)")
    latest_claim_status: Optional[str] = Field(
        None,
        description="Status of the latest associated claim if one exists (e.g. READY_FOR_REVIEW, REJECTED), else null",
    )
    latest_claim_id: Optional[str] = Field(
        None,
        description="Display ID of the latest associated claim (e.g. CLM-10091) if one exists, else null",
    )


class ChargeListResponseSchema(BaseModel):
    """Paginated list of charges."""

    total: int = Field(..., ge=0, description="Total matching charges count")
    limit: int = Field(..., ge=1, description="Page limit")
    offset: int = Field(..., ge=0, description="Page offset")
    items: List[ChargeSummarySchema] = Field(default_factory=list, description="Page items")


class ChargeClaimEvidenceItemSchema(BaseModel):
    """Operational evidence linked to a claim on a charge."""

    evidence_id: str = Field(..., description="Business proof tracking ID")
    source_manager: str = Field(..., description="Operational department")
    evidence_type: str = Field(..., description="Classification of evidence")
    evidence_timestamp: datetime = Field(..., description="Operational proof timestamp")
    evidence_content: Dict[str, Any] = Field(default_factory=dict, description="Proof payload findings")


class ChargeClaimDetailSchema(BaseModel):
    """Claim details and associated evidence linked to a charge."""

    claim_id: str = Field(..., description="Claim display ID (e.g. CLM-10091)")
    assessment: str = Field(..., description="Decision outcome: SUPPORTED, CONTRADICTED, SILENT, UNCERTAIN")
    claim_amount: Optional[Decimal] = Field(None, description="Claimed monetary amount")
    confidence: Optional[Decimal] = Field(None, description="Algorithmic confidence score")
    explanation: Optional[str] = Field(None, description="Plain-English dispute rationale")
    status: str = Field(..., description="Claim lifecycle status")
    source_manager: Optional[str] = Field(None, description="Primary evidence source manager")
    created_at: datetime = Field(..., description="Claim creation timestamp")
    evidence: List[ChargeClaimEvidenceItemSchema] = Field(
        default_factory=list,
        description="Operational evidence items linked via claim_evidence",
    )


class ChargeDetailResponseSchema(BaseModel):
    """Full detail view of a single marketplace charge."""

    charge_id: str = Field(..., description="External fee identifier")
    shipment_id: Optional[str] = Field(None, description="External shipment identifier")
    order_id: Optional[str] = Field(None, description="External order identifier")
    sku: Optional[str] = Field(None, description="Seller SKU")
    asin: Optional[str] = Field(None, description="Marketplace ASIN")
    charge_type: str = Field(..., description="Charge category or defect description")
    amount: Decimal = Field(..., description="Charge monetary fee amount")
    currency: str = Field(default="USD", description="Currency ISO code")
    charge_date: datetime = Field(..., description="Marketplace charge timestamp")
    source_report: Optional[str] = Field(None, description="Source report or ingestion batch")
    data_origin: str = Field(default="judge_data", description="Provenance label for this row")
    raw_data: Dict[str, Any] = Field(default_factory=dict, description="Original raw report payload")
    status: str = Field(..., description="Processing status (PENDING, PROCESSED)")
    created_at: datetime = Field(..., description="Record insertion timestamp")
    claim: Optional[ChargeClaimDetailSchema] = Field(
        None,
        description="Associated claim with full claim_evidence detail, or null if no claim exists",
    )
    claim_status_explanation: str = Field(
        ...,
        description="Plain-English explanation of charge claim status derived from DB state",
    )
    evidence_retrieval_persisted: bool = Field(
        default=False,
        description="Flag indicating whether evidence matching was persisted (only true via claim_evidence)",
    )
    persistence_notes: Optional[str] = Field(
        None,
        description="Auditing notes regarding evidence persistence for non-claimed charges",
    )
