"""API routes for Phase 5 AI Reasoning / Recovery Assessment."""

from fastapi import APIRouter, HTTPException, status
from app.ai.exceptions import (
    AIConfigurationError,
    AIOutputValidationError,
    AIProviderError,
    ClaimAmountValidationError,
    InvalidEvidenceIDError,
)
from app.ai.schemas import AIAssessmentRequest, AIAssessmentResponse
from app.ai.service import ai_service

router = APIRouter(prefix="/ai", tags=["AI Reasoning"])


@router.post(
    "/assess",
    response_model=AIAssessmentResponse,
    status_code=status.HTTP_200_OK,
    summary="Assess recovery claim potential from deterministically supplied evidence",
)
def assess_recovery_endpoint(request: AIAssessmentRequest) -> AIAssessmentResponse:
    """
    Evaluate deterministically retrieved evidence against a charge using AI reasoning.
    Strictly conforms to 'Evidence first, claim second':
    - Does NOT retrieve evidence or query database.
    - Does NOT create claims or mutate data.
    - Validates that returned evidence IDs exist in supplied evidence.
    """
    try:
        assessment = ai_service.assess_recovery(request)
        return assessment
    except AIConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except AIProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=str(exc),
        ) from exc
    except (InvalidEvidenceIDError, ClaimAmountValidationError, AIOutputValidationError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
