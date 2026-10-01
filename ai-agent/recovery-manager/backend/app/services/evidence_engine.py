"""Phase 4 Deterministic Evidence Engine.

Strictly adheres to:
- Evidence first, claim second.
- Deterministic, exact identifier matching only (priority: shipment_id -> order_id -> sku -> asin).
- Deterministic exact database queries only.
- Preserves full provenance (evidence_id, source_manager, evidence_type, evidence_timestamp, evidence_content, matched_by, match_value).
- Single deduplicated record per evidence, with stable tie-breaking and deterministic ordering.
- Preserves conflicting evidence without interpreting or assigning assessment statuses.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from app.core.logging import logger
from app.models.charge import Charge
from app.models.evidence import Evidence
from app.models.order import Order
from app.models.shipment import Shipment


# Priority ranks for deterministic ordering and primary key selection
MATCH_PRIORITY_ORDER = ("unit_id", "fnsku", "sku", "shipment_id", "order_id", "asin")
PRIORITY_RANK_MAP = {key: idx + 1 for idx, key in enumerate(MATCH_PRIORITY_ORDER)}


class EvidenceEngineError(Exception):
    """Base exception for Evidence Engine errors."""
    pass


class ChargeNotFoundError(EvidenceEngineError):
    """Raised when the specified charge does not exist in the database."""
    pass


@dataclass
class EvidenceMatch:
    """Represents an operational evidence record matched to a charge."""

    evidence_id: str
    matched_by: str
    match_value: str
    source_manager: str
    evidence_type: str
    evidence_timestamp: datetime
    evidence_content: Dict[str, Any]
    id: Optional[UUID] = None
    matched_keys: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary matching the API schema."""
        return {
            "evidence_id": self.evidence_id,
            "matched_by": self.matched_by,
            "match_value": self.match_value,
            "source_manager": self.source_manager,
            "evidence_type": self.evidence_type,
            "evidence_timestamp": self.evidence_timestamp.isoformat() if self.evidence_timestamp else None,
            "evidence_content": self.evidence_content,
            "matched_keys": self.matched_keys,
        }


@dataclass
class EvidenceRetrievalResult:
    """The complete result of deterministic candidate retrieval and relevance filtering."""

    charge_id: str
    candidate_count: int
    relevant_count: int
    evidence: List[EvidenceMatch] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "charge_id": self.charge_id,
            "candidate_count": self.candidate_count,
            "relevant_count": self.relevant_count,
            "evidence": [e.to_dict() for e in self.evidence],
        }


def _normalize_dt_for_sort(dt: Optional[datetime]) -> datetime:
    """Normalize datetime for robust, error-free sort comparison."""
    if dt is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class EvidenceEngine:
    """Deterministic Evidence Engine for Recovery Manager."""

    def find_charge(self, identifier: str, db: Session) -> Optional[Charge]:
        """
        Locate a charge by its external charge_id string or its internal UUID.
        Eagerly loads shipment and order relationships to resolve external identifiers.
        """
        if not identifier or not identifier.strip():
            return None

        clean_id = identifier.strip()

        # 1. Primary lookup: external charge_id (e.g. 'CHG-FBA-8901')
        stmt = (
            select(Charge)
            .options(joinedload(Charge.shipment), joinedload(Charge.order))
            .where(Charge.charge_id == clean_id)
        )
        charge = db.scalars(stmt).first()
        if charge is not None:
            return charge

        # 2. Fallback lookup: unit_id (e.g. 'UNIT-0002')
        stmt_unit = (
            select(Charge)
            .options(joinedload(Charge.shipment), joinedload(Charge.order))
            .where(Charge.unit_id == clean_id)
        )
        charge_by_unit = db.scalars(stmt_unit).first()
        if charge_by_unit is not None:
            return charge_by_unit

        # 3. Fallback lookup: internal UUID
        try:
            val_uuid = uuid.UUID(clean_id)
            stmt = (
                select(Charge)
                .options(joinedload(Charge.shipment), joinedload(Charge.order))
                .where(Charge.id == val_uuid)
            )
            return db.scalars(stmt).first()
        except (ValueError, TypeError, AttributeError):
            return None

    def retrieve_candidates(self, charge: Charge, db: Session) -> List[Evidence]:
        """
        Perform indexed database retrieval for candidate evidence matching any of the charge's
        explicit non-null identifiers:
        - evidence.unit_id == charge.unit_id (highest priority)
        - evidence.fnsku == charge.fnsku
        - evidence.sku == charge.sku
        - evidence.shipment_id == charge.shipment_id
        - evidence.order_id == charge.order_id
        - evidence.asin == charge.asin
        """
        conditions = []

        if charge.unit_id and charge.unit_id.strip():
            conditions.append(Evidence.unit_id == charge.unit_id.strip())

        if charge.fnsku and charge.fnsku.strip():
            conditions.append(Evidence.fnsku == charge.fnsku.strip())

        if charge.sku and charge.sku.strip():
            conditions.append(Evidence.sku == charge.sku.strip())

        if charge.shipment_id is not None:
            conditions.append(Evidence.shipment_id == charge.shipment_id)

        if charge.order_id is not None:
            conditions.append(Evidence.order_id == charge.order_id)

        if charge.asin and charge.asin.strip():
            conditions.append(Evidence.asin == charge.asin.strip())

        if not conditions:
            logger.info(f"Charge {charge.charge_id} has no linking identifiers. No candidate evidence.")
            return []

        # Query evidence using OR across explicit identifier criteria
        stmt = select(Evidence).where(or_(*conditions))
        # Tenant scope is part of retrieval, never inferred from a matching unit/SKU.
        candidates = list(db.scalars(stmt.where(Evidence.org_id == charge.org_id)).all())
        logger.debug(f"Retrieved {len(candidates)} candidate evidence records for charge {charge.charge_id}.")
        return candidates

    def filter_and_rank_evidence(
        self,
        charge: Charge,
        candidates: List[Evidence],
        shipment_ext_id: Optional[str] = None,
        order_ext_id: Optional[str] = None,
    ) -> List[EvidenceMatch]:
        """
        Perform deterministic relevance filtering and provenance tracking on candidate evidence.
        - Excludes any evidence lacking an explicit identifier relationship to the charge.
        - Deduplicates multiple matches of the same evidence record.
        - Assigns highest-priority matching key ('unit_id' > 'fnsku' > 'sku' > 'shipment_id' > 'order_id' > 'asin').
        - Sorts deterministically by: (priority_rank, evidence_timestamp, evidence_id).
        """
        charge_unit_id = charge.unit_id.strip() if charge.unit_id and charge.unit_id.strip() else None
        charge_fnsku = charge.fnsku.strip() if charge.fnsku and charge.fnsku.strip() else None
        charge_sku = charge.sku.strip() if charge.sku and charge.sku.strip() else None
        charge_asin = charge.asin.strip() if charge.asin and charge.asin.strip() else None

        # Resolve external display strings for shipment and order
        resolved_shipment_val = shipment_ext_id
        if not resolved_shipment_val and charge.shipment:
            resolved_shipment_val = charge.shipment.shipment_id
        elif not resolved_shipment_val and charge.shipment_id:
            resolved_shipment_val = str(charge.shipment_id)

        resolved_order_val = order_ext_id
        if not resolved_order_val and charge.order:
            resolved_order_val = charge.order.order_id
        elif not resolved_order_val and charge.order_id:
            resolved_order_val = str(charge.order_id)

        # Map to track unique evidence records and their matched keys
        # Key: evidence.id or evidence.evidence_id -> dict with match metadata
        unique_matches: Dict[str, Dict[str, Any]] = {}

        for candidate in candidates:
            cand_key = str(candidate.id) if candidate.id else candidate.evidence_id
            matched_keys: List[str] = []

            # 1. Exact unit_id match (Highest priority)
            if (
                charge_unit_id is not None
                and candidate.unit_id is not None
                and candidate.unit_id.strip() == charge_unit_id
            ):
                matched_keys.append("unit_id")

            # 2. Exact fnsku match
            if (
                charge_fnsku is not None
                and candidate.fnsku is not None
                and candidate.fnsku.strip() == charge_fnsku
            ):
                matched_keys.append("fnsku")

            # 3. Exact SKU match (Stripped exact string equality)
            if (
                charge_sku is not None
                and candidate.sku is not None
                and candidate.sku.strip() == charge_sku
            ):
                matched_keys.append("sku")

            # 4. Exact shipment_id match (Internal UUID check)
            if (
                charge.shipment_id is not None
                and candidate.shipment_id is not None
                and candidate.shipment_id == charge.shipment_id
            ):
                matched_keys.append("shipment_id")

            # 5. Exact order_id match (Internal UUID check)
            if (
                charge.order_id is not None
                and candidate.order_id is not None
                and candidate.order_id == charge.order_id
            ):
                matched_keys.append("order_id")

            # 6. Exact ASIN match (Stripped exact string equality)
            if (
                charge_asin is not None
                and candidate.asin is not None
                and candidate.asin.strip() == charge_asin
            ):
                matched_keys.append("asin")

            # RELEVANCE FILTER: Reject any candidate that lacks an explicit identifier match
            if not matched_keys:
                continue

            # Deduplication: Merge if already seen (e.g. from multiple queries or duplicate inputs)
            if cand_key in unique_matches:
                existing_keys = unique_matches[cand_key]["matched_keys"]
                for k in matched_keys:
                    if k not in existing_keys:
                        existing_keys.append(k)
            else:
                unique_matches[cand_key] = {
                    "candidate": candidate,
                    "matched_keys": matched_keys,
                }

        # Build EvidenceMatch objects
        results: List[EvidenceMatch] = []
        for cand_key, item in unique_matches.items():
            candidate = item["candidate"]
            matched_keys = item["matched_keys"]

            # Sort matched_keys by defined priority order
            matched_keys.sort(key=lambda k: PRIORITY_RANK_MAP.get(k, 99))
            primary_matched_by = matched_keys[0]

            # Assign exact match_value based on primary matching key
            if primary_matched_by == "unit_id":
                match_val = charge_unit_id or ""
            elif primary_matched_by == "fnsku":
                match_val = charge_fnsku or ""
            elif primary_matched_by == "sku":
                match_val = charge_sku or ""
            elif primary_matched_by == "shipment_id":
                match_val = resolved_shipment_val or ""
            elif primary_matched_by == "order_id":
                match_val = resolved_order_val or ""
            elif primary_matched_by == "asin":
                match_val = charge_asin or ""
            else:
                match_val = ""

            results.append(
                EvidenceMatch(
                    id=candidate.id,
                    evidence_id=candidate.evidence_id,
                    matched_by=primary_matched_by,
                    match_value=match_val,
                    source_manager=candidate.source_manager,
                    evidence_type=candidate.evidence_type,
                    evidence_timestamp=candidate.evidence_timestamp,
                    evidence_content=candidate.evidence_content or {},
                    matched_keys=matched_keys,
                )
            )

        # Deterministic sorting: priority rank -> evidence timestamp -> evidence_id tiebreaker
        results.sort(
            key=lambda m: (
                PRIORITY_RANK_MAP.get(m.matched_by, 99),
                _normalize_dt_for_sort(m.evidence_timestamp),
                m.evidence_id,
            )
        )

        return results

    def get_evidence_for_charge_model(self, charge: Charge, db: Session) -> EvidenceRetrievalResult:
        """
        Execute deterministic evidence retrieval pipeline given an already loaded Charge instance:
        Charge -> Candidate Evidence Retrieval -> Relevance Filtering -> Relevant Evidence Set.
        """
        # Resolve shipment external identifier if shipment is linked
        shipment_ext_id: Optional[str] = None
        if charge.shipment:
            shipment_ext_id = charge.shipment.shipment_id
        elif charge.shipment_id:
            s = db.get(Shipment, charge.shipment_id)
            if s:
                shipment_ext_id = s.shipment_id

        # Resolve order external identifier if order is linked
        order_ext_id: Optional[str] = None
        if charge.order:
            order_ext_id = charge.order.order_id
        elif charge.order_id:
            o = db.get(Order, charge.order_id)
            if o:
                order_ext_id = o.order_id

        candidates = self.retrieve_candidates(charge, db)
        candidate_count = len(candidates)

        relevant_evidence = self.filter_and_rank_evidence(
            charge=charge,
            candidates=candidates,
            shipment_ext_id=shipment_ext_id,
            order_ext_id=order_ext_id,
        )
        relevant_count = len(relevant_evidence)

        logger.info(
            f"Evidence Engine for charge {charge.charge_id}: "
            f"{candidate_count} candidates -> {relevant_count} relevant."
        )

        return EvidenceRetrievalResult(
            charge_id=charge.charge_id,
            candidate_count=candidate_count,
            relevant_count=relevant_count,
            evidence=relevant_evidence,
        )

    def get_evidence_for_charge(self, charge_identifier: str, db: Session) -> EvidenceRetrievalResult:
        """
        Retrieve deterministic relevant evidence for a charge by its external charge_id or UUID.
        Raises ChargeNotFoundError if the charge does not exist.
        """
        charge = self.find_charge(charge_identifier, db)
        if charge is None:
            raise ChargeNotFoundError(f"Charge with identifier '{charge_identifier}' not found.")

        return self.get_evidence_for_charge_model(charge, db)


# Singleton instance
evidence_engine = EvidenceEngine()
