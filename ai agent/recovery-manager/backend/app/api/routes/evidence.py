"""API routes for Phase 4 Evidence Engine retrieval and Phase 8a Evidence Read Layer."""

from typing import Optional
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, func, or_, select
from sqlalchemy.orm import Session

from app.core.database import current_org, get_db
from app.models.evidence import Evidence
from app.models.order import Order
from app.models.shipment import Shipment
from app.schemas.evidence import (
    ChargeEvidenceResponseSchema,
    EvidenceListResponseSchema,
    EvidenceRecordSchema,
)
from app.services.evidence_engine import evidence_engine, ChargeNotFoundError

router = APIRouter(prefix="/evidence", tags=["Evidence"])


@router.get(
    "",
    response_model=EvidenceListResponseSchema,
    summary="Get paginated list of operational evidence records with filters",
)
def get_evidence_endpoint(
    source_manager: Optional[str] = Query(default=None, description="Filter by operational department"),
    shipment_id: Optional[str] = Query(default=None, description="Filter by shipment identifier (external ID or UUID)"),
    order_id: Optional[str] = Query(default=None, description="Filter by order identifier (external ID or UUID)"),
    data_origin: Optional[str] = Query(default=None, description="Filter by row provenance"),
    limit: int = Query(default=100, ge=1, le=1000, description="Page limit"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    db: Session = Depends(get_db),
) -> EvidenceListResponseSchema:
    """
    Retrieve paginated list of operational evidence records.
    Supports filtering by source_manager, shipment_id, and order_id.
    """
    base_query = (
        select(
            Evidence.evidence_id,
            Evidence.source_manager,
            Shipment.shipment_id.label("ext_shipment_id"),
            Order.order_id.label("ext_order_id"),
            Evidence.sku,
            Evidence.asin,
            Evidence.evidence_type,
            Evidence.evidence_content,
            Evidence.evidence_timestamp,
            Evidence.created_at,
            Evidence.data_origin,
        )
        .outerjoin(Shipment, Evidence.shipment_id == Shipment.id)
        .outerjoin(Order, Evidence.order_id == Order.id)
    )

    count_stmt = select(func.count(Evidence.id)).outerjoin(Shipment, Evidence.shipment_id == Shipment.id).outerjoin(Order, Evidence.order_id == Order.id)

    filters = []
    filters.append(Evidence.org_id == current_org(db))

    if source_manager:
        filters.append(Evidence.source_manager == source_manager.strip())

    if shipment_id:
        clean_shipment = shipment_id.strip()
        shipment_conditions = [Shipment.shipment_id == clean_shipment]
        try:
            val_uuid = uuid.UUID(clean_shipment)
            shipment_conditions.append(Evidence.shipment_id == val_uuid)
        except (ValueError, TypeError, AttributeError):
            pass
        filters.append(or_(*shipment_conditions))

    if order_id:
        clean_order = order_id.strip()
        order_conditions = [Order.order_id == clean_order]
        try:
            val_uuid = uuid.UUID(clean_order)
            order_conditions.append(Evidence.order_id == val_uuid)
        except (ValueError, TypeError, AttributeError):
            pass
        filters.append(or_(*order_conditions))
    filters.append(Evidence.data_origin == (data_origin.strip() if data_origin else "judge_data"))

    if filters:
        base_query = base_query.where(*filters)
        count_stmt = count_stmt.where(*filters)

    total = db.scalar(count_stmt) or 0

    query = base_query.order_by(desc(Evidence.evidence_timestamp), desc(Evidence.created_at)).limit(limit).offset(offset)
    rows = db.execute(query).mappings().all()

    items = [
        EvidenceRecordSchema(
            evidence_id=row["evidence_id"],
            source_manager=row["source_manager"],
            shipment_id=row["ext_shipment_id"],
            order_id=row["ext_order_id"],
            sku=row["sku"],
            asin=row["asin"],
            evidence_type=row["evidence_type"],
            evidence_content=row["evidence_content"] or {},
            evidence_timestamp=row["evidence_timestamp"],
            created_at=row["created_at"],
            data_origin=row["data_origin"],
        )
        for row in rows
    ]

    return EvidenceListResponseSchema(
        total=total,
        limit=limit,
        offset=offset,
        items=items,
    )


@router.get("/charge/{charge_id}", response_model=ChargeEvidenceResponseSchema)
def get_evidence_for_charge_endpoint(
    charge_id: str,
    db: Session = Depends(get_db),
):
    """
    Deterministically retrieve and filter operational evidence for a specific marketplace charge.
    Matches strictly on: shipment_id, order_id, sku, asin.
    Returns 404 if the charge does not exist.
    """
    try:
        result = evidence_engine.get_evidence_for_charge(charge_identifier=charge_id, db=db)
        return result.to_dict()
    except ChargeNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
