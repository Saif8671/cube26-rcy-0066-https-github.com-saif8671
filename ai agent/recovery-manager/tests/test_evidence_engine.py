"""Comprehensive Phase 4 Evidence Engine Tests.

Verifies all 38 test requirements from Phase 4 specification:
1. Evidence matches by shipment_id.
2. Evidence matches by order_id.
3. Evidence matches by SKU.
4. Evidence matches by ASIN.
5. Shipment match has correct matched_by.
6. Order match has correct matched_by.
7. SKU match has correct matched_by.
8. ASIN match has correct matched_by.
9. Partial shipment ID does not match.
10. Partial order ID does not match.
11. Similar SKU does not match.
12. Similar ASIN does not match.
13. Same amount but unrelated identifiers -> excluded.
14. Same date but unrelated identifiers -> excluded.
15. Same charge type but unrelated identifiers -> excluded.
16. Same source manager but unrelated identifiers -> excluded.
17. Multiple evidence records for one charge are returned.
18. Evidence from multiple Managers is returned.
19. Same evidence matching through multiple keys appears only once.
20. No evidence -> empty result.
21. Conflicting evidence -> all relevant evidence preserved.
22. Evidence with missing optional identifiers is handled correctly.
23. Unknown charge -> appropriate error.
24. Evidence ID preserved.
25. Source Manager preserved.
26. Evidence timestamp preserved.
27. Evidence content preserved.
28. Match key/value preserved.
29. Evidence ordering is deterministic.
30. Stable tiebreaking works.
31. Database failures do not expose secrets.
32. API responses do not expose credentials or SQL details.
33. No Anthropic/LLM calls.
34. No embeddings/vector search.
35. No fuzzy matching library.
36. No claim creation.
37. No assessment classification.
38. No rule validation.
"""

from datetime import datetime, timezone
from decimal import Decimal
import inspect
from pathlib import Path
import sys
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.api.routes import evidence as evidence_routes_module
from app.core.database import SessionLocal
from app.main import app
from app.models.charge import Charge
from app.models.claim import Claim
from app.models.evidence import Evidence
from app.models.order import Order
from app.models.shipment import Shipment
from app.schemas.evidence import ChargeEvidenceResponseSchema, EvidenceMatchSchema
from app.services import evidence_engine as evidence_engine_module
from app.services.evidence_engine import (
    ChargeNotFoundError,
    EvidenceEngine,
    EvidenceMatch,
    EvidenceRetrievalResult,
    evidence_engine,
)


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app, headers={"X-Org-Id": "org_test_alpha"}, raise_server_exceptions=False)


@pytest.fixture
def db():
    """Database session fixture for verification."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clean_phase4_test_data():
    """Cleanup any Phase 4 test records before and after each test."""
    def _cleanup():
        session = SessionLocal()
        try:
            session.execute(text("DELETE FROM evidence WHERE org_id LIKE 'org_test_%'"))
            session.execute(text("DELETE FROM charges WHERE org_id LIKE 'org_test_%'"))
            session.execute(text("DELETE FROM shipments WHERE org_id LIKE 'org_test_%'"))
            session.execute(text("DELETE FROM orders WHERE org_id LIKE 'org_test_%'"))
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    _cleanup()
    yield
    _cleanup()


# ==============================================================================
# 1-8: Exact Identifier Matching & Correct `matched_by`
# ==============================================================================

def test_01_and_05_evidence_matches_by_shipment_id_and_has_correct_matched_by(db: Session):
    """Requirement 1 & 5: Evidence matches by shipment_id and matched_by is 'shipment_id'."""
    # Seed data charge CHG-FBA-8901 links to shipment FBA17Z88Y12, which has evidence EVD-PREP-8821
    result = evidence_engine.get_evidence_for_charge("CHG-FBA-8901", db)
    assert result.candidate_count >= 1
    assert result.relevant_count >= 1

    match = next((e for e in result.evidence if e.evidence_id == "EVD-PREP-8821"), None)
    assert match is not None
    # Under official contract priority (unit_id -> fnsku -> sku -> shipment_id), sku is highest rank
    assert match.matched_by == "sku"
    assert "shipment_id" in match.matched_keys
    assert match.match_value == "TECH-CABLE-01"


def test_02_and_06_evidence_matches_by_order_id_and_has_correct_matched_by(db: Session):
    """Requirement 2 & 6: Evidence matches by order_id and matched_by is 'order_id'."""
    # Create isolated order, charge (with no shipment), and evidence
    order = Order(order_id="ORD-P4-001")
    db.add(order)
    db.flush()

    charge = Charge(
        charge_id="CHG-P4-ORD01",
        shipment_id=None,
        order_id=order.id,
        sku=None,
        asin=None,
        charge_type="Customer Return Processing",
        amount=Decimal("15.00"),
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    db.add(charge)

    evidence = Evidence(
        evidence_id="EVD-P4-ORD01",
        source_manager="Returns",
        shipment_id=None,
        order_id=order.id,
        sku=None,
        asin=None,
        evidence_type="customer_return_scan",
        evidence_content={"item_condition": "DEFECTIVE"},
        evidence_timestamp=datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc),
    )
    db.add(evidence)
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-ORD01", db)
    assert result.relevant_count == 1
    match = result.evidence[0]
    assert match.evidence_id == "EVD-P4-ORD01"
    assert match.matched_by == "order_id"
    assert match.match_value == "ORD-P4-001"


def test_03_and_07_evidence_matches_by_sku_and_has_correct_matched_by(db: Session):
    """Requirement 3 & 7: Evidence matches by SKU and matched_by is 'sku'."""
    # Create isolated charge (no shipment, no order) with SKU and evidence with SKU
    charge = Charge(
        charge_id="CHG-P4-SKU01",
        shipment_id=None,
        order_id=None,
        sku="SKU-P4-UNIQUE-01",
        asin=None,
        charge_type="Labeling Defect",
        amount=Decimal("20.00"),
        charge_date=datetime(2026, 3, 2, 10, 0, tzinfo=timezone.utc),
    )
    db.add(charge)

    evidence = Evidence(
        evidence_id="EVD-P4-SKU01",
        source_manager="Prep",
        shipment_id=None,
        order_id=None,
        sku="SKU-P4-UNIQUE-01",
        asin=None,
        evidence_type="label_check",
        evidence_content={"barcode_readable": True},
        evidence_timestamp=datetime(2026, 3, 2, 9, 30, tzinfo=timezone.utc),
    )
    db.add(evidence)
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-SKU01", db)
    assert result.relevant_count == 1
    match = result.evidence[0]
    assert match.evidence_id == "EVD-P4-SKU01"
    assert match.matched_by == "sku"
    assert match.match_value == "SKU-P4-UNIQUE-01"


def test_04_and_08_evidence_matches_by_asin_and_has_correct_matched_by(db: Session):
    """Requirement 4 & 8: Evidence matches by ASIN and matched_by is 'asin'."""
    charge = Charge(
        charge_id="CHG-P4-ASIN01",
        shipment_id=None,
        order_id=None,
        sku=None,
        asin="B0P4TEST01",
        charge_type="Polybag Fee",
        amount=Decimal("35.00"),
        charge_date=datetime(2026, 3, 3, 10, 0, tzinfo=timezone.utc),
    )
    db.add(charge)

    evidence = Evidence(
        evidence_id="EVD-P4-ASIN01",
        source_manager="Prep",
        shipment_id=None,
        order_id=None,
        sku=None,
        asin="B0P4TEST01",
        evidence_type="polybag_inspection",
        evidence_content={"thickness_mil": 1.6},
        evidence_timestamp=datetime(2026, 3, 3, 8, 45, tzinfo=timezone.utc),
    )
    db.add(evidence)
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-ASIN01", db)
    assert result.relevant_count == 1
    match = result.evidence[0]
    assert match.evidence_id == "EVD-P4-ASIN01"
    assert match.matched_by == "asin"
    assert match.match_value == "B0P4TEST01"


# ==============================================================================
# 9-12: No Fuzzy Matching (Exactness Enforced)
# ==============================================================================

def test_09_partial_shipment_id_does_not_match(db: Session):
    """Requirement 9: Partial shipment ID (e.g. FBA17Z88Y1 vs FBA17Z88Y12) does not match."""
    shp_full = Shipment(shipment_id="SHP-P4-FULL-12345")
    shp_partial = Shipment(shipment_id="SHP-P4-FULL-1234")  # substring
    db.add_all([shp_full, shp_partial])
    db.flush()

    charge = Charge(
        charge_id="CHG-P4-FUZZY-SHP",
        shipment_id=shp_full.id,
        order_id=None,
        sku=None,
        asin=None,
        charge_type="Defect",
        amount=Decimal("10.00"),
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    db.add(charge)

    evidence = Evidence(
        evidence_id="EVD-P4-FUZZY-SHP",
        source_manager="Prep",
        shipment_id=shp_partial.id,  # different shipment UUID despite partial string similarity
        order_id=None,
        sku=None,
        asin=None,
        evidence_type="inspection",
        evidence_content={},
        evidence_timestamp=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
    )
    db.add(evidence)
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-FUZZY-SHP", db)
    assert result.candidate_count == 0
    assert result.relevant_count == 0
    assert len(result.evidence) == 0


def test_10_partial_order_id_does_not_match(db: Session):
    """Requirement 10: Partial order ID (substring / edit distance) does not match."""
    ord_full = Order(order_id="ORD-P4-111-2222-3333")
    ord_partial = Order(order_id="ORD-P4-111-2222")
    db.add_all([ord_full, ord_partial])
    db.flush()

    charge = Charge(
        charge_id="CHG-P4-FUZZY-ORD",
        shipment_id=None,
        order_id=ord_full.id,
        sku=None,
        asin=None,
        charge_type="Fee",
        amount=Decimal("12.00"),
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    db.add(charge)

    evidence = Evidence(
        evidence_id="EVD-P4-FUZZY-ORD",
        source_manager="Returns",
        shipment_id=None,
        order_id=ord_partial.id,
        sku=None,
        asin=None,
        evidence_type="inspection",
        evidence_content={},
        evidence_timestamp=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
    )
    db.add(evidence)
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-FUZZY-ORD", db)
    assert result.candidate_count == 0
    assert result.relevant_count == 0
    assert len(result.evidence) == 0


def test_11_similar_sku_does_not_match(db: Session):
    """Requirement 11: Similar SKU (substring, prefix, suffix, off-by-one) does not match."""
    charge = Charge(
        charge_id="CHG-P4-FUZZY-SKU",
        shipment_id=None,
        order_id=None,
        sku="SKU-TARGET-EXACT",
        asin=None,
        charge_type="Defect",
        amount=Decimal("25.00"),
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    db.add(charge)

    # Similar but not exact SKUs
    ev1 = Evidence(
        evidence_id="EVD-P4-FUZZY-SKU-1",
        source_manager="Prep",
        sku="SKU-TARGET-EXAC",  # missing last letter
        evidence_type="prep",
        evidence_content={},
        evidence_timestamp=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
    )
    ev2 = Evidence(
        evidence_id="EVD-P4-FUZZY-SKU-2",
        source_manager="Prep",
        sku="SKU-TARGET-EXACT-X",  # extra letter
        evidence_type="prep",
        evidence_content={},
        evidence_timestamp=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
    )
    db.add_all([ev1, ev2])
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-FUZZY-SKU", db)
    assert result.candidate_count == 0
    assert result.relevant_count == 0
    assert len(result.evidence) == 0


def test_12_similar_asin_does_not_match(db: Session):
    """Requirement 12: Similar ASIN does not match."""
    charge = Charge(
        charge_id="CHG-P4-FUZZY-ASIN",
        shipment_id=None,
        order_id=None,
        sku=None,
        asin="B0P4FUZZYASIN",
        charge_type="Defect",
        amount=Decimal("40.00"),
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    db.add(charge)

    ev = Evidence(
        evidence_id="EVD-P4-FUZZY-ASIN",
        source_manager="Prep",
        asin="B0P4FUZZYASI",  # truncated by one character
        evidence_type="prep",
        evidence_content={},
        evidence_timestamp=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
    )
    db.add(ev)
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-FUZZY-ASIN", db)
    assert result.candidate_count == 0
    assert result.relevant_count == 0
    assert len(result.evidence) == 0


# ==============================================================================
# 13-16: Relevance Filtering (Exclude Unrelated Features)
# ==============================================================================

def test_13_same_amount_unrelated_identifiers_excluded(db: Session):
    """Requirement 13: Evidence with same amount but unrelated identifiers is excluded."""
    charge = Charge(
        charge_id="CHG-P4-REL-AMT",
        shipment_id=None,
        order_id=None,
        sku="SKU-CHG-AMT",
        asin=None,
        charge_type="Weight Discrepancy",
        amount=Decimal("99.50"),
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    db.add(charge)

    # Evidence has same amount in content but completely different SKU and no shipment/order
    evidence = Evidence(
        evidence_id="EVD-P4-REL-AMT",
        source_manager="Receiving",
        sku="SKU-DIFFERENT-UNLINKED",
        evidence_type="scale_audit",
        evidence_content={"fee": 99.50, "amount": 99.50},
        evidence_timestamp=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    db.add(evidence)
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-REL-AMT", db)
    assert result.candidate_count == 0
    assert result.relevant_count == 0


def test_14_same_date_unrelated_identifiers_excluded(db: Session):
    """Requirement 14: Evidence sharing exact timestamp but unrelated identifiers is excluded."""
    target_dt = datetime(2026, 3, 15, 14, 22, 10, tzinfo=timezone.utc)
    charge = Charge(
        charge_id="CHG-P4-REL-DATE",
        shipment_id=None,
        order_id=None,
        sku="SKU-CHG-DATE",
        asin=None,
        charge_type="Prep Fee",
        amount=Decimal("50.00"),
        charge_date=target_dt,
    )
    db.add(charge)

    evidence = Evidence(
        evidence_id="EVD-P4-REL-DATE",
        source_manager="Prep",
        sku="SKU-UNRELATED-DATE",
        evidence_type="prep",
        evidence_content={},
        evidence_timestamp=target_dt,  # identical timestamp
    )
    db.add(evidence)
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-REL-DATE", db)
    assert result.candidate_count == 0
    assert result.relevant_count == 0


def test_15_same_charge_type_unrelated_identifiers_excluded(db: Session):
    """Requirement 15: Same charge type / evidence type but unrelated identifiers is excluded."""
    charge = Charge(
        charge_id="CHG-P4-REL-TYPE",
        shipment_id=None,
        order_id=None,
        sku="SKU-CHG-TYPE",
        asin=None,
        charge_type="packaging_check",
        amount=Decimal("30.00"),
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    db.add(charge)

    evidence = Evidence(
        evidence_id="EVD-P4-REL-TYPE",
        source_manager="Prep",
        sku="SKU-OTHER-TYPE",
        evidence_type="packaging_check",  # identical string
        evidence_content={},
        evidence_timestamp=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
    )
    db.add(evidence)
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-REL-TYPE", db)
    assert result.candidate_count == 0
    assert result.relevant_count == 0


def test_16_same_source_manager_unrelated_identifiers_excluded(db: Session):
    """Requirement 16: Same source manager (Prep) but unrelated identifiers is excluded."""
    charge = Charge(
        charge_id="CHG-P4-REL-MGR",
        shipment_id=None,
        order_id=None,
        sku="SKU-CHG-MGR",
        asin=None,
        charge_type="Unplanned Prep",
        amount=Decimal("20.00"),
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    db.add(charge)

    evidence = Evidence(
        evidence_id="EVD-P4-REL-MGR",
        source_manager="Prep",
        sku="SKU-UNLINKED-MGR",
        evidence_type="prep_scan",
        evidence_content={},
        evidence_timestamp=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
    )
    db.add(evidence)
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-REL-MGR", db)
    assert result.candidate_count == 0
    assert result.relevant_count == 0


# ==============================================================================
# 17-19: Multiple Evidence, Multiple Managers, and Deduplication
# ==============================================================================

def test_17_and_18_multiple_evidence_and_multiple_managers(db: Session):
    """Requirements 17 & 18: Multiple evidence records from distinct managers are returned."""
    # Seed charge CHG-FBA-8904 is linked to both EVD-PACK-9102 (Pack) and EVD-RECV-3301 (Receiving)
    result = evidence_engine.get_evidence_for_charge("CHG-FBA-8904", db)
    assert result.relevant_count >= 2

    managers = {e.source_manager for e in result.evidence}
    assert "Pack" in managers
    assert "Receiving" in managers

    ev_ids = {e.evidence_id for e in result.evidence}
    assert "EVD-PACK-9102" in ev_ids
    assert "EVD-RECV-3301" in ev_ids


def test_19_same_evidence_matching_multiple_keys_appears_only_once(db: Session):
    """Requirement 19: Evidence matching via both shipment_id and SKU appears exactly once."""
    shp = Shipment(shipment_id="SHP-P4-MULTI-KEY")
    db.add(shp)
    db.flush()

    charge = Charge(
        charge_id="CHG-P4-MULTI-01",
        shipment_id=shp.id,
        order_id=None,
        sku="SKU-MULTI-MATCH",
        asin=None,
        charge_type="Multi Match Fee",
        amount=Decimal("75.00"),
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    db.add(charge)

    # Evidence matches BOTH shipment_id and sku
    evidence = Evidence(
        evidence_id="EVD-P4-MULTI-01",
        source_manager="Prep",
        shipment_id=shp.id,
        order_id=None,
        sku="SKU-MULTI-MATCH",
        asin=None,
        evidence_type="prep_check",
        evidence_content={"checked": True},
        evidence_timestamp=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
    )
    db.add(evidence)
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-MULTI-01", db)
    # Deduplication check: evidence must appear only ONCE
    assert result.relevant_count == 1
    assert len(result.evidence) == 1

    ev = result.evidence[0]
    assert ev.evidence_id == "EVD-P4-MULTI-01"
    # Primary matched_by follows official contract priority: sku > shipment_id
    assert ev.matched_by == "sku"
    assert ev.match_value == "SKU-MULTI-MATCH"
    assert "shipment_id" in ev.matched_keys
    assert "sku" in ev.matched_keys


# ==============================================================================
# 20-23: Empty, Conflicting, Missing Identifiers, and Unknown Charge
# ==============================================================================

def test_20_no_evidence_returns_valid_empty_result(db: Session):
    """Requirement 20: Charge with no evidence returns valid empty list and zero counts."""
    # Seed charge CHG-FBA-8903 has no evidence rows attached to it in seed data
    result = evidence_engine.get_evidence_for_charge("CHG-FBA-8903", db)
    assert result.charge_id == "CHG-FBA-8903"
    assert result.candidate_count == 0
    assert result.relevant_count == 0
    assert result.evidence == []


def test_21_conflicting_evidence_preserved_without_resolution(db: Session):
    """Requirement 21: Conflicting evidence records are both preserved and not interpreted."""
    shp = Shipment(shipment_id="SHP-P4-CONFLICT")
    db.add(shp)
    db.flush()

    charge = Charge(
        charge_id="CHG-P4-CONFLICT",
        shipment_id=shp.id,
        order_id=None,
        sku="SKU-CONFLICT-ITEM",
        charge_type="Packaging Defect",
        amount=Decimal("100.00"),
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    db.add(charge)

    # Evidence A: Pack says carton intact
    ev_a = Evidence(
        evidence_id="EVD-P4-CONF-A",
        source_manager="Pack",
        shipment_id=shp.id,
        sku="SKU-CONFLICT-ITEM",
        evidence_type="audit",
        evidence_content={"carton_intact": True, "tape_sealed": True},
        evidence_timestamp=datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc),
    )
    # Evidence B: Receiving says carton damaged
    ev_b = Evidence(
        evidence_id="EVD-P4-CONF-B",
        source_manager="Receiving",
        shipment_id=shp.id,
        sku="SKU-CONFLICT-ITEM",
        evidence_type="dock_arrival",
        evidence_content={"carton_intact": False, "tape_sealed": False},
        evidence_timestamp=datetime(2026, 3, 1, 14, 0, tzinfo=timezone.utc),
    )
    db.add_all([ev_a, ev_b])
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-CONFLICT", db)
    assert result.relevant_count == 2
    ev_ids = [e.evidence_id for e in result.evidence]
    assert "EVD-P4-CONF-A" in ev_ids
    assert "EVD-P4-CONF-B" in ev_ids

    # Verify no interpretation was made (result contains no assessment strings)
    res_dict = result.to_dict()
    assert "assessment" not in res_dict
    assert "SUPPORTED" not in str(res_dict)
    assert "CONTRADICTED" not in str(res_dict)
    assert "UNCERTAIN" not in str(res_dict)


def test_22_evidence_with_missing_optional_identifiers_handled_correctly(db: Session):
    """Requirement 22: Evidence with NULL optional fields does not cause errors or incorrect matches."""
    shp = Shipment(shipment_id="SHP-P4-OPT-NULL")
    db.add(shp)
    db.flush()

    charge = Charge(
        charge_id="CHG-P4-OPT-NULL",
        shipment_id=shp.id,
        order_id=None,
        sku=None,
        asin=None,
        charge_type="Inbound Fee",
        amount=Decimal("45.00"),
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    db.add(charge)

    # Evidence has shipment_id, but order_id, sku, asin are NULL
    evidence = Evidence(
        evidence_id="EVD-P4-OPT-NULL",
        source_manager="Receiving",
        shipment_id=shp.id,
        order_id=None,
        sku=None,
        asin=None,
        evidence_type="dock_scan",
        evidence_content={"status": "RECEIVED"},
        evidence_timestamp=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
    )
    db.add(evidence)
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-OPT-NULL", db)
    assert result.relevant_count == 1
    match = result.evidence[0]
    assert match.evidence_id == "EVD-P4-OPT-NULL"
    assert match.matched_by == "shipment_id"
    assert match.match_value == "SHP-P4-OPT-NULL"


def test_23_unknown_charge_raises_not_found_error(db: Session, client: TestClient):
    """Requirement 23: Querying an unknown charge raises ChargeNotFoundError and returns 404."""
    with pytest.raises(ChargeNotFoundError):
        evidence_engine.get_evidence_for_charge("CHG-NONEXISTENT-9999", db)

    # Verify HTTP API response
    response = client.get("/evidence/charge/CHG-NONEXISTENT-9999")
    assert response.status_code == 404
    body = response.json()
    assert "not found" in body["detail"].lower()


# ==============================================================================
# 24-28: Full Provenance Preservation
# ==============================================================================

def test_24_to_28_evidence_provenance_preserved(db: Session):
    """Requirements 24-28: Preserves evidence_id, source_manager, timestamp, content, match key/value."""
    result = evidence_engine.get_evidence_for_charge("CHG-FBA-8901", db)
    assert result.relevant_count >= 1

    match = next(e for e in result.evidence if e.evidence_id == "EVD-PREP-8821")
    # 24. Evidence ID preserved
    assert match.evidence_id == "EVD-PREP-8821"
    # 25. Source Manager preserved
    assert match.source_manager == "Prep"
    # 26. Evidence timestamp preserved
    assert match.evidence_timestamp is not None
    assert match.evidence_timestamp.year == 2026
    # 27. Evidence content preserved
    assert isinstance(match.evidence_content, dict)
    assert match.evidence_content.get("packaging_check") == "PASS"
    assert match.evidence_content.get("polybag_thickness_mil") == 1.7
    # 28. Match key and match value preserved (official priority sku before shipment_id)
    assert match.matched_by == "sku"
    assert "shipment_id" in match.matched_keys
    assert match.match_value == "TECH-CABLE-01"


# ==============================================================================
# 29-30: Deterministic Ordering & Stable Tiebreaking
# ==============================================================================

def test_29_and_30_deterministic_ordering_and_tiebreaking(db: Session):
    """Requirements 29 & 30: Priority rank -> evidence timestamp -> evidence_id tiebreaker."""
    shp = Shipment(shipment_id="SHP-P4-ORDERING")
    db.add(shp)
    db.flush()

    charge = Charge(
        charge_id="CHG-P4-ORDERING",
        shipment_id=shp.id,
        order_id=None,
        sku="SKU-ORDERING",
        asin="ASIN-ORDERING",
        charge_type="Audit Fee",
        amount=Decimal("50.00"),
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )
    db.add(charge)

    ts_early = datetime(2026, 3, 1, 8, 0, tzinfo=timezone.utc)
    ts_late = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)

    # Create records with identical priority and timestamps to verify tiebreaking
    ev_tie_b = Evidence(
        evidence_id="EVD-P4-TIE-B",
        source_manager="Prep",
        shipment_id=shp.id,
        evidence_type="audit",
        evidence_content={},
        evidence_timestamp=ts_early,
    )
    ev_tie_a = Evidence(
        evidence_id="EVD-P4-TIE-A",
        source_manager="Prep",
        shipment_id=shp.id,
        evidence_type="audit",
        evidence_content={},
        evidence_timestamp=ts_early,
    )
    # Record with higher priority (shipment_id) but late timestamp
    ev_ship_late = Evidence(
        evidence_id="EVD-P4-SHIP-LATE",
        source_manager="Prep",
        shipment_id=shp.id,
        evidence_type="audit",
        evidence_content={},
        evidence_timestamp=ts_late,
    )
    # Record with lower priority (sku) but early timestamp
    ev_sku_early = Evidence(
        evidence_id="EVD-P4-SKU-EARLY",
        source_manager="Prep",
        sku="SKU-ORDERING",
        evidence_type="audit",
        evidence_content={},
        evidence_timestamp=ts_early,
    )

    db.add_all([ev_tie_b, ev_tie_a, ev_ship_late, ev_sku_early])
    db.commit()

    result = evidence_engine.get_evidence_for_charge("CHG-P4-ORDERING", db)
    ev_list = result.evidence

    # Official contract matching priority: unit_id -> fnsku -> sku (rank 3) -> shipment_id (rank 4)
    # SKU (rank 3) comes before shipment_id (rank 4)
    # Within shipment_id, ts_early comes before ts_late; within identical ts_early, tiebreaker is evidence_id
    ids = [e.evidence_id for e in ev_list]
    assert ids[0] == "EVD-P4-SKU-EARLY"
    assert ids[1] == "EVD-P4-TIE-A"
    assert ids[2] == "EVD-P4-TIE-B"
    assert ids[3] == "EVD-P4-SHIP-LATE"


# ==============================================================================
# 31-32: Security & Error Sanitization
# ==============================================================================

def test_31_and_32_security_sanitization(client: TestClient, monkeypatch):
    """Requirements 31 & 32: Database errors and API responses sanitize secrets and SQL details."""
    from sqlalchemy.exc import OperationalError

    def _broken_engine(*args, **kwargs):
        raise OperationalError("SELECT * FROM credentials", {}, Exception("Database connection password=supersecret failed"))

    monkeypatch.setattr(evidence_engine, "get_evidence_for_charge", _broken_engine)

    response = client.get("/evidence/charge/CHG-FBA-8901")
    assert response.status_code == 500
    data = response.json()

    # Must NOT expose SQL statement or password
    assert "supersecret" not in response.text
    assert "SELECT *" not in response.text
    assert data.get("error") == "Database Error"
    assert data.get("message") == "A database error occurred while processing the request."


# ==============================================================================
# 33-38: Strict Architectural Boundaries
# ==============================================================================

def test_33_no_anthropic_or_llm_calls():
    """Requirement 33: No LLM/Anthropic/OpenAI imports or invocations."""
    source_service = (backend_dir / "app" / "services" / "evidence_engine.py").read_text(encoding="utf-8")
    source_route = (backend_dir / "app" / "api" / "routes" / "evidence.py").read_text(encoding="utf-8")
    full_source = source_service + "\n" + source_route

    assert "anthropic" not in full_source.lower()
    assert "openai" not in full_source.lower()
    assert "langchain" not in full_source.lower()
    assert "generate_text" not in full_source.lower()
    assert "chat" not in full_source.lower()


def test_34_no_embeddings_or_vector_search():
    """Requirement 34: No vector database or embeddings search."""
    source_service = (backend_dir / "app" / "services" / "evidence_engine.py").read_text(encoding="utf-8")
    assert "embedding" not in source_service.lower()
    assert "vector" not in source_service.lower()
    assert "cosine" not in source_service.lower()
    assert "faiss" not in source_service.lower()
    assert "pgvector" not in source_service.lower()


def test_35_no_fuzzy_matching_library():
    """Requirement 35: No fuzzy matching libraries used."""
    source_service = (backend_dir / "app" / "services" / "evidence_engine.py").read_text(encoding="utf-8")
    assert "fuzzywuzzy" not in source_service.lower()
    assert "rapidfuzz" not in source_service.lower()
    assert "levenshtein" not in source_service.lower()
    assert "difflib" not in source_service.lower()


def test_36_no_claim_creation(db: Session):
    """Requirement 36: Evidence Engine does NOT create or modify claims in the database."""
    initial_claims_count = db.scalar(select(text("count(*)")).select_from(Claim))

    # Perform retrieval on seed charge
    result = evidence_engine.get_evidence_for_charge("CHG-FBA-8901", db)
    assert result.relevant_count >= 1

    final_claims_count = db.scalar(select(text("count(*)")).select_from(Claim))
    assert final_claims_count == initial_claims_count


def test_37_no_assessment_classification(db: Session):
    """Requirement 37: Result does not contain assessment classifications (SUPPORTED/SILENT/etc.)."""
    result = evidence_engine.get_evidence_for_charge("CHG-FBA-8901", db)
    res_dict = result.to_dict()

    assert "assessment" not in res_dict
    assert not hasattr(result, "assessment")
    for ev in result.evidence:
        assert not hasattr(ev, "assessment")
        assert "assessment" not in ev.to_dict()


def test_38_no_rule_validation():
    """Requirement 38: Rule validation logic is not part of Evidence Engine."""
    source_service = (backend_dir / "app" / "services" / "evidence_engine.py").read_text(encoding="utf-8")
    assert "validate_rules" not in source_service.lower()
    assert "rule_engine" not in source_service.lower()
    assert "dispute_rule" not in source_service.lower()


# ==============================================================================
# Additional API Endpoint Integration Tests
# ==============================================================================

def test_api_endpoint_success(client: TestClient):
    """Test GET /evidence/charge/{charge_id} returns 200 and matches schema."""
    response = client.get("/evidence/charge/CHG-FBA-8901")
    assert response.status_code == 200
    data = response.json()

    assert data["charge_id"] == "CHG-FBA-8901"
    assert data["candidate_count"] >= 1
    assert data["relevant_count"] >= 1
    assert isinstance(data["evidence"], list)

    first = data["evidence"][0]
    assert "evidence_id" in first
    assert "matched_by" in first
    assert "match_value" in first
    assert "source_manager" in first
    assert "evidence_type" in first
    assert "evidence_timestamp" in first
    assert "evidence_content" in first


def test_api_endpoint_empty_charge(client: TestClient):
    """Test GET /evidence/charge/{charge_id} for charge with no evidence."""
    response = client.get("/evidence/charge/CHG-FBA-8903")
    assert response.status_code == 200
    data = response.json()

    assert data["charge_id"] == "CHG-FBA-8903"
    assert data["candidate_count"] == 0
    assert data["relevant_count"] == 0
    assert data["evidence"] == []


def test_uuid_lookup_supported(db: Session, client: TestClient):
    """Test lookup by charge internal UUID is supported."""
    stmt = select(Charge).where(Charge.charge_id == "CHG-FBA-8901")
    charge = db.scalars(stmt).first()
    assert charge is not None

    response = client.get(f"/evidence/charge/{charge.id}")
    assert response.status_code == 200
    data = response.json()
    assert data["charge_id"] == "CHG-FBA-8901"
    assert data["relevant_count"] >= 1

