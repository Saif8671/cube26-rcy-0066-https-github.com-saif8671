"""Tests for RULES.md Requirements: Overrides are Data & Fail-Open Error Auditing.

Covers:
1. OVERRIDES ARE DATA (Honesty Rule):
   - Override an UNCERTAIN charge to approve -> confirms overrides row + resulting claim created.
   - Override a CONTRADICTED claim to reject -> confirms overrides row + claims.status change to REJECTED.
   - Confirm overrides table is append-only (attempting UPDATE or DELETE raises PostgreSQL exception).
   - Non-empty reason validation.

2. FAIL OPEN (Engineering Rule 3):
   - Force pipeline ERROR -> confirms durable row in pipeline_errors with status='pending'.
   - Retrievable via GET /charges/failed-pending.
   - Retrying/reprocessing without error succeeds and resolves the pending error record.
"""

from datetime import datetime, timezone
from decimal import Decimal
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

from app.main import app
from app.core.database import SessionLocal
from app.models.charge import Charge
from app.models.claim import Claim
from app.models.evidence import Evidence
from app.models.assessment_log import AssessmentLog
from app.models.override import Override
from app.models.pipeline_error import PipelineError
from app.services.pipeline import process_charge_pipeline
from app.ai.service import AIService
from app.ai.schemas import AIAssessmentResponse, AssessmentType


@pytest.fixture
def client():
    return TestClient(app, headers={"X-Org-Id": "org_test_alpha"})


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_override_uncertain_charge_to_approve(client: TestClient, db_session: Session):
    """
    Test 1: Override an UNCERTAIN charge to approve.
    Verifies:
      - Overrides table row captures original ('UNCERTAIN') and new verdict ('APPROVED').
      - Reuses ClaimEngine plumbing to create human-originated claim with READY_FOR_REVIEW status.
      - Charges.status is updated to 'PROCESSED'.
    """
    # 1. Create a fresh test charge with an UNCERTAIN assessment in assessment_log (no claim)
    test_unit_id = f"TEST-OVR-UNC-{uuid.uuid4().hex[:6].upper()}"
    test_cid = f"CHG-OVR-{uuid.uuid4().hex[:8].upper()}"

    charge = Charge(
        charge_id=test_cid,
        unit_id=test_unit_id,
        fnsku=f"FNSKU-{uuid.uuid4().hex[:6].upper()}",
        sku=f"SKU-{uuid.uuid4().hex[:6].upper()}",
        charge_type="inbound_defect_fee",
        amount=Decimal("45.50"),
        currency="USD",
        charge_date=datetime.now(timezone.utc),
        source_report="fee_report",
        status="PENDING",
        org_id="org_test_alpha",
    )
    db_session.add(charge)
    db_session.flush()

    # Add evidence for this charge
    ev = Evidence(
        evidence_id=f"EV-OVR-{uuid.uuid4().hex[:6].upper()}",
        unit_id=test_unit_id,
        fnsku=charge.fnsku,
        sku=charge.sku,
        evidence_type="photo",
        source_manager="ReceivingDock",
        evidence_content={"notes": "Conflicting barcode photo"},
        evidence_timestamp=datetime.now(timezone.utc),
        org_id="org_test_alpha",
    )
    db_session.add(ev)

    # Add UNCERTAIN assessment log
    log_entry = AssessmentLog(
        charge_id=charge.id,
        assessment="UNCERTAIN",
        claim_supported=False,
        claim_amount=None,
        confidence=Decimal("0.5000"),
        reason="Automated model could not distinguish repackaging label from vendor label",
        evidence_ids=[ev.evidence_id],
        org_id="org_test_alpha",
    )
    db_session.add(log_entry)
    db_session.commit()

    # 2. Call POST /charges/{charge_id}/override
    override_payload = {
        "new_verdict": "APPROVED",
        "reason": "Supervisor inspected dock high-res photo: vendor barcode was clearly intact; defect fee is invalid.",
        "reviewer_id": "supervisor_alice",
    }
    response = client.post(f"/charges/{test_cid}/override", json=override_payload)
    assert response.status_code == 200, f"Override failed: {response.text}"
    data = response.json()

    assert data["charge_id"] == test_cid
    assert data["original_assessment"] == "UNCERTAIN"
    assert data["new_verdict"] == "APPROVED"
    assert "supervisor_alice" in data["reviewer_id"]
    assert data["claim_id"] is not None

    # 3. Verify database persistence
    # Verify overrides row
    ovr_row = db_session.scalars(
        select(Override).where(Override.charge_id == charge.id)
    ).first()
    assert ovr_row is not None
    assert ovr_row.original_assessment == "UNCERTAIN"
    assert ovr_row.new_verdict == "APPROVED"
    assert ovr_row.reviewer_id == "supervisor_alice"
    assert ovr_row.reason == override_payload["reason"]

    # Verify claim row created with human-originated note
    claim_row = db_session.scalars(
        select(Claim).where(Claim.charge_id == charge.id)
    ).first()
    assert claim_row is not None
    assert claim_row.claim_id == data["claim_id"]
    assert claim_row.status == "READY_FOR_REVIEW"
    assert "Human operator override (supervisor_alice)" in claim_row.explanation
    assert claim_row.claim_amount == Decimal("45.50")


def test_override_contradicted_claim_to_reject(client: TestClient, db_session: Session):
    """
    Test 2: Override a CONTRADICTED claim to reject.
    Verifies:
      - Overrides table row captures original assessment and verdict.
      - Existing claim.status is updated to 'REJECTED'.
      - Claim explanation captures rejection justification.
    """
    # 1. Create a fresh charge and claim (CONTRADICTED)
    test_cid = f"CHG-REJ-{uuid.uuid4().hex[:8].upper()}"
    test_clm_id = f"CLM-REJ-{uuid.uuid4().hex[:8].upper()}"

    charge = Charge(
        charge_id=test_cid,
        charge_type="inbound_defect_fee",
        amount=Decimal("28.00"),
        currency="USD",
        charge_date=datetime.now(timezone.utc),
        source_report="fee_report",
        status="PROCESSED",
        org_id="org_test_alpha",
    )
    db_session.add(charge)
    db_session.flush()

    claim = Claim(
        claim_id=test_clm_id,
        charge_id=charge.id,
        assessment="CONTRADICTED",
        claim_amount=Decimal("28.00"),
        confidence=Decimal("0.9200"),
        explanation="Automated AI claimed vendor label was correct.",
        status="READY_FOR_REVIEW",
        source_manager="Prep",
        org_id="org_test_alpha",
    )
    db_session.add(claim)
    db_session.commit()

    # 2. Call POST /charges/{charge_id}/override to reject
    override_payload = {
        "new_verdict": "REJECTED",
        "reason": "Secondary check confirmed the label was partially torn by vendor, fee is legitimate.",
        "reviewer_id": "senior_ops_bob",
    }
    response = client.post(f"/charges/{test_cid}/override", json=override_payload)
    assert response.status_code == 200, f"Override failed: {response.text}"
    data = response.json()

    assert data["charge_id"] == test_cid
    assert data["claim_id"] == test_clm_id
    assert data["new_verdict"] == "REJECTED"

    # 3. Verify database state
    ovr_row = db_session.scalars(
        select(Override).where(Override.charge_id == charge.id)
    ).first()
    assert ovr_row is not None
    assert ovr_row.new_verdict == "REJECTED"
    assert ovr_row.reviewer_id == "senior_ops_bob"

    db_session.refresh(claim)
    assert claim.status == "REJECTED"
    assert "Human override REJECTED (senior_ops_bob)" in claim.explanation


def test_overrides_table_is_append_only(db_session: Session):
    """
    Test 3: Confirm overrides table is strictly append-only (cannot UPDATE or DELETE).
    Database trigger 'trg_prevent_overrides_mutation' blocks updates/deletions.
    """
    test_cid = f"CHG-APP-{uuid.uuid4().hex[:8].upper()}"
    charge = Charge(
        charge_id=test_cid,
        charge_type="inbound_defect_fee",
        amount=Decimal("15.00"),
        currency="USD",
        charge_date=datetime.now(timezone.utc),
        source_report="fee_report",
        status="PROCESSED",
        org_id="org_test_alpha",
    )
    db_session.add(charge)
    db_session.flush()

    override_record = Override(
        charge_id=charge.id,
        claim_id=None,
        org_id="org_test_alpha",
        original_assessment="UNCERTAIN",
        original_status="PENDING",
        new_verdict="APPROVED",
        reason="Initial human approval justification.",
        reviewer_id="auditor_test",
    )
    db_session.add(override_record)
    db_session.commit()
    override_id = override_record.id

    # Attempt UPDATE -> Must fail with database exception
    with pytest.raises(Exception) as exc_info:
        db_session.execute(
            text("UPDATE overrides SET reason = 'Malicious alteration' WHERE id = :id"),
            {"id": override_id},
        )
        db_session.commit()
    db_session.rollback()
    assert "immutable audit records" in str(exc_info.value).lower() or "overrides" in str(exc_info.value).lower()

    # Attempt DELETE -> Must fail with database exception
    with pytest.raises(Exception) as exc_info:
        db_session.execute(
            text("DELETE FROM overrides WHERE id = :id AND org_id LIKE 'org_test_%'"),
            {"id": override_id},
        )
        db_session.commit()
    db_session.rollback()
    assert "immutable audit records" in str(exc_info.value).lower() or "overrides" in str(exc_info.value).lower()


def test_fail_open_durable_error_persistence_and_retry(client: TestClient, db_session: Session):
    """
    Test 4: Engineering Rule 3 (Fail Open).
    Forces a pipeline ERROR during execution.
    Verifies:
      - Durable pending record is written to pipeline_errors with stage, error_reason, and status='pending'.
      - Retrievable via GET /charges/failed-pending API.
      - When simulated failure is removed, reprocessing succeeds and resolves the pending error record.
    """
    test_cid = f"CHG-FAILOPEN-{uuid.uuid4().hex[:8].upper()}"
    test_uid = f"UNIT-FAILOPEN-{uuid.uuid4().hex[:6].upper()}"

    charge = Charge(
        charge_id=test_cid,
        unit_id=test_uid,
        charge_type="inbound_defect_fee",
        amount=Decimal("35.00"),
        currency="USD",
        charge_date=datetime.now(timezone.utc),
        source_report="fee_report",
        status="PENDING",
        org_id="org_test_alpha",
    )
    db_session.add(charge)

    ev = Evidence(
        evidence_id=f"EV-FAIL-{uuid.uuid4().hex[:6].upper()}",
        unit_id=test_uid,
        evidence_type="photo",
        source_manager="ReceivingDock",
        evidence_content={"notes": "Inspection capture"},
        evidence_timestamp=datetime.now(timezone.utc),
        org_id="org_test_alpha",
    )
    db_session.add(ev)
    db_session.commit()

    # Mock AIService to simulate a timeout/error
    class FailingAIService(AIService):
        def assess_recovery(self, *args, **kwargs):
            raise TimeoutError("Simulated LLM gateway connection timeout after 30000ms")

    failing_service = FailingAIService()

    # 1. Run pipeline with simulated failure
    result = process_charge_pipeline(charge_id=test_cid, db=db_session, ai_service=failing_service)
    assert result.outcome == "ERROR"
    assert "TimeoutError" in result.reason or "timeout" in result.reason.lower()

    # 2. Confirm durable record exists in pipeline_errors table via direct query
    error_row = db_session.scalars(
        select(PipelineError).where(
            PipelineError.charge_id == charge.id,
            PipelineError.status == "pending",
        )
    ).first()
    assert error_row is not None
    assert error_row.stage == "ai_reasoning"
    assert "TimeoutError" in error_row.error_reason
    assert error_row.status == "pending"

    # 3. Confirm retrievable via GET /charges/failed-pending API
    response = client.get("/charges/failed-pending")
    assert response.status_code == 200
    failed_items = response.json()["items"]
    matching = [it for it in failed_items if it["charge_id"] == test_cid]
    assert len(matching) == 1
    assert matching[0]["stage"] == "ai_reasoning"
    assert matching[0]["status"] == "pending"

    # 4. Remove simulated failure and reprocess with a succeeding service
    class SuccessAIService(AIService):
        def assess_recovery(self, *args, **kwargs):
            return AIAssessmentResponse(
                assessment=AssessmentType.CONTRADICTED,
                claim_supported=True,
                claim_amount=Decimal("35.00"),
                confidence=0.95,
                reason="Recovery verified by operational evidence",
                evidence_ids=[ev.evidence_id],
            )

    retry_result = process_charge_pipeline(charge_id=test_cid, db=db_session, ai_service=SuccessAIService())
    assert retry_result.outcome == "CLAIM_CREATED"

    # 5. Confirm pending record is marked resolved
    db_session.refresh(error_row)
    assert error_row.status == "resolved"


def test_human_override_claim_dashboard_metrics_distinction(client: TestClient, db_session: Session):
    """
    Tier 1 Metric Integrity Requirement:
    A human override claim:
      - Sets confidence=None on the assessment_log row.
      - MUST NOT appear in GET /dashboard/metrics claims_by_assessment counts (not a genuine AI evaluation).
      - MUST appear in GET /dashboard/metrics claims_by_status counts under READY_FOR_REVIEW.
    """
    # 1. Capture baseline metrics from GET /dashboard/metrics
    resp_base = client.get("/dashboard/metrics")
    assert resp_base.status_code == 200
    base_metrics = resp_base.json()

    base_contradicted = base_metrics["claims_by_assessment"].get("CONTRADICTED", 0)
    base_ready_for_review = base_metrics["claims_by_status"].get("READY_FOR_REVIEW", 0)

    # 2. Create an unasserted charge to override
    test_cid = f"CHG-DASH-OVR-{uuid.uuid4().hex[:8].upper()}"
    test_uid = f"UNIT-DASH-OVR-{uuid.uuid4().hex[:6].upper()}"

    charge = Charge(
        charge_id=test_cid,
        unit_id=test_uid,
        charge_type="inbound_defect_fee",
        amount=Decimal("50.00"),
        currency="USD",
        charge_date=datetime.now(timezone.utc),
        source_report="fee_report",
        status="PENDING",
        org_id="org_test_alpha",
    )
    db_session.add(charge)
    db_session.commit()

    # Call POST /charges/{charge_id}/override to approve and create a human-override claim
    override_payload = {
        "new_verdict": "APPROVED",
        "reason": "Auditor confirmed packaging defect is carrier fault, manual approval override.",
        "reviewer_id": "auditor_override_test",
    }
    response = client.post(f"/charges/{test_cid}/override", json=override_payload)
    assert response.status_code == 200, f"Override failed: {response.text}"
    override_resp = response.json()
    assert override_resp["claim_id"] is not None

    # 3. Direct verification of assessment_log row in database: confidence MUST be None
    log_row = db_session.scalars(
        select(AssessmentLog)
        .where(
            AssessmentLog.charge_id == charge.id,
            AssessmentLog.reason.like("%auditor_override_test%"),
        )
    ).first()
    assert log_row is not None
    assert log_row.confidence is None, f"Expected AssessmentLog.confidence to be None, got {log_row.confidence}"
    assert log_row.assessment == "CONTRADICTED"

    # 4. Fetch metrics after creating human override claim
    resp_after = client.get("/dashboard/metrics")
    assert resp_after.status_code == 200
    after_metrics = resp_after.json()

    after_contradicted = after_metrics["claims_by_assessment"].get("CONTRADICTED", 0)
    after_ready_for_review = after_metrics["claims_by_status"].get("READY_FOR_REVIEW", 0)

    # ASSERTION 1: claims_by_assessment did NOT increment CONTRADICTED count (confidence=None excluded)
    assert after_contradicted == base_contradicted, (
        f"claims_by_assessment CONTRADICTED count increased from {base_contradicted} to {after_contradicted}, "
        f"meaning human override was incorrectly counted as an AI evaluation!"
    )

    # ASSERTION 2: claims_by_status DID increment READY_FOR_REVIEW count by 1 (operational status respected)
    assert after_ready_for_review == base_ready_for_review + 1, (
        f"claims_by_status READY_FOR_REVIEW count should have incremented by 1 (from {base_ready_for_review} to {after_ready_for_review})"
    )

