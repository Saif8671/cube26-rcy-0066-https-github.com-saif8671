"""Pydantic schemas for Ingestion API requests and responses."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class IngestionErrorDetailSchema(BaseModel):
    """Schema for individual ingestion error."""
    row_index: Optional[int] = None
    identifier: Optional[str] = None
    charge_id: Optional[str] = None
    error_code: str
    reason: str
    reason_code: str


class RejectedRowSchema(BaseModel):
    """Stable, compact representation of a rejected input row."""
    row: int
    charge_id: Optional[str] = None
    reason: str
    reason_code: str


class IngestionResponseSchema(BaseModel):
    """Schema for ingestion result summary."""
    record_type: str
    total_records: int
    inserted_count: int
    failed_count: int
    accepted_count: Optional[int] = None
    rejected_count: Optional[int] = None
    duplicate_count: int
    inserted_ids: List[str] = Field(default_factory=list)
    errors: List[IngestionErrorDetailSchema] = Field(default_factory=list)
    total_rows: int
    accepted: int
    rejected: int
    rejected_rows: List[RejectedRowSchema] = Field(default_factory=list)
    by_reason_code: Dict[str, int] = Field(default_factory=dict)


class IngestionBatchPayload(BaseModel):
    """Optional payload wrapper for direct JSON array ingestion."""
    records: List[Dict[str, Any]]
