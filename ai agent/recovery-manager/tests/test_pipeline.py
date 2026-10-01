"""Comprehensive Phase 9 Recovery Pipeline Orchestration Tests.

Verifies end-to-end wiring of:
  - Phase 4: Deterministic Evidence Engine
  - Phase 5: AI Reasoning / Recovery Assessment
  - Phase 6: Deterministic Rule Validation
  - Phase 7: Claim Engine Persistence & Audit Logger

Guarantees Verified:
  1. Synchronous execution: Blocks and returns real results without background queues.
  2. Safe lookup: Non-existent charge returns clean NOT_FOUND result without unhandled exceptions.
  3. Strict Idempotency: Duplicate calls on evaluated charges return ALREADY_PROCESSED without calling AI or creating duplicate log rows.
  4. Real DB state resolution for processing_state (already_reimbursed checked via reimbursements.charge_id FK).
  5. Multi-outcome pipeline coverage:
     - CONTRADICTED -> CLAIM_CREATED + Claim + ClaimEvidence + AssessmentLog + charge.status='PROCESSED'
     - SUPPORTED -> NO_CLAIM + AssessmentLog (no claim row)
     - SILENT -> NO_CLAIM + AssessmentLog (no claim row)
     - UNCERTAIN -> HUMAN_REVIEW + AssessmentLog (no claim row)
     - ALREADY_REIMBURSED -> BLOCKED (status='ALREADY_REIMBURSED')
  6. API routes:
     - POST /charges/{charge_id}/process
     - POST /pipeline/process (JSON body)
     - POST /pipeline/process/{charge_id}
     - POST /pipeline/process-batch (batch processing)
  7. Batch processing with error isolation (forced partial failure).
  8. Fresh unprocessed charge E2E (CONTRADICTED with real claim creation).
  9. Fresh unprocessed charge E2E (SILENT with no evidence -> NO_CLAIM).
  10. Reimbursement-linkage -> BLOCKED/ALREADY_REIMBURSED.
"""

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch
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
from app.models.reimbursement import Reimbursement
from app.models.shipment import Shipment
from app.models.assessment_log import AssessmentLog
from app.ai.client import AnthropicClient
from app.ai.service import AIService
from app.schemas.pipeline import PipelineResult, BatchProcessResponse
from app.services.pipeline import process_charge_pipeline, process_batch_pipeline


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
def clean_phase9_test_data():
    """Cleanup any Phase 9 test records before and after each test."""
    def _cleanup():
        session = SessionLocal()
        try:
            # Delete in order respecting foreign keys
            session.execute(text("DELETE FROM claim_evidence WHERE org_id LIKE 'org_test_%'"))
            session.execute(text("DELETE FROM claims WHERE org_id LIKE 'org_test_%'"))
            session.execute(text("DELETE FROM assessment_log WHERE org_id LIKE 'org_test_%'"))
            session.execute(text("DELETE FROM reimbursements WHERE org_id LIKE 'org_test_%'"))
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
    include_evidence: bool = True,
    evidence_type: str = "WEIGHT_DIM_SCAN",
    source_manager: str = "Receiving",
    evidence_content: dict = None,
    with_reimbursement: bool = False,
):
    """Helper to create isolated charge, shipment, order, and evidence records."""
    if evidence_content is None:
        evidence_content = {
            "discrepancy_found": True,
            "measured_weight_kg": 0.45,
            "carrier_claimed_weight_kg": 1.20,
            "scan_location": "Dock Door 4",
        }

    now = datetime.now(timezone.utc)

    shipment = Shipment(
        shipment_id=f"SHP-P9-{suffix}",
    )
    db.add(shipment)
    db.flush()

    order = Order(
        order_id=f"ORD-P9-{suffix}",
    )
    db.add(order)
    db.flush()

    charge = Charge(
        charge_id=f"CHG-P9-{suffix}",
        shipment_id=shipment.id,
        order_id=order.id,
        sku=f"SKU-P9-{suffix}",
        asin=f"B00P9{suffix}",
        charge_type="FBA Inbound Weight Discrepancy",
        amount=charge_amount,
        currency="USD",
        charge_date=now,
        status="PENDING",
    )
    db.add(charge)
    db.flush()

    evidence_record = None
    if include_evidence:
        evidence_record = Evidence(
            evidence_id=f"EVD-P9-{suffix}",
            shipment_id=shipment.id,
            order_id=order.id,
            sku=f"SKU-P9-{suffix}",
            asin=f"B00P9{suffix}",
            source_manager=source_manager,
            evidence_type=evidence_type,
            evidence_timestamp=now,
            evidence_content=evidence_content,
        )
        db.add(evidence_record)
        db.flush()

    reimb_record = None
    if with_reimbursement:
        reimb_record = Reimbursement(
            reimbursement_id=f"RMB-P9-{suffix}",
            charge_id=charge.id,
            amount=charge_amount,
            reimbursement_date=now,
            raw_data={"source": "Carrier offset credit"},
        )
        db.add(reimb_record)
        db.flush()

    db.commit()

    return {
        "shipment": shipment,
        "order": order,
        "charge": charge,
        "evidence": evidence_record,
        "reimbursement": reimb_record,
    }


def make_mock_ai_service(
    assessment: str = "CONTRADICTED",
    claim_supported: bool = True,
    claim_amount: Decimal = Decimal("100.00"),
    confidence: float = 0.95,
    reason: str = "Operational receiving weight scan proves carrier overcharged on package weight.",
    evidence_ids: list = None,
) -> AIService:
    """Helper to instantiate AIService with mocked AnthropicClient generating strict valid responses."""
    if evidence_ids is None:
        evidence_ids = []

    mock_client = MagicMock(spec=AnthropicClient)
    payload = {
        "assessment": assessment,
        "claim_supported": claim_supported,
        "claim_amount": float(claim_amount) if claim_amount is not None else None,
        "confidence": confidence,
        "reason": reason,
        "evidence_ids": evidence_ids,
    }
    mock_client.generate_assessment.return_value = json.dumps(payload)
    return AIService(client=mock_client)


def make_failing_ai_service() -> AIService:
    """Helper to create an AIService that raises an exception when called."""
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.side_effect = RuntimeError(
        "Simulated AI service failure: API timeout"
    )
    return AIService(client=mock_client)


# ==============================================================================
# 1. NOT_FOUND & Defensive Lookup Tests
# ==============================================================================

def test_pipeline_charge_not_found(db: Session):
    """
    Step 1: If charge is not found, return clear NOT_FOUND result.
    Must NOT raise an unhandled exception.
    """
    result = process_charge_pipeline(charge_id="CHG-P9-NONEXISTENT", db=db)

    assert isinstance(result, PipelineResult)
    assert result.outcome == "NOT_FOUND"
    assert result.charge_id == "CHG-P9-NONEXISTENT"
    assert "not exist" in result.reason.lower()
    assert result.claim_id is None
    assert result.claim_amount is None


def test_pipeline_empty_charge_id_safe(db: Session):
    """Empty or whitespace charge_id returns clean NOT_FOUND without crashing."""
    result = process_charge_pipeline(charge_id="   ", db=db)

    assert isinstance(result, PipelineResult)
    assert result.outcome == "NOT_FOUND"
    assert result.claim_id is None


# ==============================================================================
# 2. Idempotency Check Tests (assessment_log & claims)
# ==============================================================================

def test_pipeline_idempotency_via_assessment_log(db: Session):
    """
    Step 2: IDEMPOTENCY CHECK via assessment_log.
    If an assessment_log row exists for this charge, return ALREADY_PROCESSED.
    Do NOT re-run pipeline or call AI.
    """
    setup = create_test_setup(db, suffix="ID01")
    charge = setup["charge"]

    # Pre-populate an assessment_log entry
    log_entry = AssessmentLog(
        charge_id=charge.id,
        assessment="SUPPORTED",
        claim_supported=False,
        claim_amount=None,
        confidence=Decimal("0.8800"),
        reason="Previously evaluated as SUPPORTED by automated reasoning.",
        evidence_ids=["EVD-P9-ID01"],
    )
    db.add(log_entry)
    db.commit()

    # Create mock AI that would fail if called
    mock_ai = MagicMock(spec=AIService)
    mock_ai.assess_recovery.side_effect = RuntimeError("AI should NOT be called on already-evaluated charge!")

    result = process_charge_pipeline(
        charge_id=charge.charge_id,
        db=db,
        ai_service=mock_ai,
    )

    assert result.outcome == "ALREADY_PROCESSED"
    assert result.charge_id == charge.charge_id
    assert result.assessment == "SUPPORTED"
    assert "Idempotency hit" in result.reason
    assert mock_ai.assess_recovery.call_count == 0

    # Verify no second log row was created
    logs = list(db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == charge.id)).all())
    assert len(logs) == 1


def test_pipeline_idempotency_via_claim(db: Session):
    """
    Step 2: IDEMPOTENCY CHECK via existing claims row.
    If a claims row exists, return ALREADY_PROCESSED with existing claim metadata.
    """
    setup = create_test_setup(db, suffix="ID02", charge_amount=Decimal("75.00"))
    charge = setup["charge"]

    # Pre-populate a claim
    existing_claim = Claim(
        claim_id="CLM-P9-EXISTING",
        charge_id=charge.id,
        assessment="CONTRADICTED",
        claim_amount=Decimal("75.00"),
        confidence=Decimal("0.9600"),
        explanation="Pre-existing claim row",
        status="READY_FOR_REVIEW",
    )
    db.add(existing_claim)
    db.commit()

    mock_ai = MagicMock(spec=AIService)
    mock_ai.assess_recovery.side_effect = RuntimeError("AI should NOT be called!")

    result = process_charge_pipeline(
        charge_id=charge.charge_id,
        db=db,
        ai_service=mock_ai,
    )

    assert result.outcome == "ALREADY_PROCESSED"
    assert result.claim_id == "CLM-P9-EXISTING"
    assert result.status == "READY_FOR_REVIEW"
    assert result.claim_amount == Decimal("75.00")
    assert mock_ai.assess_recovery.call_count == 0


def test_pipeline_reprocessing_idempotency(db: Session):
    """
    Full pipeline run followed by immediate reprocessing attempt.
    First run creates claim + assessment_log.
    Second run must return ALREADY_PROCESSED without calling AI or creating duplicate rows.
    """
    setup = create_test_setup(db, suffix="REPROCESS", charge_amount=Decimal("120.00"))
    charge = setup["charge"]
    evidence = setup["evidence"]

    mock_ai = make_mock_ai_service(
        assessment="CONTRADICTED",
        claim_supported=True,
        claim_amount=Decimal("120.00"),
        confidence=0.94,
        reason="Weight discrepancy confirmed by receiving scan.",
        evidence_ids=[evidence.evidence_id],
    )

    # First run: should create claim
    result1 = process_charge_pipeline(charge_id=charge.charge_id, db=db, ai_service=mock_ai)
    assert result1.outcome == "CLAIM_CREATED"
    assert result1.claim_id is not None

    # Second run: should be idempotent
    mock_ai2 = MagicMock(spec=AIService)
    mock_ai2.assess_recovery.side_effect = RuntimeError("AI should NOT be called on reprocessing!")
    result2 = process_charge_pipeline(charge_id=charge.charge_id, db=db, ai_service=mock_ai2)

    assert result2.outcome == "ALREADY_PROCESSED"
    assert result2.claim_id == result1.claim_id
    assert mock_ai2.assess_recovery.call_count == 0

    # Verify only 1 claim row and 1 assessment_log row exist
    claims = list(db.scalars(select(Claim).where(Claim.charge_id == charge.id)).all())
    assert len(claims) == 1

    logs = list(db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == charge.id)).all())
    assert len(logs) == 1


# ==============================================================================
# 3. End-to-End Orchestration: CONTRADICTED -> CLAIM_CREATED (Fresh Charge)
# ==============================================================================

def test_pipeline_e2e_contradicted_creates_claim(db: Session):
    """
    Full pipeline run for a genuinely fresh, unprocessed charge with contradicting evidence:
      Phase 4 (Evidence) -> Phase 5 (AI CONTRADICTED) -> Phase 6 (Rule ELIGIBLE) -> Phase 7 (CLAIM_CREATED).
    Verifies:
      - Claim row created with status='READY_FOR_REVIEW'
      - ClaimEvidence join row created
      - Charge.status updated to 'PROCESSED'
      - AssessmentLog recorded
      - Re-running the pipeline immediately returns ALREADY_PROCESSED
    """
    setup = create_test_setup(
        db,
        suffix="FRESH01",
        charge_amount=Decimal("85.50"),
        evidence_content={
            "discrepancy_found": True,
            "measured_weight_kg": 0.45,
            "carrier_claimed_weight_kg": 1.20,
            "scan_location": "Dock Door 4",
            "scan_timestamp": "2026-09-01T10:00:00Z",
        },
    )
    charge = setup["charge"]
    evidence = setup["evidence"]

    # Verify no assessment_log or claims exist before pipeline
    pre_logs = list(db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == charge.id)).all())
    pre_claims = list(db.scalars(select(Claim).where(Claim.charge_id == charge.id)).all())
    assert len(pre_logs) == 0, "Pre-condition failed: assessment_log rows already exist"
    assert len(pre_claims) == 0, "Pre-condition failed: claims rows already exist"

    mock_ai = make_mock_ai_service(
        assessment="CONTRADICTED",
        claim_supported=True,
        claim_amount=Decimal("85.50"),
        confidence=0.97,
        reason="Warehouse receiving scale verifies shipment weight was 0.45 kg, contradicting 1.20 kg billed.",
        evidence_ids=[evidence.evidence_id],
    )

    result = process_charge_pipeline(
        charge_id=charge.charge_id,
        db=db,
        ai_service=mock_ai,
    )

    # 1. PipelineResult contract
    assert result.outcome == "CLAIM_CREATED"
    assert result.charge_id == charge.charge_id
    assert result.claim_id is not None
    assert result.claim_id.startswith("CLM-")
    assert result.status == "READY_FOR_REVIEW"
    assert result.assessment == "CONTRADICTED"
    assert result.claim_amount == Decimal("85.50")
    assert result.confidence == 0.97
    assert result.decision == "ELIGIBLE"
    assert result.rule_code == "RULE_ELIGIBLE"
    assert result.evidence_count == 1
    assert result.evidence_ids == [evidence.evidence_id]

    # 2. Database verification: Claim row
    claim_row = db.scalars(select(Claim).where(Claim.claim_id == result.claim_id)).first()
    assert claim_row is not None
    assert claim_row.charge_id == charge.id
    assert claim_row.status == "READY_FOR_REVIEW"
    assert claim_row.claim_amount == Decimal("85.50")
    assert claim_row.source_manager == "Receiving"

    # 3. Database verification: ClaimEvidence junction row
    ce_links = list(db.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id == claim_row.id)).all())
    assert len(ce_links) == 1
    assert ce_links[0].evidence_id == evidence.id

    # 4. Database verification: Charge status updated to 'PROCESSED'
    db.refresh(charge)
    assert charge.status == "PROCESSED"

    # 5. Database verification: AssessmentLog entry
    log_row = db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == charge.id)).first()
    assert log_row is not None
    assert log_row.assessment == "CONTRADICTED"
    assert log_row.claim_supported is True
    assert log_row.claim_amount == Decimal("85.50")
    assert log_row.evidence_ids == [evidence.evidence_id]

    # 6. Idempotency test: Immediate re-run must NOT create a duplicate claim or log
    mock_ai2 = MagicMock(spec=AIService)
    mock_ai2.assess_recovery.side_effect = RuntimeError("Should not be called!")
    rerun_result = process_charge_pipeline(charge_id=charge.charge_id, db=db, ai_service=mock_ai2)

    assert rerun_result.outcome == "ALREADY_PROCESSED"
    assert rerun_result.claim_id == result.claim_id


# ==============================================================================
# 4. End-to-End Orchestration: SUPPORTED -> NO_CLAIM
# ==============================================================================

def test_pipeline_e2e_supported_no_claim(db: Session):
    """
    Charge supported by operational evidence:
      Phase 4 -> Phase 5 (SUPPORTED) -> Phase 6 (NON_CLAIM) -> Phase 7 (NO_CLAIM).
    Verifies:
      - Zero claims rows created
      - AssessmentLog recorded with assessment='SUPPORTED'
      - outcome == 'NO_CLAIM'
    """
    setup = create_test_setup(db, suffix="20", charge_amount=Decimal("30.00"))
    charge = setup["charge"]

    mock_ai = make_mock_ai_service(
        assessment="SUPPORTED",
        claim_supported=False,
        claim_amount=None,
        confidence=0.92,
        reason="Receiving dock scan corroborates marketplace dimension classification.",
        evidence_ids=[],
    )

    result = process_charge_pipeline(
        charge_id=charge.charge_id,
        db=db,
        ai_service=mock_ai,
    )

    assert result.outcome == "NO_CLAIM"
    assert result.claim_id is None
    assert result.claim_amount is None
    assert result.assessment == "SUPPORTED"
    assert result.decision == "NON_CLAIM"

    # Verify no claim in DB
    claims_count = db.scalar(select(text("COUNT(*)")).select_from(Claim).where(Claim.charge_id == charge.id))
    assert claims_count == 0

    # Verify AssessmentLog was recorded
    log_row = db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == charge.id)).first()
    assert log_row is not None
    assert log_row.assessment == "SUPPORTED"
    assert log_row.claim_supported is False


# ==============================================================================
# 5. End-to-End Orchestration: SILENT -> NO_CLAIM (Fresh Charge, No Evidence)
# ==============================================================================

def test_pipeline_e2e_silent_no_claim(db: Session):
    """
    Fresh, genuinely unprocessed charge with NO evidence at all:
      Phase 4 (0 evidence) -> Phase 5 (SILENT) -> Phase 6 (NON_CLAIM) -> Phase 7 (NO_CLAIM).
    Proves the pipeline correctly resolves to SILENT with an assessment_log row
    and no claims row — proving the pipeline works for the no-evidence case.
    """
    setup = create_test_setup(db, suffix="SILENT01", include_evidence=False)
    charge = setup["charge"]

    # Verify genuinely fresh: no assessment_log, no claims
    pre_logs = list(db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == charge.id)).all())
    pre_claims = list(db.scalars(select(Claim).where(Claim.charge_id == charge.id)).all())
    assert len(pre_logs) == 0, "Pre-condition failed: assessment_log rows already exist for SILENT charge"
    assert len(pre_claims) == 0, "Pre-condition failed: claims rows already exist for SILENT charge"

    mock_ai = make_mock_ai_service(
        assessment="SILENT",
        claim_supported=False,
        claim_amount=None,
        confidence=0.85,
        reason="No operational evidence found across warehouse systems.",
        evidence_ids=[],
    )

    result = process_charge_pipeline(
        charge_id=charge.charge_id,
        db=db,
        ai_service=mock_ai,
    )

    assert result.outcome == "NO_CLAIM"
    assert result.claim_id is None
    assert result.assessment == "SILENT"
    assert result.evidence_count == 0
    assert result.decision == "NON_CLAIM"
    assert result.rule_code == "RULE_SILENT"

    # Verify AssessmentLog was created
    log_row = db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == charge.id)).first()
    assert log_row is not None
    assert log_row.assessment == "SILENT"
    assert log_row.claim_supported is False
    assert log_row.claim_amount is None

    # Verify NO claims row was created
    claims_count = db.scalar(select(text("COUNT(*)")).select_from(Claim).where(Claim.charge_id == charge.id))
    assert claims_count == 0


# ==============================================================================
# 6. End-to-End Orchestration: UNCERTAIN -> HUMAN_REVIEW
# ==============================================================================

def test_pipeline_e2e_uncertain_human_review(db: Session):
    """
    Conflicting evidence triggers UNCERTAIN:
      Phase 4 -> Phase 5 (UNCERTAIN) -> Phase 6 (HUMAN_REVIEW) -> Phase 7 (HUMAN_REVIEW).
    Verifies:
      - Zero claims rows
      - AssessmentLog recorded with assessment='UNCERTAIN'
      - outcome == 'HUMAN_REVIEW'
    """
    setup = create_test_setup(db, suffix="40")
    charge = setup["charge"]
    evidence = setup["evidence"]

    mock_ai = make_mock_ai_service(
        assessment="UNCERTAIN",
        claim_supported=False,
        claim_amount=None,
        confidence=0.50,
        reason="Conflicting timestamps between packing audit and dock arrival logs.",
        evidence_ids=[evidence.evidence_id],
    )

    result = process_charge_pipeline(
        charge_id=charge.charge_id,
        db=db,
        ai_service=mock_ai,
    )

    assert result.outcome == "HUMAN_REVIEW"
    assert result.claim_id is None
    assert result.assessment == "UNCERTAIN"
    assert result.decision == "HUMAN_REVIEW"

    # Zero claims rows
    claims_count = db.scalar(select(text("COUNT(*)")).select_from(Claim).where(Claim.charge_id == charge.id))
    assert claims_count == 0

    # AssessmentLog entry present
    log_row = db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == charge.id)).first()
    assert log_row is not None
    assert log_row.assessment == "UNCERTAIN"


# ==============================================================================
# 7. Processing State: Already Reimbursed -> BLOCKED
# ==============================================================================

def test_pipeline_e2e_already_reimbursed_blocked(db: Session):
    """
    Charge that already has a linked reimbursement in reimbursements table:
      Determines already_reimbursed=True from real DB state.
      Rule validation blocks recovery -> ClaimEngine persists BLOCKED claim with status='ALREADY_REIMBURSED'.
    Proves the reimbursement linkage actually works end-to-end when charge_id is populated.
    """
    setup = create_test_setup(db, suffix="REIMB01", with_reimbursement=True)
    charge = setup["charge"]
    evidence = setup["evidence"]
    reimb = setup["reimbursement"]

    # Verify reimbursement.charge_id is actually populated
    db.refresh(reimb)
    assert reimb.charge_id is not None, "Reimbursement.charge_id should be populated"
    assert reimb.charge_id == charge.id, "Reimbursement should be linked to this charge"

    # Create mock AI that raises an exception if called to strictly prove zero invocation
    mock_ai = MagicMock(spec=AIService)
    mock_ai.assess_recovery.side_effect = RuntimeError("AI service should NEVER be called on already-reimbursed charge!")

    result = process_charge_pipeline(
        charge_id=charge.charge_id,
        db=db,
        ai_service=mock_ai,
    )

    # Prove zero AI calls were made
    assert mock_ai.assess_recovery.call_count == 0, "AI must not be invoked when already_reimbursed is True"

    assert result.outcome == "BLOCKED"
    assert result.status == "ALREADY_REIMBURSED"
    assert result.decision == "BLOCKED"
    assert result.rule_code == "RULE_ALREADY_REIMBURSED"
    assert "already been reimbursed" in result.reason.lower()
    assert result.confidence is None
    assert result.claim_amount is None

    # Verify non-financial claim row exists in DB
    claim_row = db.scalars(select(Claim).where(Claim.charge_id == charge.id)).first()
    assert claim_row is not None
    assert claim_row.status == "ALREADY_REIMBURSED"
    assert claim_row.claim_amount is None
    assert claim_row.confidence is None

    # Verify assessment_log entry exists in DB
    log_row = db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == charge.id)).first()
    assert log_row is not None
    assert log_row.assessment == "CONTRADICTED"
    assert log_row.claim_supported is False
    assert log_row.claim_amount is None
    assert log_row.confidence is None
    assert "already been reimbursed" in log_row.reason.lower()


def test_pipeline_already_reimbursed_dashboard_metrics_distinction(client, db: Session):
    """
    Explicit test for Phase 9 / Dashboard metrics distinction:
    A short-circuited BLOCKED/already_reimbursed row (confidence=None):
      - MUST NOT appear in GET /dashboard/metrics claims_by_assessment counts (not a genuine AI evaluation).
      - MUST appear in GET /dashboard/metrics claims_by_status counts under ALREADY_REIMBURSED (valid operational state).
    """
    # 1. Capture baseline metrics
    resp_base = client.get("/dashboard/metrics")
    assert resp_base.status_code == 200
    base_metrics = resp_base.json()

    base_contradicted = base_metrics["claims_by_assessment"].get("CONTRADICTED", 0)
    base_already_reimbursed = base_metrics["claims_by_status"].get("ALREADY_REIMBURSED", 0)

    # 2. Run already_reimbursed short-circuit charge
    setup = create_test_setup(db, suffix="DASH01", with_reimbursement=True)
    charge = setup["charge"]

    mock_ai = MagicMock(spec=AIService)
    mock_ai.assess_recovery.side_effect = RuntimeError("AI should not be called!")

    result = process_charge_pipeline(
        charge_id=charge.charge_id,
        db=db,
        ai_service=mock_ai,
    )
    assert result.outcome == "BLOCKED"
    assert result.status == "ALREADY_REIMBURSED"

    # 3. Fetch metrics after running the pipeline
    resp_after = client.get("/dashboard/metrics")
    assert resp_after.status_code == 200
    after_metrics = resp_after.json()

    after_contradicted = after_metrics["claims_by_assessment"].get("CONTRADICTED", 0)
    after_already_reimbursed = after_metrics["claims_by_status"].get("ALREADY_REIMBURSED", 0)

    # ASSERTION 1: claims_by_assessment did NOT increment CONTRADICTED count (placeholder excluded)
    assert after_contradicted == base_contradicted, (
        f"claims_by_assessment CONTRADICTED count increased from {base_contradicted} to {after_contradicted}, "
        f"meaning placeholder assessment from short-circuited row was incorrectly counted as an AI evaluation!"
    )

    # ASSERTION 2: claims_by_status DID increment ALREADY_REIMBURSED count by 1 (operational status respected)
    assert after_already_reimbursed == base_already_reimbursed + 1, (
        f"claims_by_status ALREADY_REIMBURSED count should have incremented by 1 (from {base_already_reimbursed} to {after_already_reimbursed})"
    )


# ==============================================================================
# 8. Session Management: Autonomous Session Handling
# ==============================================================================

def test_pipeline_standalone_session_management():
    """
    Verifies process_charge_pipeline works when db is NOT passed,
    instantiating and cleanly closing its own SessionLocal context.
    """
    # Setup test charge using temporary session
    with SessionLocal() as session:
        setup = create_test_setup(session, suffix="60")
        charge_id = setup["charge"].charge_id
        ev_id = setup["evidence"].evidence_id

    mock_ai = make_mock_ai_service(
        assessment="CONTRADICTED",
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        evidence_ids=[ev_id],
    )

    # Call with db=None
    result = process_charge_pipeline(charge_id=charge_id, db=None, ai_service=mock_ai)

    assert result.outcome == "CLAIM_CREATED"
    assert result.claim_id is not None

    # Verify persistence
    with SessionLocal() as session:
        claim_row = db_claim = session.scalars(select(Claim).where(Claim.claim_id == result.claim_id)).first()
        assert claim_row is not None


# ==============================================================================
# 9. API Route Tests: POST /charges/{charge_id}/process
# ==============================================================================

def test_pipeline_endpoint_charges_process(client: TestClient, db: Session):
    """Verify POST /charges/{charge_id}/process triggers pipeline synchronously."""
    setup = create_test_setup(db, suffix="70", charge_amount=Decimal("60.00"))
    charge = setup["charge"]
    evidence = setup["evidence"]

    mock_ai = make_mock_ai_service(
        assessment="CONTRADICTED",
        claim_supported=True,
        claim_amount=Decimal("60.00"),
        evidence_ids=[evidence.evidence_id],
    )

    with patch("app.services.pipeline.AIService", return_value=mock_ai), \
         patch("app.ai.service.ai_service", mock_ai):
        response = client.post(f"/charges/{charge.charge_id}/process")

    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "CLAIM_CREATED"
    assert data["charge_id"] == charge.charge_id
    assert data["claim_id"].startswith("CLM-")
    assert Decimal(data["claim_amount"]) == Decimal("60.00")

    # Second call must hit idempotency and return 200 ALREADY_PROCESSED
    response2 = client.post(f"/charges/{charge.charge_id}/process")
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["outcome"] == "ALREADY_PROCESSED"
    assert data2["claim_id"] == data["claim_id"]


def test_pipeline_endpoint_charges_not_found(client: TestClient):
    """Verify POST /charges/{charge_id}/process returns 404 for unknown charge."""
    response = client.post("/charges/CHG-P9-UNKNOWN-999/process")
    assert response.status_code == 404
    assert "not exist" in response.json()["detail"].lower()


# ==============================================================================
# 10. API Route Tests: POST /pipeline/process and POST /pipeline/process/{id}
# ==============================================================================

def test_pipeline_endpoint_pipeline_json_process(client: TestClient, db: Session):
    """Verify POST /pipeline/process with JSON body."""
    setup = create_test_setup(db, suffix="80", charge_amount=Decimal("40.00"))
    charge = setup["charge"]
    evidence = setup["evidence"]

    mock_ai = make_mock_ai_service(
        assessment="CONTRADICTED",
        claim_supported=True,
        claim_amount=Decimal("40.00"),
        evidence_ids=[evidence.evidence_id],
    )

    with patch("app.services.pipeline.AIService", return_value=mock_ai), \
         patch("app.ai.service.ai_service", mock_ai):
        response = client.post("/pipeline/process", json={"charge_id": charge.charge_id})

    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "CLAIM_CREATED"
    assert Decimal(data["claim_amount"]) == Decimal("40.00")


def test_pipeline_endpoint_pipeline_path_process(client: TestClient, db: Session):
    """Verify POST /pipeline/process/{charge_id} with path parameter."""
    setup = create_test_setup(db, suffix="90", charge_amount=Decimal("50.00"))
    charge = setup["charge"]
    evidence = setup["evidence"]

    mock_ai = make_mock_ai_service(
        assessment="CONTRADICTED",
        claim_supported=True,
        claim_amount=Decimal("50.00"),
        evidence_ids=[evidence.evidence_id],
    )

    with patch("app.services.pipeline.AIService", return_value=mock_ai), \
         patch("app.ai.service.ai_service", mock_ai):
        response = client.post(f"/pipeline/process/{charge.charge_id}")

    assert response.status_code == 200
    data = response.json()
    assert data["outcome"] == "CLAIM_CREATED"
    assert Decimal(data["claim_amount"]) == Decimal("50.00")


# ==============================================================================
# 11. Batch Processing with Forced Partial Failure (Error Isolation)
# ==============================================================================

def test_batch_pipeline_with_forced_partial_failure(db: Session):
    """
    Batch-process 3 genuinely unprocessed charges where one is forced to fail (mocked AI failure).
    Proves:
      - The other 2 still complete successfully
      - The failure is isolated in the per-charge result, not a crashed request
      - Summary counts are accurate (succeeded=2, failed=1, total=3)
    """
    # Create 3 fresh unprocessed charges
    setup1 = create_test_setup(db, suffix="BATCH01", charge_amount=Decimal("50.00"))
    setup2 = create_test_setup(db, suffix="BATCH02", charge_amount=Decimal("75.00"))
    setup3 = create_test_setup(db, suffix="BATCH03", charge_amount=Decimal("100.00"))

    charge1 = setup1["charge"]
    charge2 = setup2["charge"]
    charge3 = setup3["charge"]
    ev1 = setup1["evidence"]
    ev2 = setup2["evidence"]
    ev3 = setup3["evidence"]

    # Verify all 3 are genuinely unprocessed
    for c in [charge1, charge2, charge3]:
        pre_logs = list(db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == c.id)).all())
        pre_claims = list(db.scalars(select(Claim).where(Claim.charge_id == c.id)).all())
        assert len(pre_logs) == 0
        assert len(pre_claims) == 0

    # Create a mock AI that:
    # - Returns CONTRADICTED for charge1 and charge3
    # - Raises RuntimeError for charge2 (forced failure)
    call_count = {"n": 0}
    charge_ids_in_order = [charge1.charge_id, charge2.charge_id, charge3.charge_id]

    def mock_generate_assessment(*args, **kwargs) -> str:
        call_count["n"] += 1
        prompt = kwargs.get("user_prompt", "") or (args[1] if len(args) > 1 else (args[0] if args else ""))
        # Determine which charge this is for by inspecting the prompt
        if charge2.charge_id in prompt:
            raise RuntimeError("Simulated AI service failure: API timeout for charge 2")

        if charge1.charge_id in prompt:
            return json.dumps({
                "assessment": "CONTRADICTED",
                "claim_supported": True,
                "claim_amount": 50.00,
                "confidence": 0.95,
                "reason": "Weight discrepancy confirmed for batch charge 1.",
                "evidence_ids": [ev1.evidence_id],
            })

        # charge3
        return json.dumps({
            "assessment": "CONTRADICTED",
            "claim_supported": True,
            "claim_amount": 100.00,
            "confidence": 0.93,
            "reason": "Weight discrepancy confirmed for batch charge 3.",
            "evidence_ids": [ev3.evidence_id],
        })

    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.side_effect = mock_generate_assessment
    mock_ai = AIService(client=mock_client)

    # Run batch pipeline
    batch_result = process_batch_pipeline(
        charge_ids=[charge1.charge_id, charge2.charge_id, charge3.charge_id],
        db=db,
        ai_service=mock_ai,
    )

    assert isinstance(batch_result, BatchProcessResponse)
    assert batch_result.total == 3
    assert batch_result.succeeded == 2
    assert batch_result.failed == 1
    assert batch_result.already_processed == 0
    assert len(batch_result.results) == 3

    # Verify per-charge results
    r1 = batch_result.results[0]
    r2 = batch_result.results[1]
    r3 = batch_result.results[2]

    assert r1.charge_id == charge1.charge_id
    assert r1.outcome == "CLAIM_CREATED"
    assert r1.claim_id is not None

    assert r2.charge_id == charge2.charge_id
    assert r2.outcome == "ERROR"
    assert "Simulated AI service failure" in r2.reason

    assert r3.charge_id == charge3.charge_id
    assert r3.outcome == "CLAIM_CREATED"
    assert r3.claim_id is not None

    # Verify DB state: charge1 and charge3 have claims, charge2 does not
    c1_claim = db.scalars(select(Claim).where(Claim.charge_id == charge1.id)).first()
    assert c1_claim is not None
    assert c1_claim.status == "READY_FOR_REVIEW"

    c2_claim = db.scalars(select(Claim).where(Claim.charge_id == charge2.id)).first()
    assert c2_claim is None, "Charge 2 should NOT have a claim because it failed"

    c3_claim = db.scalars(select(Claim).where(Claim.charge_id == charge3.id)).first()
    assert c3_claim is not None
    assert c3_claim.status == "READY_FOR_REVIEW"


# ==============================================================================
# 12. Batch Processing API Endpoint Test
# ==============================================================================

def test_batch_pipeline_api_endpoint(client: TestClient, db: Session):
    """Verify POST /pipeline/process-batch API endpoint with explicit charge_ids."""
    setup1 = create_test_setup(db, suffix="BAPI01", charge_amount=Decimal("33.00"))
    setup2 = create_test_setup(db, suffix="BAPI02", charge_amount=Decimal("44.00"))
    charge1 = setup1["charge"]
    charge2 = setup2["charge"]
    ev1 = setup1["evidence"]
    ev2 = setup2["evidence"]

    def mock_generate(*args, **kwargs) -> str:
        prompt = kwargs.get("user_prompt", "") or (args[1] if len(args) > 1 else (args[0] if args else ""))
        if charge1.charge_id in prompt:
            return json.dumps({
                "assessment": "CONTRADICTED",
                "claim_supported": True,
                "claim_amount": 33.00,
                "confidence": 0.92,
                "reason": "Batch API test charge 1 contradicted.",
                "evidence_ids": [ev1.evidence_id],
            })
        return json.dumps({
            "assessment": "CONTRADICTED",
            "claim_supported": True,
            "claim_amount": 44.00,
            "confidence": 0.91,
            "reason": "Batch API test charge 2 contradicted.",
            "evidence_ids": [ev2.evidence_id],
        })

    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.side_effect = mock_generate
    mock_ai = AIService(client=mock_client)

    with patch("app.services.pipeline.AIService", return_value=mock_ai), \
         patch("app.ai.service.ai_service", mock_ai):
        response = client.post(
            "/pipeline/process-batch",
            json={"charge_ids": [charge1.charge_id, charge2.charge_id]},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["succeeded"] == 2
    assert data["failed"] == 0
    assert len(data["results"]) == 2
    assert data["results"][0]["outcome"] == "CLAIM_CREATED"
    assert data["results"][1]["outcome"] == "CLAIM_CREATED"


# ==============================================================================
# 13. Batch Default Mode: All Unassessed Charges
# ==============================================================================

def test_batch_pipeline_default_unassessed(db: Session):
    """Batch with no charge_ids defaults to all charges with no assessment_log row."""
    # Create 2 charges: one with assessment_log (should be skipped), one without
    setup_assessed = create_test_setup(db, suffix="BDEF01")
    setup_unassessed = create_test_setup(db, suffix="BDEF02")

    # Pre-populate assessment_log for the first one
    log_entry = AssessmentLog(
        charge_id=setup_assessed["charge"].id,
        assessment="SUPPORTED",
        claim_supported=False,
        confidence=Decimal("0.8800"),
        reason="Previously assessed.",
        evidence_ids=[],
    )
    db.add(log_entry)
    db.commit()

    ev2 = setup_unassessed["evidence"]

    mock_ai = make_mock_ai_service(
        assessment="CONTRADICTED",
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        confidence=0.90,
        reason="Batch default test.",
        evidence_ids=[ev2.evidence_id],
    )

    # Call with no charge_ids (default mode)
    batch_result = process_batch_pipeline(charge_ids=None, db=db, ai_service=mock_ai)

    # Should have processed at least the unassessed one
    # (there may be other unassessed charges from seed data)
    assert isinstance(batch_result, BatchProcessResponse)
    assert batch_result.total >= 1

    # Find our test charge in results
    our_result = [r for r in batch_result.results if r.charge_id == setup_unassessed["charge"].charge_id]
    assert len(our_result) == 1
    # The assessed one should NOT be in the batch results
    assessed_result = [r for r in batch_result.results if r.charge_id == setup_assessed["charge"].charge_id]
    assert len(assessed_result) == 0


# ==============================================================================
# Zero-Amount Short-Circuit Audit Trail Test (Item 3 Tier 0)
# ==============================================================================

def test_zero_amount_charge_writes_assessment_log(db):
    """
    A charge with amount <= 0 must short-circuit to NO_CLAIM AND persist
    an AssessmentLog row (SILENT, confidence=None). This proves the audit
    trail is intact even for non-financial charges.
    """
    now = datetime.now(timezone.utc)

    shipment = Shipment(shipment_id="SHP-P9-ZERO-01")
    db.add(shipment)
    db.flush()

    zero_charge = Charge(
        charge_id="CHG-P9-ZERO-01",
        shipment_id=shipment.id,
        org_id="org_test_alpha",
        charge_type="inbound_defect_fee",
        report_type="fee_report",
        amount=Decimal("0.00"),
        currency="USD",
        charge_date=now,
        status="PENDING",
        raw_data={},
    )
    db.add(zero_charge)
    db.commit()
    db.refresh(zero_charge)

    result = process_charge_pipeline(charge_id="CHG-P9-ZERO-01", db=db)

    # Pipeline must return NO_CLAIM
    assert result.outcome == "NO_CLAIM", f"Expected NO_CLAIM, got {result.outcome}"
    assert result.charge_id == "CHG-P9-ZERO-01"

    # AssessmentLog row MUST exist (audit trail for zero-amount short-circuit)
    log_row = db.execute(
        select(AssessmentLog).where(AssessmentLog.charge_id == zero_charge.id)
    ).scalars().first()
    assert log_row is not None, (
        "AssessmentLog row was NOT written for zero-amount short-circuit — audit trail missing"
    )
    assert log_row.assessment == "SILENT", f"Expected SILENT, got {log_row.assessment}"
    assert log_row.claim_supported is False
    assert log_row.claim_amount is None
    assert log_row.confidence is None
    assert "non-positive amount" in (log_row.reason or "").lower() or "0.00" in (log_row.reason or "")

