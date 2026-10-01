"""Comprehensive Phase 6 Deterministic Rule Validation Tests.

Verifies all requirements from Phase 6 specification:
1. Valid Recovery (CONTRADICTED, claim_supported=True, valid amount, valid evidence, no duplicate, not reimbursed)
2. CONTRADICTED without evidence -> blocked / rejected
3. Unknown evidence IDs -> blocked / rejected
4. Claim amount too large (claim_amount > charge.amount) -> rejected
5. Zero claim amount (claim_amount = 0) -> rejected
6. Negative claim amount (claim_amount < 0) -> rejected
7. SUPPORTED (both claim_supported=False/None and malicious claim_supported=True/claim_amount=50) -> automatic recovery = False
8. SILENT -> automatic recovery = False, human_review_required = False
9. UNCERTAIN -> automatic recovery = False, human_review_required = True
10. Duplicate -> automatic recovery = False
11. Already reimbursed -> automatic recovery = False
12. Duplicate + Already Reimbursed both True -> deterministic rejection
13. Evidence ID variations (one valid, multiple valid, one valid + one invalid, all invalid, empty)
14. Decimal precision: no floating-point arithmetic or rounding issues
15. Partial claim amount (claim_amount < charge.amount) -> eligible
16. Database mutation check: table row counts remain completely unchanged
17. No claim creation: verify zero claims created or persisted
18. No AI / Anthropic dependency: runs without API key or external provider
19. Integration from Phase 5 AI output via validate_assessment and from_ai_context
20. Deterministic rule priority order verification
21. API endpoint POST /rules/validate test coverage
22. Static architecture check: no forbidden AI, DB write, or vector calls in rules package
"""

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys
from unittest.mock import patch

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
from app.models.reimbursement import Reimbursement
from app.ai.schemas import (
    AIAssessmentRequest,
    AIAssessmentResponse,
    AssessmentType,
    ChargeInputSchema,
    EvidenceInputSchema,
    ProcessingStateSchema,
)
from app.rules.schemas import (
    RuleValidationRequest,
    RuleValidationResult,
    ValidationDecision,
)
from app.rules.service import RuleValidationService, rule_validator


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app, headers={"X-Org-Id": "org_test_alpha"}, raise_server_exceptions=False)


@pytest.fixture
def db():
    """Database session fixture for mutation verification."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_charge():
    """Standard test charge schema."""
    return ChargeInputSchema(
        charge_id="CHG-RULE-001",
        charge_type="Polybagging Defect",
        amount=Decimal("100.00"),
        shipment_id="FBA17Z88Y12",
        order_id=None,
        sku="SKU-RULE-TEST",
        asin="B00RULETEST",
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_evidence_1():
    """Standard sample evidence 1."""
    return EvidenceInputSchema(
        evidence_id="EVD-001",
        source_manager="Prep",
        evidence_type="packaging_check",
        evidence_timestamp=datetime(2026, 3, 1, 8, 30, tzinfo=timezone.utc),
        evidence_content={"polybag_applied": True, "thickness_mil": 1.8},
        matched_by="shipment_id",
        match_value="FBA17Z88Y12",
        matched_keys=["shipment_id"],
    )


@pytest.fixture
def sample_evidence_2():
    """Standard sample evidence 2."""
    return EvidenceInputSchema(
        evidence_id="EVD-002",
        source_manager="Receiving",
        evidence_type="scale_audit",
        evidence_timestamp=datetime(2026, 3, 1, 8, 45, tzinfo=timezone.utc),
        evidence_content={"actual_weight_lb": 2.1},
        matched_by="sku",
        match_value="SKU-RULE-TEST",
        matched_keys=["sku"],
    )


# ==============================================================================
# 1. Valid Recovery
# ==============================================================================
def test_01_valid_recovery_eligible(sample_charge, sample_evidence_1):
    """
    Requirement: Valid CONTRADICTED assessment where all business conditions pass.
    Expected: eligible_for_recovery = True, human_review_required = False, decision = ELIGIBLE.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is True
    assert result.human_review_required is False
    assert result.decision == ValidationDecision.ELIGIBLE
    assert result.status == ValidationDecision.ELIGIBLE
    assert result.claim_amount == Decimal("100.00")
    assert result.evidence_ids == ["EVD-001"]
    assert result.rule_code == "RULE_ELIGIBLE"
    assert "eligible for recovery" in result.reason.lower()


# ==============================================================================
# 2. CONTRADICTED Without Evidence
# ==============================================================================
def test_02_contradicted_without_evidence_rejected(sample_charge, sample_evidence_1):
    """
    Requirement: CONTRADICTED assessment with empty evidence_ids.
    Expected: eligible_for_recovery = False, decision = BLOCKED.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        evidence_ids=[],
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.human_review_required is False
    assert result.decision == ValidationDecision.BLOCKED
    assert result.rule_code == "RULE_NO_EVIDENCE"
    assert "documentary evidence is required" in result.reason.lower()


# ==============================================================================
# 3. Unknown Evidence IDs
# ==============================================================================
def test_03_unknown_evidence_id_rejected(sample_charge, sample_evidence_1):
    """
    Requirement: Assessment references evidence ID not present in supplied evidence.
    Supplied: EVD-001
    Referenced: EVD-001, EVD-999
    Expected: rejected, eligible_for_recovery = False, decision = BLOCKED.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        evidence_ids=["EVD-001", "EVD-999"],
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.decision == ValidationDecision.BLOCKED
    assert result.rule_code == "RULE_UNKNOWN_EVIDENCE"
    assert "EVD-999" in result.reason


# ==============================================================================
# 4. Claim Amount Too Large
# ==============================================================================
def test_04_claim_amount_exceeds_charge_amount_rejected(sample_charge, sample_evidence_1):
    """
    Requirement: claim_amount > charge.amount.
    charge.amount = 100.00, claim_amount = 100.01.
    Expected: rejected, eligible_for_recovery = False, decision = BLOCKED.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.01"),
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.decision == ValidationDecision.BLOCKED
    assert result.rule_code == "RULE_AMOUNT_EXCEEDS_CHARGE"
    assert "exceeds charge amount" in result.reason.lower()


# ==============================================================================
# 5. Zero Claim Amount
# ==============================================================================
def test_05_zero_claim_amount_rejected(sample_charge, sample_evidence_1):
    """
    Requirement: claim_amount = 0 for a claim-supported CONTRADICTED recovery.
    Expected: rejected, eligible_for_recovery = False, decision = BLOCKED.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("0.00"),
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.decision == ValidationDecision.BLOCKED
    assert result.rule_code == "RULE_INVALID_AMOUNT"
    assert "greater than zero" in result.reason.lower()


# ==============================================================================
# 6. Negative Claim Amount
# ==============================================================================
def test_06_negative_claim_amount_rejected(sample_charge, sample_evidence_1):
    """
    Requirement: Negative claim amount.
    Expected: rejected, eligible_for_recovery = False, decision = BLOCKED.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("-50.00"),
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.decision == ValidationDecision.BLOCKED
    assert result.rule_code == "RULE_INVALID_AMOUNT"
    assert "greater than zero" in result.reason.lower()


# ==============================================================================
# 7. SUPPORTED Rule
# ==============================================================================
def test_07a_supported_assessment_non_claim(sample_charge, sample_evidence_1):
    """
    Requirement: SUPPORTED with claim_supported=False, claim_amount=None.
    Expected: automatic recovery = False, decision = NON_CLAIM.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.SUPPORTED,
        claim_supported=False,
        claim_amount=None,
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.human_review_required is False
    assert result.decision == ValidationDecision.NON_CLAIM
    assert result.claim_amount is None
    assert result.rule_code == "RULE_SUPPORTED"


def test_07b_supported_assessment_malicious_input_blocked(sample_charge, sample_evidence_1):
    """
    Requirement: SUPPORTED with malicious/invalid claim_supported=True, claim_amount=50.
    Must never become claim-eligible.
    Expected: automatic recovery = False, decision = NON_CLAIM, claim_amount = None.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.SUPPORTED,
        claim_supported=True,
        claim_amount=Decimal("50.00"),
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.human_review_required is False
    assert result.decision == ValidationDecision.NON_CLAIM
    assert result.claim_amount is None


# ==============================================================================
# 8. SILENT Rule
# ==============================================================================
def test_08_silent_assessment_terminal_non_claim(sample_charge):
    """
    Requirement: SILENT assessment.
    Expected: automatic recovery = False, human_review_required = False, decision = NON_CLAIM.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.SILENT,
        claim_supported=False,
        claim_amount=None,
        evidence_ids=[],
        evidence=[],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.human_review_required is False
    assert result.decision == ValidationDecision.NON_CLAIM
    assert result.claim_amount is None
    assert result.rule_code == "RULE_SILENT"
    assert "insufficient operational evidence" in result.reason.lower()


# ==============================================================================
# 9. UNCERTAIN Rule
# ==============================================================================
def test_09_uncertain_assessment_requires_human_review(sample_charge, sample_evidence_1, sample_evidence_2):
    """
    Requirement: UNCERTAIN assessment.
    Expected: automatic recovery = False, human_review_required = True, decision = HUMAN_REVIEW.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.UNCERTAIN,
        claim_supported=False,
        claim_amount=None,
        evidence_ids=["EVD-001", "EVD-002"],
        evidence=[sample_evidence_1, sample_evidence_2],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.human_review_required is True
    assert result.decision == ValidationDecision.HUMAN_REVIEW
    assert result.claim_amount is None
    assert result.rule_code == "RULE_UNCERTAIN"
    assert "human review required" in result.reason.lower()


# ==============================================================================
# 10. Duplicate Rule
# ==============================================================================
def test_10_duplicate_blocks_automatic_recovery(sample_charge, sample_evidence_1):
    """
    Requirement: Valid CONTRADICTED assessment + duplicate = True.
    Expected: eligible_for_recovery = False, decision = BLOCKED.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=True, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.decision == ValidationDecision.BLOCKED
    assert result.rule_code == "RULE_DUPLICATE"
    assert "duplicate" in result.reason.lower()
    # Preserves assessment classification
    assert result.assessment == AssessmentType.CONTRADICTED


# ==============================================================================
# 11. Already Reimbursed Rule
# ==============================================================================
def test_11_already_reimbursed_blocks_automatic_recovery(sample_charge, sample_evidence_1):
    """
    Requirement: Valid CONTRADICTED assessment + already_reimbursed = True.
    Expected: eligible_for_recovery = False, decision = BLOCKED.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=True),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.decision == ValidationDecision.BLOCKED
    assert result.rule_code == "RULE_ALREADY_REIMBURSED"
    assert "already been reimbursed" in result.reason.lower()
    assert result.assessment == AssessmentType.CONTRADICTED


# ==============================================================================
# 12. Duplicate + Already Reimbursed
# ==============================================================================
def test_12_duplicate_and_already_reimbursed_both_true(sample_charge, sample_evidence_1):
    """
    Requirement: Both duplicate = True and already_reimbursed = True.
    Expected: eligible_for_recovery = False, decision = BLOCKED, deterministic outcome.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=True, already_reimbursed=True),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.decision == ValidationDecision.BLOCKED
    # Rule 1 (duplicate) triggers first in documented deterministic order
    assert result.rule_code == "RULE_DUPLICATE"


# ==============================================================================
# 13. Evidence ID Variations
# ==============================================================================
def test_13a_multiple_valid_evidence_ids(sample_charge, sample_evidence_1, sample_evidence_2):
    """Multiple valid evidence IDs present in supplied evidence -> eligible."""
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        evidence_ids=["EVD-001", "EVD-002"],
        evidence=[sample_evidence_1, sample_evidence_2],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is True
    assert result.decision == ValidationDecision.ELIGIBLE
    assert len(result.evidence_ids) == 2


def test_13b_one_valid_one_invalid_evidence_id(sample_charge, sample_evidence_1):
    """One valid ID + one invalid ID -> rejected (fail-closed)."""
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        evidence_ids=["EVD-001", "EVD-UNKNOWN"],
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.decision == ValidationDecision.BLOCKED
    assert result.rule_code == "RULE_UNKNOWN_EVIDENCE"
    assert "EVD-UNKNOWN" in result.reason


def test_13c_all_invalid_evidence_ids(sample_charge, sample_evidence_1):
    """All referenced IDs invalid -> rejected."""
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        evidence_ids=["EVD-X", "EVD-Y"],
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.decision == ValidationDecision.BLOCKED
    assert result.rule_code == "RULE_UNKNOWN_EVIDENCE"


def test_13d_supplied_evidence_ids_alone_cannot_authorize_evidence(sample_charge):
    """
    Regression Test: supplied_evidence_ids alone without actual evidence objects
    must NEVER authorize an evidence ID or permit recovery eligibility.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        evidence_ids=["EVIDENCE-999"],
        supplied_evidence_ids=["EVIDENCE-999"],
        evidence=[],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.decision == ValidationDecision.BLOCKED
    assert result.rule_code == "RULE_UNKNOWN_EVIDENCE"
    assert "EVIDENCE-999" in result.reason


# ==============================================================================
# 14. Decimal Precision
# ==============================================================================
def test_14_decimal_precision_exact_boundary(sample_charge, sample_evidence_1):
    """Monetary comparison uses exact Decimal values without floating-point errors."""
    exact_charge = ChargeInputSchema(
        charge_id="CHG-DECIMAL",
        charge_type="Fee",
        amount=Decimal("100.00"),
    )

    # 100.00 == 100.00 -> Eligible
    req_exact = RuleValidationRequest(
        charge=exact_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
    )
    assert rule_validator.validate(req_exact).eligible_for_recovery is True

    # 100.0001 > 100.00 -> Rejected
    req_over = RuleValidationRequest(
        charge=exact_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.0001"),
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
    )
    assert rule_validator.validate(req_over).eligible_for_recovery is False


# ==============================================================================
# 15. Partial Claim Amount
# ==============================================================================
def test_15_partial_claim_amount_eligible(sample_charge, sample_evidence_1):
    """Partial claim amount strictly between 0 and charge.amount is eligible."""
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("45.50"),
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is True
    assert result.claim_amount == Decimal("45.50")


# ==============================================================================
# 16. Database Mutation Check
# ==============================================================================
def test_16_database_remains_unmutated(db: Session, sample_charge, sample_evidence_1):
    """Phase 6 rule validation must NOT write to or mutate database tables."""
    charges_before = db.scalar(select(text("COUNT(*) FROM charges")))
    claims_before = db.scalar(select(text("COUNT(*) FROM claims")))
    claim_ev_before = db.scalar(select(text("COUNT(*) FROM claim_evidence")))
    evidence_before = db.scalar(select(text("COUNT(*) FROM evidence")))
    reimb_before = db.scalar(select(text("COUNT(*) FROM reimbursements")))

    # Run validation across various states
    for assessment in (AssessmentType.CONTRADICTED, AssessmentType.SUPPORTED, AssessmentType.SILENT, AssessmentType.UNCERTAIN):
        req = RuleValidationRequest(
            charge=sample_charge,
            assessment=assessment,
            claim_supported=(assessment == AssessmentType.CONTRADICTED),
            claim_amount=Decimal("100.00") if assessment == AssessmentType.CONTRADICTED else None,
            evidence_ids=["EVD-001"] if assessment != AssessmentType.SILENT else [],
            evidence=[sample_evidence_1],
            processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
        )
        rule_validator.validate(req)

    charges_after = db.scalar(select(text("COUNT(*) FROM charges")))
    claims_after = db.scalar(select(text("COUNT(*) FROM claims")))
    claim_ev_after = db.scalar(select(text("COUNT(*) FROM claim_evidence")))
    evidence_after = db.scalar(select(text("COUNT(*) FROM evidence")))
    reimb_after = db.scalar(select(text("COUNT(*) FROM reimbursements")))

    assert charges_before == charges_after
    assert claims_before == claims_after
    assert claim_ev_before == claim_ev_after
    assert evidence_before == evidence_after
    assert reimb_before == reimb_after


# ==============================================================================
# 17. No Claim Creation
# ==============================================================================
def test_17_no_claim_creation(db: Session, sample_charge, sample_evidence_1):
    """Verify that eligible rule validation does not insert into claims table."""
    claims_count_before = db.scalar(select(text("COUNT(*) FROM claims")))

    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
    )
    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is True

    claims_count_after = db.scalar(select(text("COUNT(*) FROM claims")))
    assert claims_count_before == claims_count_after


# ==============================================================================
# 18. No AI / Anthropic Dependency
# ==============================================================================
def test_18_no_ai_or_anthropic_call(sample_charge, sample_evidence_1, monkeypatch):
    """Verify Phase 6 executes with ANTHROPIC_API_KEY unset and without AI provider."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
    )

    with patch("anthropic.Anthropic") as mock_anthropic:
        result = rule_validator.validate(request)
        assert result.eligible_for_recovery is True
        mock_anthropic.assert_not_called()


# ==============================================================================
# 19. Phase 5 Integration (from_ai_context & validate_assessment)
# ==============================================================================
def test_19_phase_5_ai_assessment_integration(sample_charge, sample_evidence_1):
    """Verify direct integration with Phase 5 AIAssessmentRequest and AIAssessmentResponse."""
    ai_request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    ai_response = AIAssessmentResponse(
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("100.00"),
        confidence=0.98,
        reason="Prep audit confirms polybag was compliant.",
        evidence_ids=["EVD-001"],
    )

    # 1. validate_assessment convenience method
    result = rule_validator.validate_assessment(ai_request, ai_response)
    assert result.eligible_for_recovery is True
    assert result.decision == ValidationDecision.ELIGIBLE

    # 2. RuleValidationRequest.from_ai_context constructor
    val_req = RuleValidationRequest.from_ai_context(ai_request, ai_response)
    result2 = rule_validator.validate(val_req)
    assert result2.eligible_for_recovery is True


# ==============================================================================
# 20. Deterministic Rule Priority Order
# ==============================================================================
def test_20_deterministic_rule_priority_order(sample_charge, sample_evidence_1):
    """
    Verify rule precedence:
    Duplicate check precedes invalid claim amount check.
    Even with claim_amount = 999999 (invalid), duplicate = True triggers RULE_DUPLICATE.
    """
    request = RuleValidationRequest(
        charge=sample_charge,
        assessment=AssessmentType.CONTRADICTED,
        claim_supported=True,
        claim_amount=Decimal("999999.00"),  # Exceeds charge amount
        evidence_ids=["EVD-001"],
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=True, already_reimbursed=False),
    )

    result = rule_validator.validate(request)
    assert result.eligible_for_recovery is False
    assert result.rule_code == "RULE_DUPLICATE"


# ==============================================================================
# 21. API Endpoint POST /rules/validate
# ==============================================================================
def test_21a_api_endpoint_eligible(client: TestClient):
    """API endpoint returns 200 with ELIGIBLE decision for valid contradicted assessment."""
    payload = {
        "charge": {
            "charge_id": "CHG-API-001",
            "charge_type": "Defect",
            "amount": "120.00",
        },
        "assessment": "CONTRADICTED",
        "claim_supported": True,
        "claim_amount": "120.00",
        "evidence_ids": ["EVD-001"],
        "evidence": [
            {
                "evidence_id": "EVD-001",
                "source_manager": "Prep",
                "evidence_type": "packaging_check",
                "evidence_timestamp": "2026-03-01T08:30:00Z",
                "evidence_content": {"polybag_applied": True},
                "matched_by": "shipment_id",
                "match_value": "FBA17Z88Y12",
            }
        ],
        "processing_state": {
            "duplicate": False,
            "already_reimbursed": False,
        },
    }

    response = client.post("/rules/validate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["eligible_for_recovery"] is True
    assert data["decision"] == "ELIGIBLE"
    assert data["status"] == "ELIGIBLE"
    assert data["claim_amount"] == "120.00"
    assert data["rule_code"] == "RULE_ELIGIBLE"


def test_21b_api_endpoint_blocked_duplicate(client: TestClient):
    """API endpoint returns 200 with BLOCKED decision when duplicate=True."""
    payload = {
        "charge": {
            "charge_id": "CHG-API-002",
            "charge_type": "Defect",
            "amount": "120.00",
        },
        "assessment": "CONTRADICTED",
        "claim_supported": True,
        "claim_amount": "120.00",
        "evidence_ids": ["EVD-001"],
        "evidence": [
            {
                "evidence_id": "EVD-001",
                "source_manager": "Prep",
                "evidence_type": "packaging_check",
                "evidence_timestamp": "2026-03-01T08:30:00Z",
                "evidence_content": {"polybag_applied": True},
                "matched_by": "shipment_id",
                "match_value": "FBA17Z88Y12",
            }
        ],
        "processing_state": {
            "duplicate": True,
            "already_reimbursed": False,
        },
    }

    response = client.post("/rules/validate", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["eligible_for_recovery"] is False
    assert data["decision"] == "BLOCKED"
    assert data["rule_code"] == "RULE_DUPLICATE"


def test_21c_api_endpoint_malformed_input_returns_422(client: TestClient):
    """API endpoint returns 422 Unprocessable Entity when required charge is missing."""
    payload = {
        "assessment": "CONTRADICTED",
    }
    response = client.post("/rules/validate", json=payload)
    assert response.status_code == 422


# ==============================================================================
# 22. Static Architecture Check
# ==============================================================================
def test_22_static_architecture_check():
    """Verify Phase 6 files contain NO forbidden AI, DB write, or vector search imports."""
    rules_dir = backend_dir / "app" / "rules"
    forbidden_terms = [
        "anthropic",
        "Anthropic",
        "chat.completions",
        "AIService",
        "session.add",
        "session.commit",
        "INSERT INTO claims",
        "fuzzywuzzy",
        "levenshtein",
        "vector",
        "embedding",
    ]

    for py_file in rules_dir.glob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        for term in forbidden_terms:
            # Skip docstring mentions of prohibition (e.g. "- NO Anthropic API calls")
            code_lines = [
                line for line in content.splitlines()
                if not line.strip().startswith("-")
                and not line.strip().startswith("*")
                and not line.strip().startswith('"""')
                and not line.strip().startswith("#")
            ]
            code_text = "\n".join(code_lines)
            assert term not in code_text, (
                f"Forbidden term '{term}' found in code of {py_file.name}"
            )

