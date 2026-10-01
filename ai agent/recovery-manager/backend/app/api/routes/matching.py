"""API routes for operational evidence matching."""

from typing import List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.database import get_db, SessionLocal
from app.services.job_manager import job_manager
from app.services.matching_service import matching_service

router = APIRouter(tags=["Matching"])


class MatchRequestSchema(BaseModel):
    charge_ids: Optional[List[str]] = Field(default=None, description="Specific charge IDs to match")
    window_days: int = Field(default=30, description="Time window in days around charge_date")
    async_mode: bool = Field(default=False, description="Run as background job")


def _run_matching_background_task(job_id: str, charge_ids: Optional[List[str]], window_days: int, org_id: str):
    db = SessionLocal()
    try:
        job_manager.update_job(job_id, status="running", progress=0.1)
        results = matching_service.match_all_charges(
            db=db,
            charge_ids=charge_ids,
            window_days=window_days,
            org_id=org_id,
        )
        dict_results = [r.to_dict() for r in results]
        job_manager.update_job(
            job_id,
            status="completed",
            progress=1.0,
            result={"matches": dict_results, "total_matched": len(dict_results)},
        )
    except Exception as exc:
        job_manager.update_job(job_id, status="failed", error=str(exc))
    finally:
        db.close()


@router.post("/matching/match-charges")
def match_charges_endpoint(
    payload: MatchRequestSchema,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Match financial charges to operational evidence_events by shipment_id within time window.
    Explicitly reports charges with NO matching evidence.
    Supports asynchronous execution returning job_id immediately.
    """
    org_id = "org_demo_alpha"
    if payload.async_mode:
        job = job_manager.create_job(
            job_type="evidence_matching",
            metadata={"charge_count": len(payload.charge_ids) if payload.charge_ids else "all", "window_days": payload.window_days},
        )
        background_tasks.add_task(
            _run_matching_background_task,
            job.id,
            payload.charge_ids,
            payload.window_days,
            org_id,
        )
        return {"job_id": job.id, "status": "pending", "message": "Matching job started in background."}

    results = matching_service.match_all_charges(
        db=db,
        charge_ids=payload.charge_ids,
        window_days=payload.window_days,
        org_id=org_id,
    )
    return {
        "total": len(results),
        "matches": [r.to_dict() for r in results],
    }


@router.get("/charges/{charge_id}/evidence-events")
def get_charge_evidence_events_endpoint(
    charge_id: str,
    window_days: int = Query(default=30, ge=1, le=365, description="Time window in days around charge_date"),
    db: Session = Depends(get_db),
):
    """
    Retrieve operational evidence_events linked to a specific charge by shipment_id.
    Explicitly flags if no matching evidence was found.
    """
    result = matching_service.match_charge(charge_id=charge_id, db=db, window_days=window_days)
    if result.status == "CHARGE_NOT_FOUND":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Charge '{charge_id}' does not exist.",
        )
    return result.to_dict()
