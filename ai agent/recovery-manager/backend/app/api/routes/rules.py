"""API routes for Phase 6 Deterministic Rule Validation."""

from fastapi import APIRouter, status
from app.rules.schemas import RuleValidationRequest, RuleValidationResult
from app.rules.service import rule_validator

router = APIRouter(prefix="/rules", tags=["Rule Validation"])


@router.post(
    "/validate",
    response_model=RuleValidationResult,
    status_code=status.HTTP_200_OK,
    summary="Deterministically validate recovery assessment against operational business rules",
)
def validate_rules_endpoint(request: RuleValidationRequest) -> RuleValidationResult:
    """
    Deterministically validate a recovery assessment against business rules.

    Strictly satisfies Phase 6 boundaries:
    - 100% deterministic execution.
    - NO Anthropic API calls or LLM reasoning.
    - NO database queries, claim creation, or mutation.
    - Fail-closed validation logic.
    """
    return rule_validator.validate(request)
