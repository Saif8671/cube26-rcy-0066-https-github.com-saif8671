"""API routes for Phase 9 Pipeline Orchestration."""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.pipeline import (
    BatchProcessRequest,
    BatchProcessResponse,
    PipelineProcessRequest,
    PipelineResult,
)
from app.services.pipeline import process_batch_pipeline, process_charge_pipeline

router = APIRouter(prefix="/pipeline", tags=["Pipeline Orchestration"])


@router.post(
    "/process",
    response_model=PipelineResult,
    status_code=status.HTTP_200_OK,
    summary="Synchronously execute recovery pipeline for a charge via JSON payload",
)
def process_pipeline_json_endpoint(
    request: PipelineProcessRequest,
    db: Session = Depends(get_db),
) -> PipelineResult:
    """
    Synchronously runs the full recovery pipeline for a charge:
      Phase 4 (Evidence) -> Phase 5 (AI) -> Phase 6 (Rules) -> Phase 7 (Claims).

    Enforces idempotency: does not re-evaluate already processed charges.
    Blocks until complete and returns real results.
    """
    result = process_charge_pipeline(charge_id=request.charge_id, db=db)
    if result.outcome == "NOT_FOUND":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.reason,
        )
    return result


@router.post(
    "/process/{charge_id}",
    response_model=PipelineResult,
    status_code=status.HTTP_200_OK,
    summary="Synchronously execute recovery pipeline for a charge via path parameter",
)
def process_pipeline_path_endpoint(
    charge_id: str,
    db: Session = Depends(get_db),
) -> PipelineResult:
    """
    Synchronously runs the full recovery pipeline for a charge specified in the path:
      Phase 4 (Evidence) -> Phase 5 (AI) -> Phase 6 (Rules) -> Phase 7 (Claims).
    """
    result = process_charge_pipeline(charge_id=charge_id, db=db)
    if result.outcome == "NOT_FOUND":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.reason,
        )
    return result


@router.post(
    "/process-batch",
    response_model=BatchProcessResponse,
    status_code=status.HTTP_200_OK,
    summary="Batch-process multiple charges through the recovery pipeline",
)
def process_batch_endpoint(
    request: Optional[BatchProcessRequest] = None,
    db: Session = Depends(get_db),
) -> BatchProcessResponse:
    """
    Processes multiple charges sequentially through the full recovery pipeline.

    - If charge_ids is provided in the request body, processes only those charges.
    - If charge_ids is omitted/null, defaults to all charges with no assessment_log row.
    - Error isolation: if one charge fails (AI error, etc.), the batch continues
      and reports that failure per-charge rather than aborting.

    Returns per-charge PipelineResult list plus summary counts
    (succeeded, failed, already_processed, total).
    """
    charge_ids = None
    if request and request.charge_ids:
        charge_ids = request.charge_ids

    return process_batch_pipeline(charge_ids=charge_ids, db=db)

