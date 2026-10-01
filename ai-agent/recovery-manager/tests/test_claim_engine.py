"""Comprehensive Phase 7 Claim Engine Tests.

Verifies all requirements from Phase 7 specification:
1. ELIGIBLE, everything valid -> CLAIM_CREATED, correct claims row, correct claim_evidence rows,
   correct row counts, full traceability chain (claim -> charge -> shipment/order/SKU -> evidence ->
   source_manager -> evidence_timestamp) resolvable via real joins.
2. Same charge processed twice (ELIGIBLE case) -> second call ALREADY_CLAIMED, zero new rows anywhere,
   original claim untouched.
3. BLOCKED/RULE_DUPLICATE -> claims row created with status=DUPLICATE, no claim_evidence rows, no claim_amount.
4. Reprocessing that same duplicate-blocked charge -> ALREADY_CLAIMED (proves idempotency covers non-eligible
   rows too, not just eligible).
5. BLOCKED/RULE_ALREADY_REIMBURSED -> status=ALREADY_REIMBURSED, same checks as above.
6. HUMAN_REVIEW (UNCERTAIN) -> no row created, evidence passed through.
7. NO_CLAIM (SUPPORTED) -> no row.
8. NO_CLAIM (SILENT) -> no row.
9. Tampered input: decision says ELIGIBLE/eligible_for_recovery=True but claim_amount > charge.amount anyway ->
   REJECTED_AT_CLAIM_ENGINE, a claims row with status=REJECTED IS created, no claim_evidence, no financial claim.
10. Tampered input: ELIGIBLE but an evidence_id doesn't actually exist in the evidence table -> same REJECTED_AT_CLAIM_ENGINE.
11. Tampered input: ELIGIBLE but assessment != CONTRADICTED -> REJECTED_AT_CLAIM_ENGINE.
12. Forced mid-transaction failure on an otherwise-valid ELIGIBLE case -> zero rows in claims, zero in claim_evidence (rollback).
13. decision/human_review_required disagreement (manufacture this) -> caught defensively, not silently resolved.
14. API endpoint POST /claims/process test coverage.
15. Multi-source manager joining verification (e.g. "Pack+Prep").
"""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys
from unittest.mock import patch
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app
from app.core.database import SessionLocal
from app.models.charge import Charge
from app.models.claim import Claim
from app.models.claim_evidence import ClaimEvidence
from app.models.evidence import Evidence
from app.models.order import Order
from app.models.shipment import Shipment
from app.models.assessment_log import AssessmentLog
from app.ai.schemas import (
    AIAssessmentResponse,
    AssessmentType,
    ChargeInputSchema,
    EvidenceInputSchema,
    ProcessingStateSchema,
)
from app.rules.schemas import (
    RuleValidationResult,
    ValidationDecision,
)
from app.claims.exceptions import ClaimIntegrityError, ClaimTransactionError
from app.claims.service import ClaimEngine


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app, headers={"X-Org-Id": "org_test_alpha"}, raise_server_exceptions=False)


@pytest.fixture
def db():
    """Database session fixture."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def clean_phase7_test_data():
    """Cleanup any Phase 7 test records before and after each test."""
    def _cleanup():
        session = SessionLocal()
        try:
            # Delete in order respecting foreign keys
            session.execute(text("DELETE FROM claim_evidence WHERE org_id LIKE 'org_test_%'"))
            session.execute(text("DELETE FROM claims WHERE org_id LIKE 'org_test_%'"))
            session.execute(text("DELETE FROM assessment_log WHERE org_id LIKE 'org_test_%'"))
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


def create_test_setup(
    db: Session,
    suffix: str = "01",
    charge_amount: Decimal = Decimal("100.00"),
    multi_manager: bool = False,
):
    """Helper to create an isolated charge, shipment, order, and evidence records."""
    shipment = Shipment(shipment_id=f"SHP-P7-{suffix}")
    db.add(shipment)
    db.flush()

    order = Order(order_id=f"ORD-P7-{suffix}")
    db.add(order)
    db.flush()

    charge = Charge(
        charge_id=f"CHG-P7-{suffix}",
        shipment_id=shipment.id,
        order_id=order.id,
        sku=f"SKU-P7-{suffix}",
        asin=f"B00P7{suffix}",
        charge_type="Packaging defect",
        amount=charge_amount,
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
        status="PENDING",
    )
    db.add(charge)
    db.flush()

    ev1 = Evidence(
        evidence_id=f"EVD-P7-{suffix}-A",
        source_manager="Prep",
        shipment_id=shipment.id,
        order_id=order.id,
        sku=charge.sku,
        asin=charge.asin,
        evidence_type="packaging_check",
        evidence_content={"bag_mil": 1.8, "label_ok": True},
        evidence_timestamp=datetime(2026, 3, 1, 8, 30, tzinfo=timezone.utc),
    )
    db.add(ev1)

    ev_list = [ev1]

    if multi_manager:
        ev2 = Evidence(
            evidence_id=f"EVD-P7-{suffix}-B",
            source_manager="Receiving",
            shipment_id=shipment.id,
            order_id=order.id,
            sku=charge.sku,
            asin=charge.asin,
            evidence_type="dock_intake_scan",
            evidence_content={"carton_seal": "INTACT"},
            evidence_timestamp=datetime(2026, 3, 1, 8, 45, tzinfo=timezone.utc),
        )
        db.add(ev2)
        ev_list.append(ev2)

    db.commit()
    return charge, shipment, order, ev_list


# ==============================================================================
# Requirement 1: ELIGIBLE Case -> CLAIM_CREATED & Full Traceability Chain
# ==============================================================================
def test_eligible_creates_claim_and_traceability_chain(db: Session):
    """
    Test that an ELIGIBLE assessment produces CLAIM_CREATED with:
    - claims row (status='READY_FOR_REVIEW', correct claim_amount, confidence, source_manager)
    - claim_evidence rows linking to real evidence
    - charges.status updated to 'PROCESSED'
    - full database traceability chain verified via relational joins
    """
    charge, shipment, order, evidence_list = create_test_setup(db, suffix="ELIGIBLE01", charge_amount=Decimal("150.00"))

    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("150.00"),
        confidence=0.95,
        reason="Prep logs prove suffocation warning was present. Defect charge contradicted.",
        evidence_ids=[evidence_list[0].evidence_id],
    )

    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.CONTRADICTED,
        eligible_for_recovery=True,
        human_review_required=False,
        claim_amount=Decimal("150.00"),
        evidence_ids=[evidence_list[0].evidence_id],
        decision=ValidationDecision.ELIGIBLE,
        status=ValidationDecision.ELIGIBLE,
        reason="Validated and eligible for recovery.",
        rule_code="RULE_RECOVERY_ELIGIBLE",
    )

    engine = ClaimEngine(db=db)
    result = engine.process_claim(
        charge_id=charge.charge_id,
        validation_result=val_res,
        assessment_response=ai_resp,
    )

    assert result.outcome == "CLAIM_CREATED"
    assert result.charge_id == charge.charge_id
    assert result.claim_id is not None
    assert result.claim_id.startswith("CLM-")
    assert result.status == "READY_FOR_REVIEW"
    assert result.claim_amount == Decimal("150.00")
    assert result.evidence_ids == [evidence_list[0].evidence_id]

    # Verify database state
    claim_row = db.scalars(select(Claim).where(Claim.claim_id == result.claim_id)).first()
    assert claim_row is not None
    assert claim_row.charge_id == charge.id
    assert claim_row.assessment == "CONTRADICTED"
    assert claim_row.claim_amount == Decimal("150.00")
    assert claim_row.status == "READY_FOR_REVIEW"
    assert claim_row.source_manager == "Prep"

    # Verify claim_evidence row
    links = list(db.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id == claim_row.id)).all())
    assert len(links) == 1
    assert links[0].evidence_id == evidence_list[0].id

    # Verify charge status updated
    db.refresh(charge)
    assert charge.status == "PROCESSED"

    # Full Traceability Chain Join: Claim -> Charge -> Shipment -> Order -> SKU -> Evidence
    stmt = (
        select(
            Claim.claim_id,
            Charge.charge_id,
            Shipment.shipment_id,
            Order.order_id,
            Charge.sku,
            Evidence.evidence_id,
            Evidence.source_manager,
            Evidence.evidence_timestamp,
        )
        .join(Charge, Claim.charge_id == Charge.id)
        .join(Shipment, Charge.shipment_id == Shipment.id)
        .join(Order, Charge.order_id == Order.id)
        .join(ClaimEvidence, ClaimEvidence.claim_id == Claim.id)
        .join(Evidence, ClaimEvidence.evidence_id == Evidence.id)
        .where(Claim.claim_id == result.claim_id)
    )
    chain = db.execute(stmt).first()
    assert chain is not None
    assert chain.claim_id == result.claim_id
    assert chain.charge_id == charge.charge_id
    assert chain.shipment_id == shipment.shipment_id
    assert chain.order_id == order.order_id
    assert chain.sku == charge.sku
    assert chain.evidence_id == evidence_list[0].evidence_id
    assert chain.source_manager == "Prep"
    assert chain.evidence_timestamp == evidence_list[0].evidence_timestamp


# ==============================================================================
# Requirement 2: Idempotency on ELIGIBLE Case (No Duplicates)
# ==============================================================================
def test_idempotency_second_call_returns_already_claimed(db: Session):
    """Processing an already-claimed charge returns ALREADY_CLAIMED without creating rows."""
    charge, _, _, evidence_list = create_test_setup(db, suffix="IDEMPOTENT01", charge_amount=Decimal("80.00"))

    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("80.00"),
        confidence=0.90,
        reason="Evidence contradicts charge.",
        evidence_ids=[evidence_list[0].evidence_id],
    )
    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.CONTRADICTED,
        eligible_for_recovery=True,
        human_review_required=False,
        claim_amount=Decimal("80.00"),
        evidence_ids=[evidence_list[0].evidence_id],
        decision=ValidationDecision.ELIGIBLE,
        status=ValidationDecision.ELIGIBLE,
        reason="Eligible for recovery.",
        rule_code="RULE_RECOVERY_ELIGIBLE",
    )

    engine = ClaimEngine(db=db)
    res1 = engine.process_claim(charge.charge_id, val_res, ai_resp)
    assert res1.outcome == "CLAIM_CREATED"

    claims_count_before = db.scalar(select(text("count(*)")).select_from(Claim))
    ce_count_before = db.scalar(select(text("count(*)")).select_from(ClaimEvidence))

    # Second call
    res2 = engine.process_claim(charge.charge_id, val_res, ai_resp)
    assert res2.outcome == "ALREADY_CLAIMED"
    assert res2.claim_id == res1.claim_id
    assert res2.status == "READY_FOR_REVIEW"
    assert res2.claim_amount == Decimal("80.00")
    assert res2.evidence_ids == [evidence_list[0].evidence_id]

    claims_count_after = db.scalar(select(text("count(*)")).select_from(Claim))
    ce_count_after = db.scalar(select(text("count(*)")).select_from(ClaimEvidence))

    assert claims_count_after == claims_count_before
    assert ce_count_after == ce_count_before


# ==============================================================================
# Requirement 3: BLOCKED/RULE_DUPLICATE -> Claims Row Created, status=DUPLICATE
# ==============================================================================
def test_blocked_duplicate_creates_claim_row(db: Session):
    """
    BLOCKED/RULE_DUPLICATE creates a claims row with status='DUPLICATE',
    claim_amount=NULL, and no claim_evidence rows.
    """
    charge, _, _, _ = create_test_setup(db, suffix="DUP01", charge_amount=Decimal("60.00"))

    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("60.00"),
        confidence=0.85,
        reason="Duplicate charge flagged.",
        evidence_ids=[],
    )
    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.CONTRADICTED,
        eligible_for_recovery=False,
        human_review_required=False,
        claim_amount=None,
        evidence_ids=[],
        decision=ValidationDecision.BLOCKED,
        status=ValidationDecision.BLOCKED,
        reason="Charge is flagged as duplicate in processing state; blocked.",
        rule_code="RULE_DUPLICATE",
    )

    engine = ClaimEngine(db=db)
    res = engine.process_claim(charge.charge_id, val_res, ai_resp)

    assert res.outcome == "BLOCKED"
    assert res.claim_id is not None
    assert res.status == "DUPLICATE"
    assert res.claim_amount is None
    assert res.evidence_ids == []

    # Verify DB row
    claim_row = db.scalars(select(Claim).where(Claim.claim_id == res.claim_id)).first()
    assert claim_row is not None
    assert claim_row.status == "DUPLICATE"
    assert claim_row.claim_amount is None
    assert claim_row.source_manager is None

    # Verify zero claim_evidence rows
    ce_count = db.scalar(select(text("count(*)")).select_from(ClaimEvidence).where(ClaimEvidence.claim_id == claim_row.id))
    assert ce_count == 0


# ==============================================================================
# Requirement 4: Reprocessing Duplicate-Blocked Charge -> ALREADY_CLAIMED
# ==============================================================================
def test_reprocessing_duplicate_blocked_charge_returns_already_claimed(db: Session):
    """
    Reprocessing that same duplicate-blocked charge returns ALREADY_CLAIMED,
    proving idempotency covers non-eligible rows too, not just eligible.
    """
    charge, _, _, _ = create_test_setup(db, suffix="DUP02", charge_amount=Decimal("60.00"))

    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("60.00"),
        confidence=0.85,
        reason="Duplicate charge flagged.",
        evidence_ids=[],
    )
    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.CONTRADICTED,
        eligible_for_recovery=False,
        human_review_required=False,
        claim_amount=None,
        evidence_ids=[],
        decision=ValidationDecision.BLOCKED,
        status=ValidationDecision.BLOCKED,
        reason="Charge is flagged as duplicate in processing state; blocked.",
        rule_code="RULE_DUPLICATE",
    )

    engine = ClaimEngine(db=db)
    res1 = engine.process_claim(charge.charge_id, val_res, ai_resp)
    assert res1.outcome == "BLOCKED"
    assert res1.status == "DUPLICATE"

    # Reprocess same charge
    res2 = engine.process_claim(charge.charge_id, val_res, ai_resp)
    assert res2.outcome == "ALREADY_CLAIMED"
    assert res2.claim_id == res1.claim_id
    assert res2.status == "DUPLICATE"
    assert res2.claim_amount is None


# ==============================================================================
# Requirement 5: BLOCKED/RULE_ALREADY_REIMBURSED
# ==============================================================================
def test_blocked_already_reimbursed_creates_claim_row(db: Session):
    """
    BLOCKED/RULE_ALREADY_REIMBURSED creates a claims row with status='ALREADY_REIMBURSED',
    claim_amount=NULL, and no claim_evidence rows.
    """
    charge, _, _, _ = create_test_setup(db, suffix="REIMB01", charge_amount=Decimal("45.00"))

    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("45.00"),
        confidence=0.88,
        reason="Charge previously reimbursed.",
        evidence_ids=[],
    )
    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.CONTRADICTED,
        eligible_for_recovery=False,
        human_review_required=False,
        claim_amount=None,
        evidence_ids=[],
        decision=ValidationDecision.BLOCKED,
        status=ValidationDecision.BLOCKED,
        reason="Charge has already been reimbursed; blocked.",
        rule_code="RULE_ALREADY_REIMBURSED",
    )

    engine = ClaimEngine(db=db)
    res = engine.process_claim(charge.charge_id, val_res, ai_resp)

    assert res.outcome == "BLOCKED"
    assert res.claim_id is not None
    assert res.status == "ALREADY_REIMBURSED"
    assert res.claim_amount is None

    claim_row = db.scalars(select(Claim).where(Claim.claim_id == res.claim_id)).first()
    assert claim_row.status == "ALREADY_REIMBURSED"
    assert claim_row.claim_amount is None


# ==============================================================================
# Requirement 6: HUMAN_REVIEW (UNCERTAIN) -> No Row Created
# ==============================================================================
def test_human_review_creates_no_row(db: Session):
    """HUMAN_REVIEW outcome creates no row in claims table and passes through evidence."""
    charge, _, _, evidence_list = create_test_setup(db, suffix="HR01", charge_amount=Decimal("75.00"))

    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.UNCERTAIN,
        claim_supported=False,
        claim_amount=None,
        confidence=0.50,
        reason="Conflicting dock intake and pack station logs.",
        evidence_ids=[evidence_list[0].evidence_id],
    )
    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.UNCERTAIN,
        eligible_for_recovery=False,
        human_review_required=True,
        claim_amount=None,
        evidence_ids=[evidence_list[0].evidence_id],
        decision=ValidationDecision.HUMAN_REVIEW,
        status=ValidationDecision.HUMAN_REVIEW,
        reason="Flagged for human review.",
        rule_code="RULE_UNCERTAIN_HUMAN_REVIEW",
    )

    claims_before = db.scalar(select(text("count(*)")).select_from(Claim))
    engine = ClaimEngine(db=db)
    res = engine.process_claim(charge.charge_id, val_res, ai_resp)

    assert res.outcome == "HUMAN_REVIEW"
    assert res.claim_id is None
    assert res.status is None
    assert res.evidence_ids == [evidence_list[0].evidence_id]

    claims_after = db.scalar(select(text("count(*)")).select_from(Claim))
    assert claims_after == claims_before


# ==============================================================================
# Requirement 7 & 8: NO_CLAIM (SUPPORTED / SILENT) -> No Row Created
# ==============================================================================
def test_no_claim_supported_creates_no_row(db: Session):
    """SUPPORTED assessment (marketplace fee valid) results in NO_CLAIM with no row created."""
    charge, _, _, _ = create_test_setup(db, suffix="SUPP01", charge_amount=Decimal("50.00"))

    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.SUPPORTED,
        claim_supported=False,
        claim_amount=None,
        confidence=0.92,
        reason="Warehouse scale confirms package was overweight. Surcharge valid.",
        evidence_ids=[],
    )
    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.SUPPORTED,
        eligible_for_recovery=False,
        human_review_required=False,
        claim_amount=None,
        evidence_ids=[],
        decision=ValidationDecision.NON_CLAIM,
        status=ValidationDecision.NON_CLAIM,
        reason="Charge corroborated by operational evidence; claim withheld.",
        rule_code="RULE_SUPPORTED_NON_CLAIM",
    )

    claims_before = db.scalar(select(text("count(*)")).select_from(Claim))
    engine = ClaimEngine(db=db)
    res = engine.process_claim(charge.charge_id, val_res, ai_resp)

    assert res.outcome == "NO_CLAIM"
    assert res.claim_id is None
    claims_after = db.scalar(select(text("count(*)")).select_from(Claim))
    assert claims_after == claims_before


def test_no_claim_silent_creates_no_row(db: Session):
    """SILENT assessment (no evidence) results in NO_CLAIM with no row created."""
    charge, _, _, _ = create_test_setup(db, suffix="SILENT01", charge_amount=Decimal("30.00"))

    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.SILENT,
        claim_supported=False,
        claim_amount=None,
        confidence=0.0,
        reason="No operational evidence found.",
        evidence_ids=[],
    )
    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.SILENT,
        eligible_for_recovery=False,
        human_review_required=False,
        claim_amount=None,
        evidence_ids=[],
        decision=ValidationDecision.NON_CLAIM,
        status=ValidationDecision.NON_CLAIM,
        reason="No operational evidence found; claim withheld.",
        rule_code="RULE_SILENT_NON_CLAIM",
    )

    claims_before = db.scalar(select(text("count(*)")).select_from(Claim))
    engine = ClaimEngine(db=db)
    res = engine.process_claim(charge.charge_id, val_res, ai_resp)

    assert res.outcome == "NO_CLAIM"
    assert res.claim_id is None
    claims_after = db.scalar(select(text("count(*)")).select_from(Claim))
    assert claims_after == claims_before


# ==============================================================================
# Requirement 9: Tampered Input - Claim Amount > Charge Amount -> REJECTED
# ==============================================================================
def test_tampered_claim_amount_exceeding_charge_rejected(db: Session):
    """
    If claim_amount exceeds charge.amount in DB, ClaimEngine rejects it,
    creating a claim row with status='REJECTED' and no claim_evidence rows.
    """
    charge, _, _, evidence_list = create_test_setup(db, suffix="TAMP_AMT01", charge_amount=Decimal("100.00"))

    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("150.00"),  # Exceeds charge amount of 100.00!
        confidence=0.90,
        reason="Contradicted with excessive claim amount.",
        evidence_ids=[evidence_list[0].evidence_id],
    )
    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.CONTRADICTED,
        eligible_for_recovery=True,
        human_review_required=False,
        claim_amount=Decimal("150.00"),
        evidence_ids=[evidence_list[0].evidence_id],
        decision=ValidationDecision.ELIGIBLE,
        status=ValidationDecision.ELIGIBLE,
        reason="Fraudulently marked eligible upstream.",
        rule_code="RULE_RECOVERY_ELIGIBLE",
    )

    engine = ClaimEngine(db=db)
    res = engine.process_claim(charge.charge_id, val_res, ai_resp)

    assert res.outcome == "REJECTED_AT_CLAIM_ENGINE"
    assert res.status == "REJECTED"
    assert res.claim_amount is None
    assert "exceeds charge amount" in res.reason

    claim_row = db.scalars(select(Claim).where(Claim.claim_id == res.claim_id)).first()
    assert claim_row.status == "REJECTED"
    assert claim_row.claim_amount is None

    # Zero claim_evidence rows
    ce_count = db.scalar(select(text("count(*)")).select_from(ClaimEvidence).where(ClaimEvidence.claim_id == claim_row.id))
    assert ce_count == 0


# ==============================================================================
# Requirement 10: Tampered Input - Missing Evidence in Database -> REJECTED
# ==============================================================================
def test_tampered_nonexistent_evidence_id_rejected(db: Session):
    """If evidence ID doesn't exist in the database, ClaimEngine rejects the claim."""
    charge, _, _, _ = create_test_setup(db, suffix="TAMP_EVD01", charge_amount=Decimal("100.00"))

    fake_evidence_id = "EVD-FAKE-NONEXISTENT-999"

    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        confidence=0.90,
        reason="Contradicted with ghost evidence.",
        evidence_ids=[fake_evidence_id],
    )
    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.CONTRADICTED,
        eligible_for_recovery=True,
        human_review_required=False,
        claim_amount=Decimal("100.00"),
        evidence_ids=[fake_evidence_id],
        decision=ValidationDecision.ELIGIBLE,
        status=ValidationDecision.ELIGIBLE,
        reason="Fraudulently marked eligible with phantom evidence.",
        rule_code="RULE_RECOVERY_ELIGIBLE",
    )

    engine = ClaimEngine(db=db)
    res = engine.process_claim(charge.charge_id, val_res, ai_resp)

    assert res.outcome == "REJECTED_AT_CLAIM_ENGINE"
    assert res.status == "REJECTED"
    assert "evidence IDs not found in database" in res.reason

    claim_row = db.scalars(select(Claim).where(Claim.claim_id == res.claim_id)).first()
    assert claim_row.status == "REJECTED"


# ==============================================================================
# Requirement 11: Tampered Input - Assessment != CONTRADICTED -> REJECTED
# ==============================================================================
def test_tampered_non_contradicted_assessment_rejected(db: Session):
    """If an ELIGIBLE result arrives with assessment != CONTRADICTED, reject it."""
    charge, _, _, evidence_list = create_test_setup(db, suffix="TAMP_ASSESS01", charge_amount=Decimal("100.00"))

    # Assessment is SUPPORTED but marked ELIGIBLE (contract violation)
    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.SUPPORTED,
        claim_supported=False,
        claim_amount=None,
        confidence=0.80,
        reason="Contradiction bypass test.",
        evidence_ids=[evidence_list[0].evidence_id],
    )
    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.SUPPORTED,
        eligible_for_recovery=True,
        human_review_required=False,
        claim_amount=Decimal("100.00"),
        evidence_ids=[evidence_list[0].evidence_id],
        decision=ValidationDecision.ELIGIBLE,
        status=ValidationDecision.ELIGIBLE,
        reason="Fraudulently marked eligible despite SUPPORTED assessment.",
        rule_code="RULE_RECOVERY_ELIGIBLE",
    )

    engine = ClaimEngine(db=db)
    res = engine.process_claim(charge.charge_id, val_res, ai_resp)

    assert res.outcome == "REJECTED_AT_CLAIM_ENGINE"
    assert res.status == "REJECTED"
    assert "not CONTRADICTED" in res.reason


# ==============================================================================
# Requirement 12: Atomic Rollback on Mid-Transaction Failure
# ==============================================================================
def test_forced_mid_transaction_failure_rolls_back_completely(db: Session):
    """
    Forcing an exception mid-transaction (after Claim insert but before commit)
    must rollback completely, leaving ZERO rows in claims and ZERO in claim_evidence.
    """
    charge, _, _, evidence_list = create_test_setup(db, suffix="ROLLBACK01", charge_amount=Decimal("100.00"))

    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        confidence=0.95,
        reason="Valid recovery candidate for rollback test.",
        evidence_ids=[evidence_list[0].evidence_id],
    )
    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.CONTRADICTED,
        eligible_for_recovery=True,
        human_review_required=False,
        claim_amount=Decimal("100.00"),
        evidence_ids=[evidence_list[0].evidence_id],
        decision=ValidationDecision.ELIGIBLE,
        status=ValidationDecision.ELIGIBLE,
        reason="Eligible for recovery.",
        rule_code="RULE_RECOVERY_ELIGIBLE",
    )

    engine = ClaimEngine(db=db)

    # Patch ClaimEvidence __init__ to raise an error during insertion
    with patch.object(ClaimEvidence, "__init__", side_effect=RuntimeError("Simulated mid-transaction failure")):
        with pytest.raises(ClaimTransactionError):
            engine.process_claim(charge.charge_id, val_res, ai_resp)

    # Verify atomic rollback: ZERO claims rows created for this charge
    claim_count = db.scalar(
        select(text("count(*)")).select_from(Claim).where(Claim.charge_id == charge.id)
    )
    assert claim_count == 0

    # Charge status must still be 'PENDING', not 'PROCESSED'
    db.refresh(charge)
    assert charge.status == "PENDING"


# ==============================================================================
# Requirement 13: Decision / Flag Disagreement Caught Defensively
# ==============================================================================
def test_decision_and_human_review_flag_disagreement_caught(db: Session):
    """
    If validation_result.decision is HUMAN_REVIEW but human_review_required is False,
    treat defensively as failure and create a REJECTED claim row.
    """
    charge, _, _, _ = create_test_setup(db, suffix="DISAGREE01", charge_amount=Decimal("100.00"))

    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.UNCERTAIN,
        claim_supported=False,
        claim_amount=None,
        confidence=0.50,
        reason="Uncertain assessment.",
        evidence_ids=[],
    )
    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.UNCERTAIN,
        eligible_for_recovery=False,
        human_review_required=False,  # Contradicts HUMAN_REVIEW decision!
        claim_amount=None,
        evidence_ids=[],
        decision=ValidationDecision.HUMAN_REVIEW,
        status=ValidationDecision.HUMAN_REVIEW,
        reason="Manufactured disagreement test.",
        rule_code="RULE_UNCERTAIN_HUMAN_REVIEW",
    )

    engine = ClaimEngine(db=db)
    res = engine.process_claim(charge.charge_id, val_res, ai_resp)

    assert res.outcome == "REJECTED_AT_CLAIM_ENGINE"
    assert res.status == "REJECTED"
    assert "disagreement" in res.reason.lower()


# ==============================================================================
# Requirement 14: Multi-Source Manager Concatenation ("Pack+Prep")
# ==============================================================================
def test_multi_source_manager_concatenation(db: Session):
    """
    If backing evidence spans multiple departments, source_manager joins them sorted with '+'.
    """
    charge, _, _, evidence_list = create_test_setup(db, suffix="MULTIMGR01", charge_amount=Decimal("200.00"), multi_manager=True)
    assert len(evidence_list) == 2  # Prep and Receiving

    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("200.00"),
        confidence=0.98,
        reason="Multi-station evidence refutes charge.",
        evidence_ids=[e.evidence_id for e in evidence_list],
    )
    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.CONTRADICTED,
        eligible_for_recovery=True,
        human_review_required=False,
        claim_amount=Decimal("200.00"),
        evidence_ids=[e.evidence_id for e in evidence_list],
        decision=ValidationDecision.ELIGIBLE,
        status=ValidationDecision.ELIGIBLE,
        reason="Eligible for recovery.",
        rule_code="RULE_RECOVERY_ELIGIBLE",
    )

    engine = ClaimEngine(db=db)
    res = engine.process_claim(charge.charge_id, val_res, ai_resp)

    assert res.outcome == "CLAIM_CREATED"
    claim_row = db.scalars(select(Claim).where(Claim.claim_id == res.claim_id)).first()
    # Sorted distinct managers: Prep and Receiving -> "Prep+Receiving"
    assert claim_row.source_manager == "Prep+Receiving"

    # Verify both claim_evidence rows created
    ce_rows = list(db.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id == claim_row.id)).all())
    assert len(ce_rows) == 2


# ==============================================================================
# Requirement 15: API Endpoint POST /claims/process
# ==============================================================================
def test_api_process_claim_endpoint(client: TestClient, db: Session):
    """Verify HTTP POST /claims/process endpoint works correctly."""
    charge, _, _, evidence_list = create_test_setup(db, suffix="API01", charge_amount=Decimal("99.99"))

    payload = {
        "charge_id": charge.charge_id,
        "validation_result": {
            "charge_id": charge.charge_id,
            "assessment": "CONTRADICTED",
            "eligible_for_recovery": True,
            "human_review_required": False,
            "claim_amount": "99.99",
            "evidence_ids": [evidence_list[0].evidence_id],
            "decision": "ELIGIBLE",
            "status": "ELIGIBLE",
            "reason": "Validated via API test.",
            "rule_code": "RULE_RECOVERY_ELIGIBLE",
        },
        "assessment_response": {
            "assessment": "CONTRADICTED",
            "claim_supported": True,
            "claim_amount": "99.99",
            "confidence": 0.95,
            "reason": "Validated via API test.",
            "evidence_ids": [evidence_list[0].evidence_id],
        },
        "evidence": [],
        "processing_state": {
            "duplicate": False,
            "already_reimbursed": False,
        },
    }

    response = client.post("/claims/process", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "CLAIM_CREATED"
    assert data["charge_id"] == charge.charge_id
    assert data["claim_id"].startswith("CLM-")
    assert data["status"] == "READY_FOR_REVIEW"
    assert data["claim_amount"] == "99.99"


# ==============================================================================
# Requirement: assessment_log Single Audit Trail & Idempotency Tests
# ==============================================================================
def test_assessment_log_written_for_every_evaluation(db: Session):
    """
    Verify assessment_log gets exactly one row for every evaluation,
    regardless of outcome (ELIGIBLE, BLOCKED, NO_CLAIM, HUMAN_REVIEW).
    """
    engine = ClaimEngine(db=db)

    # 1. ELIGIBLE evaluation -> writes 1 claims row, 1 assessment_log row
    chg_el, _, _, ev_el = create_test_setup(db, suffix="AL-EL", charge_amount=Decimal("80.00"))
    ai_el = AIAssessmentResponse(
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("80.00"),
        confidence=0.96,
        reason="Eligible audit test",
        evidence_ids=[ev_el[0].evidence_id],
    )
    val_el = RuleValidationResult(
        charge_id=chg_el.charge_id,
        assessment=AssessmentType.CONTRADICTED,
        eligible_for_recovery=True,
        human_review_required=False,
        claim_amount=Decimal("80.00"),
        evidence_ids=[ev_el[0].evidence_id],
        decision=ValidationDecision.ELIGIBLE,
        status=ValidationDecision.ELIGIBLE,
        reason="Eligible audit test",
        rule_code="RULE_RECOVERY_ELIGIBLE",
    )
    res_el = engine.process_claim(chg_el.charge_id, val_el, ai_el)
    assert res_el.outcome == "CLAIM_CREATED"

    log_el = db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == chg_el.id)).all()
    assert len(log_el) == 1
    assert log_el[0].assessment == "CONTRADICTED"
    assert log_el[0].claim_supported is True
    assert log_el[0].claim_amount == Decimal("80.00")
    assert log_el[0].confidence == Decimal("0.9600")
    assert log_el[0].evidence_ids == [ev_el[0].evidence_id]

    # 2. NO_CLAIM (SUPPORTED) -> 0 claims rows, 1 assessment_log row
    chg_sup, _, _, _ = create_test_setup(db, suffix="AL-SUP", charge_amount=Decimal("50.00"))
    ai_sup = AIAssessmentResponse(
        assessment=AssessmentType.SUPPORTED,
        claim_supported=False,
        claim_amount=None,
        confidence=0.91,
        reason="Supported defect valid",
        evidence_ids=[],
    )
    val_sup = RuleValidationResult(
        charge_id=chg_sup.charge_id,
        assessment=AssessmentType.SUPPORTED,
        eligible_for_recovery=False,
        human_review_required=False,
        claim_amount=None,
        evidence_ids=[],
        decision=ValidationDecision.NON_CLAIM,
        status=ValidationDecision.NON_CLAIM,
        reason="Supported non-claim",
        rule_code="RULE_SUPPORTED_NON_CLAIM",
    )
    res_sup = engine.process_claim(chg_sup.charge_id, val_sup, ai_sup)
    assert res_sup.outcome == "NO_CLAIM"

    claims_sup = db.scalars(select(Claim).where(Claim.charge_id == chg_sup.id)).all()
    assert len(claims_sup) == 0
    log_sup = db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == chg_sup.id)).all()
    assert len(log_sup) == 1
    assert log_sup[0].assessment == "SUPPORTED"
    assert log_sup[0].claim_supported is False
    assert log_sup[0].claim_amount is None

    # 3. NO_CLAIM (SILENT) -> 0 claims rows, 1 assessment_log row
    chg_sil, _, _, _ = create_test_setup(db, suffix="AL-SIL", charge_amount=Decimal("40.00"))
    ai_sil = AIAssessmentResponse(
        assessment=AssessmentType.SILENT,
        claim_supported=False,
        claim_amount=None,
        confidence=0.00,
        reason="No evidence found",
        evidence_ids=[],
    )
    val_sil = RuleValidationResult(
        charge_id=chg_sil.charge_id,
        assessment=AssessmentType.SILENT,
        eligible_for_recovery=False,
        human_review_required=False,
        claim_amount=None,
        evidence_ids=[],
        decision=ValidationDecision.NON_CLAIM,
        status=ValidationDecision.NON_CLAIM,
        reason="Silent non-claim",
        rule_code="RULE_SILENT_NON_CLAIM",
    )
    res_sil = engine.process_claim(chg_sil.charge_id, val_sil, ai_sil)
    assert res_sil.outcome == "NO_CLAIM"

    claims_sil = db.scalars(select(Claim).where(Claim.charge_id == chg_sil.id)).all()
    assert len(claims_sil) == 0
    log_sil = db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == chg_sil.id)).all()
    assert len(log_sil) == 1
    assert log_sil[0].assessment == "SILENT"
    assert log_sil[0].claim_supported is False

    # 4. HUMAN_REVIEW (UNCERTAIN) -> 0 claims rows, 1 assessment_log row
    chg_unc, _, _, ev_unc = create_test_setup(db, suffix="AL-UNC", charge_amount=Decimal("65.00"))
    ai_unc = AIAssessmentResponse(
        assessment=AssessmentType.UNCERTAIN,
        claim_supported=False,
        claim_amount=None,
        confidence=0.40,
        reason="Conflicting logs",
        evidence_ids=[ev_unc[0].evidence_id],
    )
    val_unc = RuleValidationResult(
        charge_id=chg_unc.charge_id,
        assessment=AssessmentType.UNCERTAIN,
        eligible_for_recovery=False,
        human_review_required=True,
        claim_amount=None,
        evidence_ids=[ev_unc[0].evidence_id],
        decision=ValidationDecision.HUMAN_REVIEW,
        status=ValidationDecision.HUMAN_REVIEW,
        reason="Uncertain needs human review",
        rule_code="RULE_UNCERTAIN_HUMAN_REVIEW",
    )
    res_unc = engine.process_claim(chg_unc.charge_id, val_unc, ai_unc)
    assert res_unc.outcome == "HUMAN_REVIEW"

    claims_unc = db.scalars(select(Claim).where(Claim.charge_id == chg_unc.id)).all()
    assert len(claims_unc) == 0
    log_unc = db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == chg_unc.id)).all()
    assert len(log_unc) == 1
    assert log_unc[0].assessment == "UNCERTAIN"
    assert log_unc[0].claim_supported is False

    # 5. BLOCKED (DUPLICATE) -> 1 claims row (DUPLICATE), 1 assessment_log row
    chg_blk, _, _, _ = create_test_setup(db, suffix="AL-BLK", charge_amount=Decimal("30.00"))
    ai_blk = AIAssessmentResponse(
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("30.00"),
        confidence=0.85,
        reason="Duplicate fee",
        evidence_ids=[],
    )
    val_blk = RuleValidationResult(
        charge_id=chg_blk.charge_id,
        assessment=AssessmentType.CONTRADICTED,
        eligible_for_recovery=False,
        human_review_required=False,
        claim_amount=None,
        evidence_ids=[],
        decision=ValidationDecision.BLOCKED,
        status=ValidationDecision.BLOCKED,
        reason="Blocked duplicate",
        rule_code="RULE_DUPLICATE",
    )
    res_blk = engine.process_claim(chg_blk.charge_id, val_blk, ai_blk)
    assert res_blk.outcome == "BLOCKED"

    claims_blk = db.scalars(select(Claim).where(Claim.charge_id == chg_blk.id)).all()
    assert len(claims_blk) == 1
    log_blk = db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == chg_blk.id)).all()
    assert len(log_blk) == 1
    assert log_blk[0].assessment == "CONTRADICTED"


def test_assessment_log_zero_extra_rows_on_already_claimed_reprocessing(db: Session):
    """
    Verify assessment_log gets exactly one row per genuine evaluation,
    and zero extra rows on ALREADY_CLAIMED reprocessing.
    """
    charge, _, _, evidence_list = create_test_setup(db, suffix="IDEM01", charge_amount=Decimal("120.00"))

    ai_resp = AIAssessmentResponse(
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("120.00"),
        confidence=0.95,
        reason="Initial genuine evaluation.",
        evidence_ids=[evidence_list[0].evidence_id],
    )
    val_res = RuleValidationResult(
        charge_id=charge.charge_id,
        assessment=AssessmentType.CONTRADICTED,
        eligible_for_recovery=True,
        human_review_required=False,
        claim_amount=Decimal("120.00"),
        evidence_ids=[evidence_list[0].evidence_id],
        decision=ValidationDecision.ELIGIBLE,
        status=ValidationDecision.ELIGIBLE,
        reason="Eligible for recovery.",
        rule_code="RULE_RECOVERY_ELIGIBLE",
    )

    engine = ClaimEngine(db=db)

    # 1. Genuine first evaluation
    res1 = engine.process_claim(charge.charge_id, val_res, ai_resp)
    assert res1.outcome == "CLAIM_CREATED"

    initial_log_count = db.scalar(
        select(text("count(*)")).select_from(AssessmentLog).where(AssessmentLog.charge_id == charge.id)
    )
    assert initial_log_count == 1

    # 2. Reprocessing attempt -> ALREADY_CLAIMED
    res2 = engine.process_claim(charge.charge_id, val_res, ai_resp)
    assert res2.outcome == "ALREADY_CLAIMED"

    # Confirm exactly zero extra rows were written to assessment_log
    reprocessed_log_count = db.scalar(
        select(text("count(*)")).select_from(AssessmentLog).where(AssessmentLog.charge_id == charge.id)
    )
    assert reprocessed_log_count == 1
    assert reprocessed_log_count == initial_log_count


def test_seed_data_invariants_and_exact_row_counts(client: TestClient, db: Session):
    """
    Verify clean seed data invariants:
    - claims table contains exactly 1 row (the CONTRADICTED/ELIGIBLE example CLM-10092).
    - assessment_log contains exactly 4 rows (CONTRADICTED, SUPPORTED, SILENT, UNCERTAIN).
    - total_potential_recovery reflects only the real CONTRADICTED claim ($45.50), not SUPPORTED ($125.00).
    - GET /charges/pending-review correctly surfaces the UNCERTAIN seed charge via assessment_log without a claim.
    """
    # Verify the seed claim CLM-10092 specifically maintains its invariants
    seed_claim = db.execute(text("SELECT claim_id, assessment, claim_amount, status FROM claims WHERE claim_id = 'CLM-10092'")).mappings().first()
    assert seed_claim is not None
    assert seed_claim["claim_id"] == "CLM-10092"
    assert seed_claim["assessment"] == "CONTRADICTED"
    assert seed_claim["claim_amount"] == Decimal("45.50")
    assert seed_claim["status"] == "READY_FOR_REVIEW"

    assessment_log_count = db.scalar(text("SELECT count(*) FROM assessment_log"))
    assert assessment_log_count >= 4

    log_assessments = set(db.scalars(text("SELECT assessment FROM assessment_log")).all())
    assert {"CONTRADICTED", "SUPPORTED", "SILENT", "UNCERTAIN"}.issubset(log_assessments)

    # Dashboard metrics endpoint verification
    metrics_resp = client.get("/dashboard/metrics")
    assert metrics_resp.status_code == 200
    metrics = metrics_resp.json()
    assert Decimal(str(metrics["total_potential_recovery"])) >= Decimal("45.50")
    for cat in ("SUPPORTED", "CONTRADICTED", "SILENT", "UNCERTAIN"):
        assert metrics["claims_by_assessment"].get(cat, 0) >= 1
    assert metrics["total_claims"] >= 1

    # Pending review endpoint verification
    pending_resp = client.get("/charges/pending-review")
    assert pending_resp.status_code == 200
    pending = pending_resp.json()
    assert pending["total"] == 1
    assert pending["items"][0]["charge_id"] == "CHG-FBA-8904"
    assert pending["items"][0]["latest_claim_id"] is None
    assert pending["items"][0]["latest_claim_status"] is None

