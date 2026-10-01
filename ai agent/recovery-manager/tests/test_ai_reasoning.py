"""Comprehensive Phase 5 AI Reasoning / Recovery Assessment Tests.

Verifies all 24 required test scenarios from Phase 5 specification:
1. CONTRADICTED with valid evidence
2. SUPPORTED with valid evidence
3. SILENT with empty evidence
4. UNCERTAIN with conflicting evidence
5. Multiple evidence IDs returned
6. Invalid evidence ID returned by mocked LLM -> rejected
7. Claim amount cannot exceed charge amount
8. SUPPORTED cannot produce a supported recovery claim
9. SILENT cannot produce a claim
10. UNCERTAIN cannot produce a claim
11. Malformed LLM output -> controlled failure
12. Invalid assessment value -> rejected
13. Invalid confidence -> rejected
14. Empty reason -> rejected
15. Duplicate input preserved
16. Already-reimbursed input preserved
17. Missing API key handled
18. Provider/API failure handled
19. API endpoint validation
20. No database mutation
21. No claim creation
22. No evidence retrieval inside AI service
23. Evidence IDs are restricted to supplied evidence
24. Prompt contains the required evidence-first constraints
"""

from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import sys
from unittest.mock import MagicMock, patch

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
from app.ai.client import AnthropicClient
from app.ai.gemini_client import GeminiClient
from app.ai.exceptions import (
    AIConfigurationError,
    AIOutputValidationError,
    AIProviderError,
    ClaimAmountValidationError,
    InvalidEvidenceIDError,
)
from app.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from app.ai.schemas import (
    AIAssessmentRequest,
    AIAssessmentResponse,
    AssessmentType,
    ChargeInputSchema,
    EvidenceInputSchema,
    ProcessingStateSchema,
)
from app.ai.service import AIService, ai_service


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app, headers={"X-Org-Id": "org_test_alpha"}, raise_server_exceptions=False)


@pytest.fixture
def db():
    """Database session fixture for mutation checks."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def sample_charge():
    """Standard sample charge schema for test inputs."""
    return ChargeInputSchema(
        charge_id="CHG-TEST-001",
        charge_type="Polybagging Defect",
        amount=Decimal("150.00"),
        shipment_id="FBA17Z88Y12",
        order_id=None,
        sku="SKU-TEST-ITEM",
        asin="B00EXAMPLE",
        charge_date=datetime(2026, 3, 1, 10, 0, tzinfo=timezone.utc),
    )


@pytest.fixture
def sample_evidence_1():
    """Standard sample evidence 1."""
    return EvidenceInputSchema(
        evidence_id="EVD-TEST-001",
        source_manager="Prep",
        evidence_type="packaging_check",
        evidence_timestamp=datetime(2026, 3, 1, 8, 30, tzinfo=timezone.utc),
        evidence_content={"polybag_applied": True, "thickness_mil": 1.8, "result": "PASS"},
        matched_by="shipment_id",
        match_value="FBA17Z88Y12",
        matched_keys=["shipment_id", "sku"],
    )


@pytest.fixture
def sample_evidence_2():
    """Standard sample evidence 2."""
    return EvidenceInputSchema(
        evidence_id="EVD-TEST-002",
        source_manager="Pack",
        evidence_type="carton_seal_audit",
        evidence_timestamp=datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc),
        evidence_content={"carton_intact": True, "tamper_tape": True},
        matched_by="sku",
        match_value="SKU-TEST-ITEM",
        matched_keys=["sku"],
    )


# ==============================================================================
# 1. CONTRADICTED with valid evidence
# ==============================================================================
def test_01_contradicted_with_valid_evidence(sample_charge, sample_evidence_1):
    """Requirement 1: CONTRADICTED assessment where evidence disproves charge reason."""
    mock_llm_json = {
        "assessment": "CONTRADICTED",
        "claim_supported": True,
        "claim_amount": 150.00,
        "confidence": 0.95,
        "reason": "Prep audit EVD-TEST-001 confirms polybagging was completed with 1.8 mil thickness, directly contradicting fee.",
        "evidence_ids": ["EVD-TEST-001"],
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=False),
    )

    response = service.assess_recovery(request)
    assert response.assessment == AssessmentType.CONTRADICTED
    assert response.claim_supported is True
    assert response.claim_amount == Decimal("150.00")
    assert response.confidence == 0.95
    assert response.evidence_ids == ["EVD-TEST-001"]
    assert "contradicting" in response.reason.lower()


# ==============================================================================
# 2. SUPPORTED with valid evidence
# ==============================================================================
def test_02_supported_with_valid_evidence(sample_charge, sample_evidence_1):
    """Requirement 2: SUPPORTED assessment where evidence confirms charge reason."""
    mock_llm_json = {
        "assessment": "SUPPORTED",
        "claim_supported": False,
        "claim_amount": None,
        "confidence": 0.92,
        "reason": "Evidence confirms the item arrived unbagged at receiving dock, supporting the charge.",
        "evidence_ids": ["EVD-TEST-001"],
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
    )

    response = service.assess_recovery(request)
    assert response.assessment == AssessmentType.SUPPORTED
    assert response.claim_supported is False
    assert response.claim_amount is None
    assert response.confidence == 0.92
    assert response.evidence_ids == ["EVD-TEST-001"]


# ==============================================================================
# 3. SILENT with empty evidence
# ==============================================================================
def test_03_silent_with_empty_evidence(sample_charge):
    """Requirement 3: SILENT assessment when no evidence records are supplied."""
    mock_llm_json = {
        "assessment": "SILENT",
        "claim_supported": False,
        "claim_amount": None,
        "confidence": 1.0,
        "reason": "No evidence was supplied for this charge. Cannot establish or contest liability.",
        "evidence_ids": [],
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[],
    )

    response = service.assess_recovery(request)
    assert response.assessment == AssessmentType.SILENT
    assert response.claim_supported is False
    assert response.claim_amount is None
    assert response.evidence_ids == []


# ==============================================================================
# 4. UNCERTAIN with conflicting evidence
# ==============================================================================
def test_04_uncertain_with_conflicting_evidence(sample_charge, sample_evidence_1, sample_evidence_2):
    """Requirement 4: UNCERTAIN assessment when evidence records conflict."""
    mock_llm_json = {
        "assessment": "UNCERTAIN",
        "claim_supported": False,
        "claim_amount": None,
        "confidence": 0.50,
        "reason": "Prep report indicates pass while Receiving log indicates defect. Evidence is conflicting.",
        "evidence_ids": ["EVD-TEST-001", "EVD-TEST-002"],
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1, sample_evidence_2],
    )

    response = service.assess_recovery(request)
    assert response.assessment == AssessmentType.UNCERTAIN
    assert response.claim_supported is False
    assert response.claim_amount is None
    assert len(response.evidence_ids) == 2


# ==============================================================================
# 5. Multiple evidence IDs returned
# ==============================================================================
def test_05_multiple_evidence_ids_returned(sample_charge, sample_evidence_1, sample_evidence_2):
    """Requirement 5: Model can legitimately cite multiple supplied evidence IDs."""
    mock_llm_json = {
        "assessment": "CONTRADICTED",
        "claim_supported": True,
        "claim_amount": 150.00,
        "confidence": 0.98,
        "reason": "Both Prep and Pack logs confirm full packaging and sealing compliance.",
        "evidence_ids": ["EVD-TEST-001", "EVD-TEST-002"],
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1, sample_evidence_2],
    )

    response = service.assess_recovery(request)
    assert response.evidence_ids == ["EVD-TEST-001", "EVD-TEST-002"]


# ==============================================================================
# 6. Invalid evidence ID returned by mocked LLM -> rejected
# ==============================================================================
def test_06_invalid_evidence_id_returned_by_mocked_llm_rejected(sample_charge, sample_evidence_1):
    """Requirement 6: Hallucinated evidence ID not in supplied evidence must be rejected."""
    mock_llm_json = {
        "assessment": "CONTRADICTED",
        "claim_supported": True,
        "claim_amount": 150.00,
        "confidence": 0.90,
        "reason": "Contradicted by external document.",
        "evidence_ids": ["EVD-TEST-999-HALLUCINATED"],
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
    )

    with pytest.raises(InvalidEvidenceIDError) as exc_info:
        service.assess_recovery(request)

    assert "EVD-TEST-999-HALLUCINATED" in str(exc_info.value)
    assert "not in supplied evidence" in str(exc_info.value)


# ==============================================================================
# 7. Claim amount cannot exceed charge amount
# ==============================================================================
def test_07_claim_amount_cannot_exceed_charge_amount(sample_charge, sample_evidence_1):
    """Requirement 7: AI cannot recommend a claim amount greater than the charge amount."""
    # Charge amount is 150.00; model proposes 250.00
    mock_llm_json = {
        "assessment": "CONTRADICTED",
        "claim_supported": True,
        "claim_amount": 250.00,
        "confidence": 0.90,
        "reason": "Exaggerated claim amount.",
        "evidence_ids": ["EVD-TEST-001"],
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
    )

    with pytest.raises(ClaimAmountValidationError) as exc_info:
        service.assess_recovery(request)

    assert "cannot exceed charge amount" in str(exc_info.value)


# ==============================================================================
# 8. SUPPORTED cannot produce a supported recovery claim
# ==============================================================================
def test_08_supported_cannot_produce_a_supported_recovery_claim(sample_charge, sample_evidence_1):
    """Requirement 8: If assessment is SUPPORTED, claim_supported cannot be True or have claim_amount."""
    mock_llm_json = {
        "assessment": "SUPPORTED",
        "claim_supported": True,  # Illegal state
        "claim_amount": 100.00,
        "confidence": 0.85,
        "reason": "Erroneously claiming recovery when charge is supported.",
        "evidence_ids": ["EVD-TEST-001"],
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
    )

    with pytest.raises(AIOutputValidationError) as exc_info:
        service.assess_recovery(request)

    assert "cannot produce a supported recovery claim" in str(exc_info.value)


# ==============================================================================
# 9. SILENT cannot produce a claim
# ==============================================================================
def test_09_silent_cannot_produce_a_claim(sample_charge):
    """Requirement 9: SILENT assessment cannot have claim_supported=True or claim_amount > 0."""
    mock_llm_json = {
        "assessment": "SILENT",
        "claim_supported": True,  # Illegal state
        "claim_amount": 150.00,
        "confidence": 0.50,
        "reason": "Trying to force claim without evidence.",
        "evidence_ids": [],
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[],
    )

    with pytest.raises(AIOutputValidationError) as exc_info:
        service.assess_recovery(request)

    assert "cannot produce a supported recovery claim" in str(exc_info.value)


# ==============================================================================
# 10. UNCERTAIN cannot produce a claim
# ==============================================================================
def test_10_uncertain_cannot_produce_a_claim(sample_charge, sample_evidence_1):
    """Requirement 10: UNCERTAIN assessment cannot have claim_supported=True or claim_amount > 0."""
    mock_llm_json = {
        "assessment": "UNCERTAIN",
        "claim_supported": True,  # Illegal state
        "claim_amount": 100.00,
        "confidence": 0.60,
        "reason": "Uncertain evidence cannot justify claim.",
        "evidence_ids": ["EVD-TEST-001"],
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
    )

    with pytest.raises(AIOutputValidationError) as exc_info:
        service.assess_recovery(request)

    assert "cannot produce a supported recovery claim" in str(exc_info.value)


# ==============================================================================
# 11. Malformed LLM output -> controlled failure
# ==============================================================================
def test_11_malformed_llm_output_controlled_failure(sample_charge, sample_evidence_1):
    """Requirement 11: Non-JSON / malformed output raises AIOutputValidationError without crash."""
    malformed_outputs = [
        "This is not JSON at all.",
        "{ incomplete json: ",
        "['array', 'not', 'object']",
        "",
    ]
    for output in malformed_outputs:
        mock_client = MagicMock(spec=AnthropicClient)
        mock_client.generate_assessment.return_value = output

        service = AIService(client=mock_client)
        request = AIAssessmentRequest(
            charge=sample_charge,
            evidence=[sample_evidence_1],
        )

        with pytest.raises(AIOutputValidationError):
            service.assess_recovery(request)


# ==============================================================================
# 12. Invalid assessment value -> rejected
# ==============================================================================
def test_12_invalid_assessment_value_rejected(sample_charge, sample_evidence_1):
    """Requirement 12: Invalid assessment string (not one of the 4 allowed) is rejected."""
    mock_llm_json = {
        "assessment": "DISPUTED",  # Invalid enum
        "claim_supported": True,
        "claim_amount": 100.00,
        "confidence": 0.90,
        "reason": "Invalid assessment enum.",
        "evidence_ids": ["EVD-TEST-001"],
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
    )

    with pytest.raises(AIOutputValidationError):
        service.assess_recovery(request)


# ==============================================================================
# 13. Invalid confidence -> rejected
# ==============================================================================
def test_13_invalid_confidence_rejected(sample_charge, sample_evidence_1):
    """Requirement 13: Confidence outside [0.0, 1.0] must be rejected."""
    for invalid_conf in [-0.1, 1.05, 99.0]:
        mock_llm_json = {
            "assessment": "CONTRADICTED",
            "claim_supported": True,
            "claim_amount": 150.00,
            "confidence": invalid_conf,
            "reason": "Invalid confidence bounds.",
            "evidence_ids": ["EVD-TEST-001"],
        }
        mock_client = MagicMock(spec=AnthropicClient)
        mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

        service = AIService(client=mock_client)
        request = AIAssessmentRequest(
            charge=sample_charge,
            evidence=[sample_evidence_1],
        )

        with pytest.raises(AIOutputValidationError):
            service.assess_recovery(request)


# ==============================================================================
# 14. Empty reason -> rejected
# ==============================================================================
def test_14_empty_reason_rejected(sample_charge, sample_evidence_1):
    """Requirement 14: Empty or whitespace reason must be rejected."""
    for empty_reason in ["", "   ", "\n\t"]:
        mock_llm_json = {
            "assessment": "CONTRADICTED",
            "claim_supported": True,
            "claim_amount": 150.00,
            "confidence": 0.90,
            "reason": empty_reason,
            "evidence_ids": ["EVD-TEST-001"],
        }
        mock_client = MagicMock(spec=AnthropicClient)
        mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

        service = AIService(client=mock_client)
        request = AIAssessmentRequest(
            charge=sample_charge,
            evidence=[sample_evidence_1],
        )

        with pytest.raises(AIOutputValidationError):
            service.assess_recovery(request)


# ==============================================================================
# 15. Duplicate input preserved
# ==============================================================================
def test_15_duplicate_input_preserved(sample_charge, sample_evidence_1):
    """Requirement 15: Duplicate state is preserved and correctly included in user prompt."""
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=True, already_reimbursed=False),
    )
    assert request.processing_state.duplicate is True
    assert request.processing_state.already_reimbursed is False

    user_prompt = build_user_prompt(request)
    assert '"duplicate": true' in user_prompt
    assert '"already_reimbursed": false' in user_prompt


# ==============================================================================
# 16. Already-reimbursed input preserved
# ==============================================================================
def test_16_already_reimbursed_input_preserved(sample_charge, sample_evidence_1):
    """Requirement 16: Already-reimbursed state is preserved and correctly included in user prompt."""
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
        processing_state=ProcessingStateSchema(duplicate=False, already_reimbursed=True),
    )
    assert request.processing_state.duplicate is False
    assert request.processing_state.already_reimbursed is True

    user_prompt = build_user_prompt(request)
    assert '"duplicate": false' in user_prompt
    assert '"already_reimbursed": true' in user_prompt


# ==============================================================================
# 17. Missing API key handled
# ==============================================================================
def test_17_missing_api_key_handled():
    """Requirement 17: Missing API keys raise clean AIConfigurationError."""
    with patch("app.ai.client.settings.anthropic_api_key", None):
        anthropic_client = AnthropicClient(api_key=None)
        with pytest.raises(AIConfigurationError) as exc_info:
            _ = anthropic_client.client
        assert "ANTHROPIC_API_KEY is not configured" in str(exc_info.value)

    with patch("app.ai.gemini_client.settings.gemini_api_key", None):
        gemini_client = GeminiClient(api_key=None)
        with pytest.raises(AIConfigurationError) as exc_info:
            _ = gemini_client.client
        assert "GEMINI_API_KEY is not configured" in str(exc_info.value)


# ==============================================================================
# 18. Provider/API failure handled
# ==============================================================================
def test_18_provider_api_failure_handled():
    """Requirement 18: Provider API failures are caught and wrapped in sanitized AIProviderError."""
    from anthropic import APIConnectionError

    mock_client = AnthropicClient(api_key="sk-ant-test-fake-key")
    mock_client._client = MagicMock(
        messages=MagicMock(
            create=MagicMock(side_effect=APIConnectionError(request=MagicMock()))
        )
    )

    with pytest.raises(AIProviderError) as exc_info:
        mock_client.generate_assessment("system prompt", "user prompt")

    # Must not leak secret or raw details
    assert "sk-ant" not in str(exc_info.value)
    assert "connection error" in str(exc_info.value).lower()

    # Gemini failure handling & secret protection
    from google.genai.errors import ServerError
    gemini_client = GeminiClient(api_key="AQ.SecretKeyTest12345", max_retries=0)
    mock_gclient = MagicMock()
    mock_gclient.models.generate_content.side_effect = ServerError(
        503,
        {"error": {"code": 503, "message": "High demand"}},
    )
    gemini_client._client = mock_gclient

    with pytest.raises(AIProviderError) as exc_info_gemini:
        gemini_client.generate_assessment("system prompt", "user prompt")

    assert "AQ.SecretKey" not in str(exc_info_gemini.value)
    assert "server error" in str(exc_info_gemini.value).lower()


# ==============================================================================
# 19. API endpoint validation
# ==============================================================================
def test_19_api_endpoint_validation(client: TestClient, sample_charge, sample_evidence_1):
    """Requirement 19: POST /ai/assess endpoint validates input and returns structured assessment."""
    mock_llm_json = {
        "assessment": "CONTRADICTED",
        "claim_supported": True,
        "claim_amount": 150.00,
        "confidence": 0.95,
        "reason": "Polybag packaging check passed.",
        "evidence_ids": ["EVD-TEST-001"],
    }

    # 1. Successful 200 response
    with patch.object(
        ai_service,
        "assess_recovery",
        return_value=AIAssessmentResponse.model_validate(mock_llm_json),
    ):
        payload = {
            "charge": {
                "charge_id": sample_charge.charge_id,
                "charge_type": sample_charge.charge_type,
                "amount": "150.00",
                "shipment_id": sample_charge.shipment_id,
            },
            "evidence": [
                {
                    "evidence_id": sample_evidence_1.evidence_id,
                    "source_manager": sample_evidence_1.source_manager,
                    "evidence_type": sample_evidence_1.evidence_type,
                    "evidence_timestamp": sample_evidence_1.evidence_timestamp.isoformat(),
                    "evidence_content": sample_evidence_1.evidence_content,
                    "matched_by": sample_evidence_1.matched_by,
                    "match_value": sample_evidence_1.match_value,
                }
            ],
            "processing_state": {"duplicate": False, "already_reimbursed": False},
        }
        res = client.post("/ai/assess", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["assessment"] == "CONTRADICTED"
        assert data["claim_supported"] is True
        assert Decimal(str(data["claim_amount"])) == Decimal("150.00")
        assert data["evidence_ids"] == ["EVD-TEST-001"]

    # 2. Invalid request body -> 422
    bad_payload = {"charge": {"charge_id": ""}}  # Missing required fields
    res = client.post("/ai/assess", json=bad_payload)
    assert res.status_code == 422

    # 3. Model outputs hallucinated evidence ID -> 422 handled
    mock_inner_client = MagicMock(spec=AnthropicClient)
    mock_inner_client.generate_assessment.return_value = json.dumps({
        "assessment": "CONTRADICTED",
        "claim_supported": True,
        "claim_amount": 150.00,
        "confidence": 0.95,
        "reason": "Valid reason.",
        "evidence_ids": ["EVD-UNKNOWN-999"],
    })
    with patch.object(ai_service, "_client", mock_inner_client):
        res = client.post("/ai/assess", json=payload)
        assert res.status_code == 422
        assert "not in supplied evidence" in res.json()["detail"]

    # 4. Configuration error (missing API key) -> 503
    with patch.object(
        ai_service,
        "assess_recovery",
        side_effect=AIConfigurationError("ANTHROPIC_API_KEY is not configured."),
    ):
        res = client.post("/ai/assess", json=payload)
        assert res.status_code == 503

    # 5. Provider failure -> 502
    with patch.object(
        ai_service,
        "assess_recovery",
        side_effect=AIProviderError("AI reasoning provider connection error."),
    ):
        res = client.post("/ai/assess", json=payload)
        assert res.status_code == 502


# ==============================================================================
# 20. No database mutation
# ==============================================================================
def test_20_no_database_mutation(db: Session, sample_charge, sample_evidence_1):
    """Requirement 20: AI Reasoning service and endpoint perform zero database mutations."""
    # Capture counts before
    initial_charges = db.scalar(select(text("count(*)")).select_from(Charge))
    initial_evidence = db.scalar(select(text("count(*)")).select_from(Evidence))
    initial_claims = db.scalar(select(text("count(*)")).select_from(Claim))
    initial_claim_ev = db.scalar(select(text("count(*)")).select_from(ClaimEvidence))
    initial_reimbs = db.scalar(select(text("count(*)")).select_from(Reimbursement))

    mock_llm_json = {
        "assessment": "CONTRADICTED",
        "claim_supported": True,
        "claim_amount": 150.00,
        "confidence": 0.95,
        "reason": "Packaging check PASS confirms polybag was applied.",
        "evidence_ids": ["EVD-TEST-001"],
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
    )
    _ = service.assess_recovery(request)

    # Verify counts after
    assert db.scalar(select(text("count(*)")).select_from(Charge)) == initial_charges
    assert db.scalar(select(text("count(*)")).select_from(Evidence)) == initial_evidence
    assert db.scalar(select(text("count(*)")).select_from(Claim)) == initial_claims
    assert db.scalar(select(text("count(*)")).select_from(ClaimEvidence)) == initial_claim_ev
    assert db.scalar(select(text("count(*)")).select_from(Reimbursement)) == initial_reimbs


# ==============================================================================
# 21. No claim creation
# ==============================================================================
def test_21_no_claim_creation(db: Session, sample_charge, sample_evidence_1):
    """Requirement 21: Claims table is untouched during Phase 5 reasoning."""
    initial_claims_count = db.scalar(select(text("count(*)")).select_from(Claim))

    mock_llm_json = {
        "assessment": "CONTRADICTED",
        "claim_supported": True,
        "claim_amount": 150.00,
        "confidence": 0.95,
        "reason": "Proof directly contradicts fee.",
        "evidence_ids": ["EVD-TEST-001"],
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
    )
    result = service.assess_recovery(request)
    assert result.claim_supported is True

    # Confirm no claim record was inserted
    final_claims_count = db.scalar(select(text("count(*)")).select_from(Claim))
    assert final_claims_count == initial_claims_count


# ==============================================================================
# 22. No evidence retrieval inside AI service
# ==============================================================================
def test_22_no_evidence_retrieval_inside_ai_service():
    """Requirement 22: AI service does not import database sessions, query tables, or retrieve evidence."""
    source_service = (backend_dir / "app" / "ai" / "service.py").read_text(encoding="utf-8")
    source_route = (backend_dir / "app" / "api" / "routes" / "ai.py").read_text(encoding="utf-8")
    combined = source_service + "\n" + source_route

    # Strict prohibitions
    assert "Session" not in combined
    assert "select(" not in combined
    assert "execute(" not in combined
    assert "query(" not in combined
    assert "get_db" not in combined
    assert "evidence_engine" not in combined
    assert "get_evidence_for_charge" not in combined


# ==============================================================================
# 23. Evidence IDs are restricted to supplied evidence
# ==============================================================================
def test_23_evidence_ids_are_restricted_to_supplied_evidence(sample_charge, sample_evidence_1):
    """Requirement 23: Strict set membership validation between returned and supplied evidence IDs."""
    # When evidence list has EVD-TEST-001, any other ID fails
    mock_llm_json = {
        "assessment": "CONTRADICTED",
        "claim_supported": True,
        "claim_amount": 150.00,
        "confidence": 0.95,
        "reason": "Reason with hallucinated ID.",
        "evidence_ids": ["EVD-TEST-001", "EVD-HALLUCINATED-002"],
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
    )

    with pytest.raises(InvalidEvidenceIDError) as exc_info:
        service.assess_recovery(request)

    assert "EVD-HALLUCINATED-002" in str(exc_info.value)


# ==============================================================================
# 24. Prompt contains the required evidence-first constraints
# ==============================================================================
def test_24_prompt_contains_the_required_evidence_first_constraints():
    """Requirement 24: SYSTEM_PROMPT contains all 12 explicit constraints and evidence-first principles."""
    assert "Evidence relevance has already been determined deterministically by the Evidence Engine." in SYSTEM_PROMPT
    assert "Use ONLY supplied charge data." in SYSTEM_PROMPT
    assert "Use ONLY supplied evidence." in SYSTEM_PROMPT
    assert "Do not invent facts." in SYSTEM_PROMPT
    assert "Do not infer undocumented operational events." in SYSTEM_PROMPT
    assert "Do not search for more evidence." in SYSTEM_PROMPT
    assert "Do not use external knowledge to manufacture evidence." in SYSTEM_PROMPT
    assert "If evidence is absent, return SILENT." in SYSTEM_PROMPT
    assert "If evidence conflicts or is ambiguous, return UNCERTAIN." in SYSTEM_PROMPT
    assert "CONTRADICTED requires direct documentary contradiction." in SYSTEM_PROMPT
    assert "SUPPORTED requires evidence supporting the charge." in SYSTEM_PROMPT
    assert "Every evidence_id must come directly from the supplied evidence." in SYSTEM_PROMPT
    assert "Return only the required structured output." in SYSTEM_PROMPT


# ==============================================================================
# Additional Architectural & Security Boundaries
# ==============================================================================
def test_25_markdown_codeblock_cleaning(sample_charge, sample_evidence_1):
    """Test that model output wrapped in ```json ... ``` codeblocks is correctly parsed."""
    wrapped_json = f"""```json
{{
  "assessment": "CONTRADICTED",
  "claim_supported": true,
  "claim_amount": 150.00,
  "confidence": 0.95,
  "reason": "Polybagging passed cleanly.",
  "evidence_ids": ["{sample_evidence_1.evidence_id}"]
}}
```"""
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = wrapped_json

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
    )
    result = service.assess_recovery(request)
    assert result.assessment == AssessmentType.CONTRADICTED
    assert result.claim_supported is True


def test_26_extra_fields_forbidden(sample_charge, sample_evidence_1):
    """Test that extra unmodeled fields from the model cause validation failure."""
    mock_llm_json = {
        "assessment": "CONTRADICTED",
        "claim_supported": True,
        "claim_amount": 150.00,
        "confidence": 0.95,
        "reason": "Valid reason.",
        "evidence_ids": ["EVD-TEST-001"],
        "unauthorized_field": "injected_data",
    }
    mock_client = MagicMock(spec=AnthropicClient)
    mock_client.generate_assessment.return_value = json.dumps(mock_llm_json)

    service = AIService(client=mock_client)
    request = AIAssessmentRequest(
        charge=sample_charge,
        evidence=[sample_evidence_1],
    )

    with pytest.raises(AIOutputValidationError):
        service.assess_recovery(request)

