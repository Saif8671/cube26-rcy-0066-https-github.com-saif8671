"""Pydantic schemas for Phase 4 deterministic Evidence Engine."""

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class EvidenceMatchSchema(BaseModel):
    """Schema representing an operational evidence record matched to a charge."""

    evidence_id: str = Field(..., description="External business proof tracking ID (e.g. EVD-PREP-8821)")
    matched_by: str = Field(..., description="Highest-priority matching key ('shipment_id', 'order_id', 'sku', 'asin')")
    match_value: str = Field(..., description="The exact identifier value matched upon")
    source_manager: str = Field(..., description="Operational department that generated the proof (e.g. Prep, Receiving, Pack)")
    evidence_type: str = Field(..., description="Classification of evidence (e.g. packaging_check, scale_audit)")
    evidence_timestamp: datetime = Field(..., description="Exact operational proof timestamp")
    evidence_content: Dict[str, Any] = Field(..., description="Recorded proof payload / findings")
    matched_keys: Optional[List[str]] = Field(
        default=None,
        description="All identifier keys connecting this evidence record to the charge in priority order",
    )


class ChargeEvidenceResponseSchema(BaseModel):
    """Schema representing the deterministic evidence retrieval result for a charge."""

    charge_id: str = Field(..., description="Marketplace charge external identifier")
    candidate_count: int = Field(..., ge=0, description="Total candidate evidence records retrieved before filtering")
    relevant_count: int = Field(..., ge=0, description="Total verified relevant evidence records retained after filtering")
    evidence: List[EvidenceMatchSchema] = Field(
        default_factory=list,
        description="Deterministically ordered list of relevant evidence matches",
    )


class EvidenceRecordSchema(BaseModel):
    """Schema representing an operational evidence record stored in the database."""

    evidence_id: str = Field(..., description="External business proof tracking ID (e.g. EVD-PREP-8821)")
    source_manager: str = Field(..., description="Operational department that generated proof (e.g. Prep, Receiving, Pack)")
    shipment_id: Optional[str] = Field(None, description="External shipment identifier")
    order_id: Optional[str] = Field(None, description="External order identifier")
    sku: Optional[str] = Field(None, description="Inspected SKU")
    asin: Optional[str] = Field(None, description="Inspected ASIN")
    evidence_type: str = Field(..., description="Classification of evidence (e.g. packaging_check, scale_audit)")
    evidence_content: Dict[str, Any] = Field(default_factory=dict, description="Recorded proof payload / findings")
    evidence_timestamp: datetime = Field(..., description="Exact operational proof timestamp")
    created_at: datetime = Field(..., description="Record insertion timestamp")
    data_origin: str = Field(default="judge_data", description="Provenance label for this row")


class EvidenceListResponseSchema(BaseModel):
    """Paginated list of operational evidence records."""

    total: int = Field(..., ge=0, description="Total count of matching evidence records")
    limit: int = Field(..., ge=1, description="Page limit")
    offset: int = Field(..., ge=0, description="Page offset")
    items: List[EvidenceRecordSchema] = Field(default_factory=list, description="Page items")
