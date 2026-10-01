"""API routes for tracking background jobs."""

from fastapi import APIRouter, HTTPException, status
from app.schemas.ingestion import JobResponseSchema
from app.services.job_manager import job_manager

router = APIRouter(prefix="/jobs", tags=["Jobs"])


@router.get("/{job_id}", response_model=JobResponseSchema)
def get_job_endpoint(job_id: str):
    """Retrieve current status and results of a background job."""
    job = job_manager.get_job(job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job '{job_id}' not found.",
        )
    return job.to_dict()
