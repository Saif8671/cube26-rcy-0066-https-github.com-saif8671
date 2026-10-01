"""Pydantic schemas for Phase 9 Recovery Pipeline Orchestration."""

from decimal import Decimal
from typing import List, Literal, Optional
from pydantic import BaseModel, ConfigDict, Field


class PipelineResult(BaseModel):
    """
    Structured outcome returned by the synchronous end-to-end recovery pipeline.
    Aggregates outcomes from Phase 4 (Evidence), Phase 5 (AI), Phase 6 (Rules), and Phase 7 (Claims).
    """
    model_config = ConfigDict(extra="forbid")

    outcome: Literal[
        "CLAIM_CREATED",
        "ALREADY_PROCESSED",
        "NO_CLAIM",
        "HUMAN_REVIEW",
        "BLOCKED",
        "REJECTED_AT_CLAIM_ENGINE",
        "NOT_FOUND",
        "ERROR",
        "INELIGIBLE_INVENTORY_ADJUSTMENT",
    ] = Field(..., description="High-level processing outcome of the orchestrated pipeline")
    charge_id: str = Field(..., description="External marketplace charge identifier")
    claim_id: Optional[str] = Field(default=None, description="External claim tracking ID (CLM-...) if claim created or exists")
    status: Optional[str] = Field(default=None, description="The claims.status value if a claim row exists, or charge status")
    assessment: Optional[str] = Field(default=None, description="Assessment classification (CONTRADICTED, SUPPORTED, SILENT, UNCERTAIN)")
    claim_amount: Optional[Decimal] = Field(default=None, description="Persisted financial claim amount if eligible")
    confidence: Optional[float] = Field(default=None, description="AI confidence score if evaluated")
    reason: str = Field(..., min_length=1, description="Detailed explanatory text for the outcome")
    rule_code: Optional[str] = Field(default=None, description="Rule code if evaluated by rule validator")
    decision: Optional[str] = Field(default=None, description="Rule validation decision (ELIGIBLE, NON_CLAIM, HUMAN_REVIEW, BLOCKED)")
    evidence_count: int = Field(default=0, description="Total count of relevant operational evidence records retrieved")
    evidence_ids: List[str] = Field(default_factory=list, description="Validated evidence IDs linked to the outcome")


class PipelineProcessRequest(BaseModel):
    """Optional request body when triggering pipeline by JSON payload."""
    model_config = ConfigDict(extra="forbid")

    charge_id: str = Field(..., min_length=1, description="External marketplace charge identifier")


class BatchProcessRequest(BaseModel):
    """Request body for batch pipeline processing.

    If charge_ids is provided, processes only those charges.
    If omitted or empty, defaults to all charges with no assessment_log row.
    """
    model_config = ConfigDict(extra="forbid")

    charge_ids: Optional[List[str]] = Field(
        default=None,
        description="Explicit list of charge_ids to process. If null/omitted, processes all unassessed charges.",
    )


class BatchProcessResponse(BaseModel):
    """Response for batch pipeline processing with per-charge results and summary counts."""
    model_config = ConfigDict(extra="forbid")

    results: List[PipelineResult] = Field(
        default_factory=list,
        description="Per-charge pipeline results in processing order",
    )
    succeeded: int = Field(default=0, description="Count of charges that completed pipeline successfully")
    failed: int = Field(default=0, description="Count of charges that encountered errors during processing")
    already_processed: int = Field(default=0, description="Count of charges that were already processed (idempotency)")
    total: int = Field(default=0, description="Total charges attempted")
