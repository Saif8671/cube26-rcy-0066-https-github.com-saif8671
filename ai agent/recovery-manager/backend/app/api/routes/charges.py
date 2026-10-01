"""API routes for Phase 8a Read API - Charges."""

from typing import List, Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session, joinedload

from app.core.database import current_org, get_db
from app.models.charge import Charge
from app.models.claim import Claim
from app.models.claim_evidence import ClaimEvidence
from app.models.evidence import Evidence
from app.models.order import Order
from app.models.shipment import Shipment
from app.models.assessment_log import AssessmentLog
from app.models.override import Override
from app.models.pipeline_error import PipelineError
from app.claims.service import ClaimEngine
from app.schemas.charges_read import (
    ChargeClaimDetailSchema,
    ChargeClaimEvidenceItemSchema,
    ChargeDetailResponseSchema,
    ChargeListResponseSchema,
    ChargeSummarySchema,
)
from app.schemas.dashboard import PendingReviewChargesResponseSchema
from app.schemas.override import ChargeOverrideRequest, ChargeOverrideResponse
from app.schemas.pipeline import PipelineResult
from app.schemas.pipeline_error import FailedPendingChargeItem, FailedPendingChargesResponse
from app.services.evidence_engine import evidence_engine
from app.services.pipeline import process_charge_pipeline

router = APIRouter(prefix="/charges", tags=["Charges"])


@router.get(
    "",
    response_model=ChargeListResponseSchema,
    summary="Get paginated list of marketplace charges",
)
def get_charges_endpoint(
    limit: int = Query(default=100, ge=1, le=1000, description="Page size limit"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by charge processing status"),
    data_origin: Optional[str] = Query(default=None, description="Filter by row provenance"),
    db: Session = Depends(get_db),
) -> ChargeListResponseSchema:
    """
    Retrieve paginated list of marketplace charges.
    Includes external shipment_id, order_id, and latest associated claim's status.
    """
    # 1. Total count query
    count_stmt = select(func.count(Charge.id))
    if status_filter:
        count_stmt = count_stmt.where(Charge.status == status_filter)
    count_stmt = count_stmt.where(Charge.data_origin == (data_origin.strip() if data_origin else "judge_data"))
    total = db.scalar(count_stmt) or 0

    # 2. Window subquery to rank claims by charge_id, ordering by created_at DESC
    ranked_claims = (
        select(
            Claim.id.label("claim_row_id"),
            Claim.claim_id,
            Claim.charge_id,
            Claim.status.label("claim_status"),
            Claim.created_at,
            func.row_number()
            .over(
                partition_by=Claim.charge_id,
                order_by=(desc(Claim.created_at), desc(Claim.id)),
            )
            .label("rn"),
        )
        .subquery()
    )

    # 3. Main query joining charges, shipments, orders, and latest claim
    query = (
        select(
            Charge.charge_id,
            Shipment.shipment_id.label("ext_shipment_id"),
            Order.order_id.label("ext_order_id"),
            Charge.sku,
            Charge.asin,
            Charge.charge_type,
            Charge.amount,
            Charge.currency,
            Charge.charge_date,
            Charge.source_report,
            Charge.data_origin,
            Charge.status,
            ranked_claims.c.claim_status.label("latest_claim_status"),
            ranked_claims.c.claim_id.label("latest_claim_id"),
        )
        .outerjoin(Shipment, Charge.shipment_id == Shipment.id)
        .outerjoin(Order, Charge.order_id == Order.id)
        .outerjoin(
            ranked_claims,
            (ranked_claims.c.charge_id == Charge.id) & (ranked_claims.c.rn == 1),
        )
    )

    if status_filter:
        query = query.where(Charge.status == status_filter)
    query = query.where(Charge.data_origin == (data_origin.strip() if data_origin else "judge_data"))

    query = query.order_by(desc(Charge.charge_date), desc(Charge.created_at)).limit(limit).offset(offset)
    rows = db.execute(query).mappings().all()

    items = [
        ChargeSummarySchema(
            charge_id=row["charge_id"],
            shipment_id=row["ext_shipment_id"],
            order_id=row["ext_order_id"],
            sku=row["sku"],
            asin=row["asin"],
            charge_type=row["charge_type"],
            amount=row["amount"],
            currency=row["currency"],
            charge_date=row["charge_date"],
            source_report=row["source_report"],
            data_origin=row["data_origin"],
            status=row["status"],
            latest_claim_status=row["latest_claim_status"],
            latest_claim_id=row["latest_claim_id"],
        )
        for row in rows
    ]

    return ChargeListResponseSchema(
        total=total,
        limit=limit,
        offset=offset,
        items=items,
    )


@router.get(
    "/pending-review",
    response_model=PendingReviewChargesResponseSchema,
    summary="Get charges pending supervisor or human review",
)
def get_pending_review_charges_endpoint(
    db: Session = Depends(get_db),
) -> PendingReviewChargesResponseSchema:
    """
    Retrieve charges whose evaluation is pending human review:
    Queries assessment_log for assessment = 'UNCERTAIN' rows with no corresponding claims row.
    """
    query = (
        select(
            Charge.charge_id,
            Shipment.shipment_id.label("ext_shipment_id"),
            Order.order_id.label("ext_order_id"),
            Charge.sku,
            Charge.asin,
            Charge.charge_type,
            Charge.amount,
            Charge.currency,
            Charge.charge_date,
            Charge.source_report,
            Charge.data_origin,
            Charge.status,
        )
        .join(AssessmentLog, AssessmentLog.charge_id == Charge.id)
        .outerjoin(Shipment, Charge.shipment_id == Shipment.id)
        .outerjoin(Order, Charge.order_id == Order.id)
        .where(
            AssessmentLog.assessment == "UNCERTAIN",
            ~Charge.id.in_(select(Claim.charge_id)),
        )
        .distinct()
        .order_by(desc(Charge.charge_date))
    )

    rows = db.execute(query).mappings().all()

    items = [
        ChargeSummarySchema(
            charge_id=row["charge_id"],
            shipment_id=row["ext_shipment_id"],
            order_id=row["ext_order_id"],
            sku=row["sku"],
            asin=row["asin"],
            charge_type=row["charge_type"],
            amount=row["amount"],
            currency=row["currency"],
            charge_date=row["charge_date"],
            source_report=row["source_report"],
            data_origin=row["data_origin"],
            status=row["status"],
            latest_claim_status=None,
            latest_claim_id=None,
        )
        for row in rows
    ]

    return PendingReviewChargesResponseSchema(
        total=len(items),
        items=items,
        persistence_gap_notice=None,
    )


@router.get(
    "/failed-pending",
    response_model=FailedPendingChargesResponse,
    summary="Get charges with failed pipeline executions pending review/retry",
)
def get_failed_pending_charges_endpoint(
    db: Session = Depends(get_db),
) -> FailedPendingChargesResponse:
    """
    Engineering Rule 3 (Fail Open):
    Retrieve pipeline executions that failed due to model/timeout/persistence errors.
    Allows operators to discover, audit, and trigger retries on failed runs.
    """
    stmt = (
        select(PipelineError, Charge)
        .join(Charge, PipelineError.charge_id == Charge.id)
        .where(PipelineError.status == "pending")
        .order_by(desc(PipelineError.created_at))
    )
    rows = db.execute(stmt).all()
    items = []
    for err, chg in rows:
        items.append(
            FailedPendingChargeItem(
                id=str(err.id),
                charge_id=chg.charge_id,
                unit_id=chg.unit_id,
                fnsku=chg.fnsku,
                charge_type=chg.charge_type,
                amount=float(chg.amount) if chg.amount is not None else None,
                currency=chg.currency,
                stage=err.stage,
                error_reason=err.error_reason,
                status=err.status,
                created_at=err.created_at.isoformat() if err.created_at else "",
            )
        )
    return FailedPendingChargesResponse(total=len(items), items=items)


@router.get(
    "/{charge_id}",
    response_model=ChargeDetailResponseSchema,
    summary="Get full charge detail including associated claim and evidence",
)
def get_charge_detail_endpoint(
    charge_id: str,
    db: Session = Depends(get_db),
) -> ChargeDetailResponseSchema:
    """
    Retrieve full charge detail for a specific marketplace charge.
    Includes associated claim and claim_evidence if a claim was generated.
    If no claim exists, provides a plain-English explanation derived from real DB state.
    """
    clean_id = charge_id.strip()

    # Find charge by external charge_id or fallback UUID
    stmt = (
        select(Charge)
        .options(joinedload(Charge.shipment), joinedload(Charge.order))
        .where(Charge.charge_id == clean_id, Charge.org_id == current_org(db))
    )
    charge = db.scalars(stmt).first()

    if not charge:
        try:
            val_uuid = uuid.UUID(clean_id)
            uuid_stmt = (
                select(Charge)
                .options(joinedload(Charge.shipment), joinedload(Charge.order))
                .where(Charge.id == val_uuid)
            )
            charge = db.scalars(uuid_stmt).first()
        except (ValueError, TypeError, AttributeError):
            pass

    if not charge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Charge with identifier '{charge_id}' not found.",
        )

    # Resolve external shipment and order strings
    ext_shipment_id = charge.shipment.shipment_id if charge.shipment else None
    ext_order_id = charge.order.order_id if charge.order else None

    # Find latest associated claim if one exists
    claim_stmt = (
        select(Claim)
        .where(Claim.charge_id == charge.id)
        .order_by(desc(Claim.created_at))
    )
    claim_model = db.scalars(claim_stmt).first()

    claim_detail: Optional[ChargeClaimDetailSchema] = None
    claim_status_explanation: str

    if claim_model:
        # Fetch associated evidence linked through claim_evidence
        ev_stmt = (
            select(
                Evidence.evidence_id,
                Evidence.source_manager,
                Evidence.evidence_type,
                Evidence.evidence_timestamp,
                Evidence.evidence_content,
            )
            .join(ClaimEvidence, ClaimEvidence.evidence_id == Evidence.id)
            .where(ClaimEvidence.claim_id == claim_model.id)
            .order_by(Evidence.evidence_timestamp)
        )
        ev_rows = db.execute(ev_stmt).mappings().all()

        claim_evidence_items = [
            ChargeClaimEvidenceItemSchema(
                evidence_id=r["evidence_id"],
                source_manager=r["source_manager"],
                evidence_type=r["evidence_type"],
                evidence_timestamp=r["evidence_timestamp"],
                evidence_content=r["evidence_content"] or {},
            )
            for r in ev_rows
        ]

        claim_detail = ChargeClaimDetailSchema(
            claim_id=claim_model.claim_id,
            assessment=claim_model.assessment,
            claim_amount=claim_model.claim_amount,
            confidence=claim_model.confidence,
            explanation=claim_model.explanation,
            status=claim_model.status,
            source_manager=claim_model.source_manager,
            created_at=claim_model.created_at,
            evidence=claim_evidence_items,
        )

        claim_status_explanation = (
            f"Claim '{claim_model.claim_id}' exists with assessment '{claim_model.assessment}' "
            f"and status '{claim_model.status}'."
        )
    else:
        # Check assessment_log for evaluations that did not produce a claims row
        log_stmt = (
            select(AssessmentLog)
            .where(AssessmentLog.charge_id == charge.id)
            .order_by(desc(AssessmentLog.created_at))
        )
        log_model = db.scalars(log_stmt).first()
        if log_model:
            claim_status_explanation = (
                f"Evaluated as {log_model.assessment} (no claim generated). Rationale: {log_model.reason or 'None'}"
            )
        elif charge.status == "PENDING":
            claim_status_explanation = "Not yet processed — charge is in PENDING status."
        elif charge.status == "PROCESSED":
            claim_status_explanation = (
                "No claim record — charge was evaluated through the recovery pipeline and resulted in no claim."
            )
        else:
            claim_status_explanation = f"No claim record found for charge with status '{charge.status}'."

    persistence_notes = (
        "Operational evidence matching results and assessment audits are tracked in assessment_log. "
        "Formal claim records are only created when a charge is eligible for recovery or blocked."
    )

    return ChargeDetailResponseSchema(
        charge_id=charge.charge_id,
        shipment_id=ext_shipment_id,
        order_id=ext_order_id,
        sku=charge.sku,
        asin=charge.asin,
        charge_type=charge.charge_type,
        amount=charge.amount,
        currency=charge.currency,
        charge_date=charge.charge_date,
        source_report=charge.source_report,
        raw_data=charge.raw_data or {},
        status=charge.status,
        created_at=charge.created_at,
        claim=claim_detail,
        claim_status_explanation=claim_status_explanation,
        evidence_retrieval_persisted=bool(claim_detail and claim_detail.evidence),
        persistence_notes=persistence_notes,
    )


@router.post(
    "/{charge_id}/process",
    response_model=PipelineResult,
    status_code=status.HTTP_200_OK,
    summary="Synchronously execute end-to-end recovery evaluation pipeline for a charge",
)
def process_charge_endpoint(
    charge_id: str,
    db: Session = Depends(get_db),
) -> PipelineResult:
    """
    Synchronously runs:
      1. Deterministic Evidence Retrieval (Phase 4)
      2. AI Reasoning (Phase 5)
      3. Deterministic Rule Validation (Phase 6)
      4. Claim Engine Persistence & Audit Logger (Phase 7)

    Enforces idempotency on assessment_log and claims tables.
    Blocks until finished and returns real results.
    """
    result = process_charge_pipeline(charge_id=charge_id, db=db)
    if result.outcome == "NOT_FOUND":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=result.reason,
        )
    return result


@router.post(
    "/{charge_id}/override",
    response_model=ChargeOverrideResponse,
    status_code=status.HTTP_200_OK,
    summary="Capture human operator override disagreeing with the agent",
)
def override_charge_endpoint(
    charge_id: str,
    body: ChargeOverrideRequest,
    db: Session = Depends(get_db),
) -> ChargeOverrideResponse:
    """
    Honesty Rule (Overrides are data):
    When an operator disagrees with the agent, capture the original verdict,
    the new verdict and a reason. Never discard those rows silently.

    1. Reads the charge's current assessment and claim status.
    2. Writes an immutable audit row to 'overrides'.
    3. Applies practical effect:
       - If overriding UNCERTAIN to approve a claim: creates claim via ClaimEngine
         with a note it was human-originated.
       - If overriding a claim to reject: updates claims.status to REJECTED and records why.
    """
    charge = evidence_engine.find_charge(charge_id.strip(), db)
    if not charge:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Charge with identifier '{charge_id}' not found.",
        )

    # 1. Fetch current assessment and claim status
    claim_stmt = select(Claim).where(Claim.charge_id == charge.id).order_by(desc(Claim.created_at))
    existing_claim = db.scalars(claim_stmt).first()

    assessment_stmt = select(AssessmentLog).where(AssessmentLog.charge_id == charge.id).order_by(desc(AssessmentLog.created_at))
    latest_assessment = db.scalars(assessment_stmt).first()

    original_assessment = existing_claim.assessment if existing_claim else (latest_assessment.assessment if latest_assessment else None)
    original_status = existing_claim.status if existing_claim else charge.status

    norm_verdict = body.new_verdict.strip().upper()
    active_claim_id = existing_claim.id if existing_claim else None
    active_claim_ext_id = existing_claim.claim_id if existing_claim else None

    # 2. Apply practical effects reusing existing ClaimEngine plumbing
    claim_engine = ClaimEngine(db=db)
    is_approving = norm_verdict in ("APPROVED", "CLAIM_ELIGIBLE", "APPROVE", "CLAIM_CREATED", "SUPPORTED")
    is_rejecting = norm_verdict in ("REJECTED", "NOT_ELIGIBLE", "REJECT")

    if is_approving:
        if existing_claim:
            existing_claim.status = "READY_FOR_REVIEW"
            existing_claim.explanation = f"Human operator override ({body.reviewer_id}): {body.reason}"
            charge.status = "PROCESSED"
            action_taken = f"Updated existing claim {existing_claim.claim_id} to READY_FOR_REVIEW"
        else:
            # Overriding UNCERTAIN or unasserted charge to create human-originated claim
            new_claim = claim_engine.create_human_override_claim(
                charge=charge,
                reason=body.reason,
                reviewer_id=body.reviewer_id,
                new_verdict=body.new_verdict,
            )
            active_claim_id = new_claim.id
            active_claim_ext_id = new_claim.claim_id
            action_taken = f"Created human-originated claim {new_claim.claim_id}"
    elif is_rejecting:
        if existing_claim:
            existing_claim.status = "REJECTED"
            existing_claim.explanation = f"{existing_claim.explanation} | Human override REJECTED ({body.reviewer_id}): {body.reason}"
            charge.status = "PROCESSED"
            action_taken = f"Updated claim {existing_claim.claim_id} status to REJECTED"
        else:
            charge.status = "PROCESSED"
            action_taken = "Charge recorded as rejected without claim creation"
    else:
        action_taken = f"Recorded verdict override to {body.new_verdict}"

    # 3. Insert append-only audit row into overrides table
    override_record = Override(
        charge_id=charge.id,
        claim_id=active_claim_id,
        org_id=charge.org_id,
        original_assessment=original_assessment,
        original_status=original_status,
        new_verdict=body.new_verdict,
        reason=body.reason,
        reviewer_id=body.reviewer_id,
    )
    db.add(override_record)
    db.commit()
    db.refresh(override_record)

    return ChargeOverrideResponse(
        id=str(override_record.id),
        charge_id=charge.charge_id,
        claim_id=active_claim_ext_id,
        org_id=override_record.org_id,
        original_assessment=original_assessment,
        original_status=original_status,
        new_verdict=override_record.new_verdict,
        reason=override_record.reason,
        reviewer_id=override_record.reviewer_id,
        created_at=override_record.created_at.isoformat() if override_record.created_at else "",
        action_taken=action_taken,
    )
