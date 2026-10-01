"""API routes for Phase 7 Claim Engine & Phase 8a Claims Read Layer."""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, select, text
from sqlalchemy.orm import Session

from app.claims.exceptions import ClaimIntegrityError, ClaimTransactionError
from app.claims.schemas import ClaimEngineRequest, ClaimEngineResult
from app.claims.service import ClaimEngine
from app.core.database import get_db
from app.models.charge import Charge
from app.models.claim import Claim
from app.schemas.claims_read import (
    ClaimListResponseSchema,
    ClaimSummarySchema,
    ClaimTraceabilityResponseSchema,
    TraceableEvidenceItemSchema,
)

router = APIRouter(prefix="/claims", tags=["Claims Engine"])


@router.post(
    "/process",
    response_model=ClaimEngineResult,
    status_code=status.HTTP_200_OK,
    summary="Process recovery assessment & rule results to evaluate and persist claims",
)
def process_claim_endpoint(
    request: ClaimEngineRequest,
    db: Session = Depends(get_db),
) -> ClaimEngineResult:
    """
    Process recovery evaluation and persist claims/claim_evidence records where applicable.

    - Idempotent on charge_id across all claims row statuses.
    - Atomically persists eligible claims and claim_evidence join rows.
    - Persists non-financial claim audit rows for BLOCKED or REJECTED outcomes.
    - Zero rows created for NON_CLAIM or HUMAN_REVIEW.
    """
    engine = ClaimEngine(db=db)
    try:
        return engine.process_claim(
            charge_id=request.charge_id,
            validation_result=request.validation_result,
            assessment_response=request.assessment_response,
            evidence=request.evidence,
            processing_state=request.processing_state,
        )
    except ClaimIntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ClaimTransactionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="A database transaction error occurred while persisting the claim.",
        ) from exc


@router.get(
    "",
    response_model=ClaimListResponseSchema,
    summary="Get paginated list of claims with optional status filter",
)
def get_claims_endpoint(
    limit: int = Query(default=100, ge=1, le=1000, description="Page size limit"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    status_filter: Optional[str] = Query(default=None, alias="status", description="Filter by claim lifecycle status"),
    data_origin: Optional[str] = Query(default=None, description="Filter by row provenance; defaults to judge_data"),
    db: Session = Depends(get_db),
) -> ClaimListResponseSchema:
    """
    Retrieve paginated list of claims.
    Includes external charge_id, assessment, claim_amount, status, confidence, and source_manager.
    """
    # Count total
    origin = data_origin.strip() if data_origin else "judge_data"
    count_stmt = select(func.count(Claim.id)).where(Claim.data_origin == origin)
    if status_filter:
        count_stmt = count_stmt.where(Claim.status == status_filter)
    total = db.scalar(count_stmt) or 0

    # Query claims joined with charges to retrieve external charge_id
    query = (
        select(
            Claim.claim_id,
            Charge.charge_id,
            Claim.assessment,
            Claim.claim_amount,
            Claim.status,
            Claim.confidence,
            Claim.source_manager,
            Claim.created_at,
        )
        .join(Charge, Claim.charge_id == Charge.id)
    )

    query = query.where(Claim.data_origin == origin)
    if status_filter:
        query = query.where(Claim.status == status_filter)

    query = query.order_by(desc(Claim.created_at), desc(Claim.id)).limit(limit).offset(offset)
    rows = db.execute(query).mappings().all()

    items = [
        ClaimSummarySchema(
            claim_id=row["claim_id"],
            charge_id=row["charge_id"],
            assessment=row["assessment"],
            claim_amount=row["claim_amount"],
            status=row["status"],
            confidence=row["confidence"],
            source_manager=row["source_manager"],
            created_at=row["created_at"],
        )
        for row in rows
    ]

    return ClaimListResponseSchema(
        total=total,
        limit=limit,
        offset=offset,
        items=items,
    )


@router.get(
    "/{claim_id}",
    response_model=ClaimTraceabilityResponseSchema,
    summary="Get full claim detail and complete end-to-end traceability chain",
)
def get_claim_traceability_endpoint(
    claim_id: str,
    db: Session = Depends(get_db),
) -> ClaimTraceabilityResponseSchema:
    """
    Retrieve full claim detail including the complete traceability chain:
    claim -> charge -> shipment/order/sku -> each evidence row -> source_manager -> evidence_timestamp -> evidence_content.

    Reuses the proven SQL JOIN across claims, charges, shipments, orders, claim_evidence, and evidence.
    """
    clean_id = claim_id.strip()

    trace_query = text(
        """
        SELECT
            c.claim_id,
            c.assessment,
            c.claim_amount,
            c.confidence,
            c.explanation,
            c.status AS claim_status,
            c.source_manager AS claim_source_manager,
            c.created_at AS claim_created_at,
            ch.charge_id,
            ch.charge_type,
            ch.amount AS charge_amount,
            ch.currency AS charge_currency,
            ch.charge_date,
            ch.status AS charge_status,
            ch.sku,
            ch.asin,
            s.shipment_id,
            o.order_id,
            e.evidence_id,
            e.source_manager AS evidence_source_manager,
            e.evidence_type,
            e.evidence_timestamp,
            e.evidence_content
        FROM claims c
        JOIN charges ch ON c.charge_id = ch.id
        LEFT JOIN shipments s ON ch.shipment_id = s.id
        LEFT JOIN orders o ON ch.order_id = o.id
        LEFT JOIN claim_evidence ce ON ce.claim_id = c.id
        LEFT JOIN evidence e ON ce.evidence_id = e.id
        WHERE c.claim_id = :claim_id
        ORDER BY e.evidence_timestamp ASC NULLS LAST;
        """
    )

    rows = db.execute(trace_query, {"claim_id": clean_id}).mappings().all()

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Claim with claim_id '{claim_id}' not found.",
        )

    first_row = rows[0]

    evidence_items: List[TraceableEvidenceItemSchema] = []
    seen_evidence_ids = set()
    for row in rows:
        eid = row["evidence_id"]
        if eid and eid not in seen_evidence_ids:
            seen_evidence_ids.add(eid)
            evidence_items.append(
                TraceableEvidenceItemSchema(
                    evidence_id=eid,
                    source_manager=row["evidence_source_manager"],
                    evidence_type=row["evidence_type"],
                    evidence_timestamp=row["evidence_timestamp"],
                    evidence_content=row["evidence_content"] or {},
                )
            )

    return ClaimTraceabilityResponseSchema(
        claim_id=first_row["claim_id"],
        assessment=first_row["assessment"],
        claim_amount=first_row["claim_amount"],
        confidence=first_row["confidence"],
        explanation=first_row["explanation"],
        status=first_row["claim_status"],
        source_manager=first_row["claim_source_manager"],
        created_at=first_row["claim_created_at"],
        charge_id=first_row["charge_id"],
        charge_type=first_row["charge_type"],
        charge_amount=first_row["charge_amount"],
        charge_currency=first_row["charge_currency"],
        charge_date=first_row["charge_date"],
        charge_status=first_row["charge_status"],
        sku=first_row["sku"],
        asin=first_row["asin"],
        shipment_id=first_row["shipment_id"],
        order_id=first_row["order_id"],
        evidence=evidence_items,
    )
