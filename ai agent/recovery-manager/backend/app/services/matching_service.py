"""Matching service linking financial charges with operational evidence_events by shipment_id."""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import select, and_
from sqlalchemy.orm import Session, joinedload

from app.core.logging import logger
from app.models.charge import Charge
from app.models.shipment import Shipment
from app.models.evidence_event import EvidenceEvent


@dataclass
class MatchedEvidenceItem:
    id: str
    shipment_id: str
    evidence_type: str
    timestamp: str
    status: Optional[str]
    source_file: str
    raw_payload: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChargeMatchResult:
    charge_id: str
    shipment_id: Optional[str]
    charge_date: str
    amount: float
    charge_type: str
    has_evidence: bool
    status: str  # "MATCHED", "NO_EVIDENCE_FOUND"
    matched_count: int
    evidence: List[MatchedEvidenceItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "charge_id": self.charge_id,
            "shipment_id": self.shipment_id,
            "charge_date": self.charge_date,
            "amount": self.amount,
            "charge_type": self.charge_type,
            "has_evidence": self.has_evidence,
            "status": self.status,
            "matched_count": self.matched_count,
            "evidence": [e.to_dict() for e in self.evidence],
        }


class MatchingService:
    """Matches charges to operational evidence_events by shipment_id within a time window."""

    def match_charge(
        self,
        charge_id: str,
        db: Session,
        window_days: int = 30,
        org_id: Optional[str] = None,
    ) -> ChargeMatchResult:
        """Fetch evidence for a single charge by shipment_id within time window."""
        stmt = (
            select(Charge)
            .options(joinedload(Charge.shipment))
            .where(Charge.charge_id == charge_id)
        )
        charge = db.execute(stmt).scalar_one_or_none()
        if not charge:
            return ChargeMatchResult(
                charge_id=charge_id,
                shipment_id=None,
                charge_date="",
                amount=0.0,
                charge_type="",
                has_evidence=False,
                status="CHARGE_NOT_FOUND",
                matched_count=0,
                evidence=[],
            )

        # Resolve external shipment_id string
        ext_shipment = None
        if charge.shipment and charge.shipment.shipment_id:
            ext_shipment = charge.shipment.shipment_id
        elif isinstance(charge.raw_data, dict):
            ext_shipment = (
                charge.raw_data.get("fba_shipment_id")
                or charge.raw_data.get("shipment_id")
                or charge.raw_data.get("shipmentid")
            )

        c_date = charge.charge_date
        if c_date.tzinfo is None:
            c_date = c_date.replace(tzinfo=timezone.utc)

        if not ext_shipment:
            return ChargeMatchResult(
                charge_id=charge.charge_id,
                shipment_id=None,
                charge_date=c_date.isoformat(),
                amount=float(charge.amount),
                charge_type=charge.charge_type,
                has_evidence=False,
                status="NO_EVIDENCE_FOUND",
                matched_count=0,
                evidence=[],
            )

        start_time = c_date - timedelta(days=window_days)
        end_time = c_date + timedelta(days=window_days)

        ev_stmt = select(EvidenceEvent).where(
            and_(
                EvidenceEvent.shipment_id == ext_shipment,
                EvidenceEvent.timestamp >= start_time,
                EvidenceEvent.timestamp <= end_time,
            )
        )
        if org_id:
            ev_stmt = ev_stmt.where(EvidenceEvent.org_id == org_id)

        ev_rows = db.execute(ev_stmt).scalars().all()

        evidence_items = [
            MatchedEvidenceItem(
                id=str(row.id),
                shipment_id=row.shipment_id,
                evidence_type=row.evidence_type,
                timestamp=row.timestamp.isoformat() if row.timestamp else "",
                status=row.status,
                source_file=row.source_file,
                raw_payload=row.raw_payload or {},
            )
            for row in ev_rows
        ]

        has_evidence = len(evidence_items) > 0
        match_status = "MATCHED" if has_evidence else "NO_EVIDENCE_FOUND"

        return ChargeMatchResult(
            charge_id=charge.charge_id,
            shipment_id=ext_shipment,
            charge_date=c_date.isoformat(),
            amount=float(charge.amount),
            charge_type=charge.charge_type,
            has_evidence=has_evidence,
            status=match_status,
            matched_count=len(evidence_items),
            evidence=evidence_items,
        )

    def match_all_charges(
        self,
        db: Session,
        charge_ids: Optional[List[str]] = None,
        window_days: int = 30,
        org_id: Optional[str] = None,
    ) -> List[ChargeMatchResult]:
        """Match multiple charges in batch."""
        stmt = select(Charge.charge_id)
        if charge_ids:
            stmt = stmt.where(Charge.charge_id.in_(charge_ids))
        if org_id:
            stmt = stmt.where(Charge.org_id == org_id)

        all_ids = db.execute(stmt).scalars().all()
        return [
            self.match_charge(cid, db=db, window_days=window_days, org_id=org_id)
            for cid in all_ids
        ]


matching_service = MatchingService()
