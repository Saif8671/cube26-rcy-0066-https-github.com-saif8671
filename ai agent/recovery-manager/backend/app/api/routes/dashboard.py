"""API routes for Phase 8a Read API - Dashboard Metrics."""

from decimal import Decimal
from typing import Dict
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.database import current_org, get_db
from app.models.charge import Charge
from app.models.claim import Claim
from app.models.assessment_log import AssessmentLog
from app.schemas.dashboard import DashboardMetricsResponseSchema

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get(
    "/metrics",
    response_model=DashboardMetricsResponseSchema,
    summary="Get aggregated dashboard recovery metrics computed at request time",
)
def get_dashboard_metrics_endpoint(
    data_origin: str = Query(default="judge_data", description="Row provenance used for dashboard metrics"),
    db: Session = Depends(get_db),
) -> DashboardMetricsResponseSchema:
    """
    Retrieve real-time operational dashboard metrics computed directly from PostgreSQL tables:
    - total charges
    - total potential recovery (sum of claim_amount where status = 'READY_FOR_REVIEW' and assessment = 'CONTRADICTED')
    - count of evaluations by assessment outcome (from assessment_log)
    - count of claims by lifecycle status
    - count of truly unprocessed charges (status = PENDING and no claims row)
    - count of charges processed through pipeline that produced no claim row
    """
    # 1. Total charges
    org_id = current_org(db)
    selected_origin = data_origin.strip() or "judge_data"
    selected_charge_filter = (Charge.org_id == org_id, Charge.data_origin == selected_origin)
    selected_claim_filter = (Claim.org_id == org_id, Claim.data_origin == selected_origin)
    total_charges = db.scalar(select(func.count(Charge.id)).where(*selected_charge_filter)) or 0
    seed_charges = db.scalar(select(func.count(Charge.id)).where(Charge.org_id == org_id, Charge.data_origin == "seed_example")) or 0

    # 2. Total claims
    total_claims = db.scalar(select(func.count(Claim.id)).where(*selected_claim_filter)) or 0
    seed_claims = db.scalar(select(func.count(Claim.id)).where(Claim.org_id == org_id, Claim.data_origin == "seed_example")) or 0

    # 3. Total potential recovery
    # Claims in 'READY_FOR_REVIEW' and 'CONTRADICTED' represent actionable recovery amounts awaiting supervisor
    # or dispute filing. Ineligible/non-claim outcomes carry NULL claim_amount.
    potential_sum_stmt = select(
        func.coalesce(func.sum(Claim.claim_amount), Decimal("0.00"))
    ).where(
        Claim.status == "READY_FOR_REVIEW",
        Claim.assessment == "CONTRADICTED",
        Claim.org_id == org_id,
        Claim.data_origin == selected_origin,
    )
    total_potential_recovery = db.scalar(potential_sum_stmt) or Decimal("0.00")

    # 4. Claims by assessment type computed from assessment_log (only real AI evaluations where confidence IS NOT NULL)
    # Short-circuited BLOCKED rows (confidence is NULL) are excluded from the assessment breakdown
    assessment_query = (
        select(AssessmentLog.assessment, func.count(AssessmentLog.id))
        .join(Charge, AssessmentLog.charge_id == Charge.id)
        .where(AssessmentLog.confidence.is_not(None), AssessmentLog.org_id == org_id, Charge.data_origin == selected_origin)
        .group_by(AssessmentLog.assessment)
    )
    raw_assessments = dict(db.execute(assessment_query).all())
    claims_by_assessment: Dict[str, int] = {
        "SUPPORTED": raw_assessments.get("SUPPORTED", 0),
        "CONTRADICTED": raw_assessments.get("CONTRADICTED", 0),
        "SILENT": raw_assessments.get("SILENT", 0),
        "UNCERTAIN": raw_assessments.get("UNCERTAIN", 0),
    }
    # Include any other distinct values if present
    for k, v in raw_assessments.items():
        if k not in claims_by_assessment:
            claims_by_assessment[k] = v

    # 5. Claims by status (READY_FOR_REVIEW, DUPLICATE, ALREADY_REIMBURSED, REJECTED, APPROVED)
    status_query = select(Claim.status, func.count(Claim.id)).where(*selected_claim_filter).group_by(Claim.status)
    raw_statuses = dict(db.execute(status_query).all())
    claims_by_status: Dict[str, int] = {
        "READY_FOR_REVIEW": raw_statuses.get("READY_FOR_REVIEW", 0),
        "DUPLICATE": raw_statuses.get("DUPLICATE", 0),
        "ALREADY_REIMBURSED": raw_statuses.get("ALREADY_REIMBURSED", 0),
        "REJECTED": raw_statuses.get("REJECTED", 0),
        "APPROVED": raw_statuses.get("APPROVED", 0),
    }
    for k, v in raw_statuses.items():
        if k not in claims_by_status:
            claims_by_status[k] = v

    # 6. Unprocessed charges count (never evaluated by pipeline - no assessment_log row)
    unprocessed_stmt = select(func.count(Charge.id)).where(
        Charge.org_id == org_id,
        Charge.data_origin == selected_origin,
        ~Charge.id.in_(select(AssessmentLog.charge_id)),
    )
    unprocessed_charges_count = db.scalar(unprocessed_stmt) or 0

    # 7. Processed charges resulting in no claim row (evaluated in assessment_log but produced no claims row)
    processed_no_claim_stmt = select(func.count(Charge.id)).where(
        Charge.org_id == org_id,
        Charge.data_origin == selected_origin,
        Charge.id.in_(select(AssessmentLog.charge_id)),
        ~Charge.id.in_(select(Claim.charge_id)),
    )
    processed_no_claim_charges_count = db.scalar(processed_no_claim_stmt) or 0

    return DashboardMetricsResponseSchema(
        total_charges=total_charges,
        total_potential_recovery=total_potential_recovery,
        total_claims=total_claims,
        claims_by_assessment=claims_by_assessment,
        claims_by_status=claims_by_status,
        unprocessed_charges_count=unprocessed_charges_count,
        processed_no_claim_charges_count=processed_no_claim_charges_count,
        persistence_gap_notice=None,
        seed_charges=seed_charges,
        seed_claims=seed_claims,
    )
