"""Pydantic schemas for Phase 8a Read API - Claims and Traceability."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ClaimSummarySchema(BaseModel):
    """Summary of a dispute claim."""

    claim_id: str = Field(..., description="External tracking ID (e.g. CLM-10091)")
    charge_id: str = Field(..., description="External charge identifier (e.g. CHG-FBA-8901)")
    assessment: str = Field(..., description="Assessment decision: CONTRADICTED, SUPPORTED, SILENT, UNCERTAIN")
    claim_amount: Optional[Decimal] = Field(None, description="Disputed recovery amount")
    status: str = Field(..., description="Lifecycle status (READY_FOR_REVIEW, REJECTED, etc.)")
    confidence: Optional[Decimal] = Field(None, description="Algorithmic confidence score (0.0 to 1.0)")
    source_manager: Optional[str] = Field(None, description="Primary warehouse/operations source manager")
    created_at: datetime = Field(..., description="Claim creation timestamp")


class ClaimListResponseSchema(BaseModel):
    """Paginated list of claims."""

    total: int = Field(..., ge=0, description="Total matching claims count")
    limit: int = Field(..., ge=1, description="Page limit")
    offset: int = Field(..., ge=0, description="Page offset")
    items: List[ClaimSummarySchema] = Field(default_factory=list, description="Page items")


class TraceableEvidenceItemSchema(BaseModel):
    """Evidence item in the end-to-end traceability chain."""

    evidence_id: str = Field(..., description="Operational proof tracking ID")
    source_manager: str = Field(..., description="Operational department")
    evidence_type: str = Field(..., description="Classification of evidence")
    evidence_timestamp: datetime = Field(..., description="Exact operational proof timestamp")
    evidence_content: Dict[str, Any] = Field(default_factory=dict, description="Proof payload findings")


class ClaimTraceabilityResponseSchema(BaseModel):
    """Full claim detail with complete traceability chain from claim -> charge -> shipment/order/sku -> evidence."""

    claim_id: str = Field(..., description="Claim tracking ID (e.g. CLM-10091)")
    assessment: str = Field(..., description="Decision outcome")
    claim_amount: Optional[Decimal] = Field(None, description="Claim monetary amount")
    confidence: Optional[Decimal] = Field(None, description="Confidence score")
    explanation: Optional[str] = Field(None, description="Dispute explanation")
    status: str = Field(..., description="Claim lifecycle status")
    source_manager: Optional[str] = Field(None, description="Claim source manager")
    created_at: datetime = Field(..., description="Claim creation timestamp")

    # Charge traceability
    charge_id: str = Field(..., description="Underlying charge identifier")
    charge_type: str = Field(..., description="Charge category / defect")
    charge_amount: Decimal = Field(..., description="Charge fee amount")
    charge_currency: str = Field(..., description="Fee currency")
    charge_date: datetime = Field(..., description="Fee assessment timestamp")
    charge_status: str = Field(..., description="Charge processing status")
    sku: Optional[str] = Field(None, description="Product SKU")
    asin: Optional[str] = Field(None, description="Marketplace ASIN")
    shipment_id: Optional[str] = Field(None, description="External shipment container ID")
    order_id: Optional[str] = Field(None, description="External order transaction ID")

    # Operational evidence join
    evidence: List[TraceableEvidenceItemSchema] = Field(
        default_factory=list,
        description="Complete operational evidence items linked via claim_evidence",
    )
