"""AI Reasoning Service for Phase 5 Recovery Assessment."""

import json
from decimal import Decimal
from typing import Optional, Union
from pydantic import ValidationError

from app.ai.client import AnthropicClient
from app.ai.gemini_client import GeminiClient
from app.ai.exceptions import (
    AIOutputValidationError,
    ClaimAmountValidationError,
    InvalidEvidenceIDError,
)
from app.ai.prompts import SYSTEM_PROMPT, build_user_prompt
from app.ai.schemas import (
    AIAssessmentRequest,
    AIAssessmentResponse,
    AssessmentType,
)
from app.core.logging import logger


class AIService:
    """
    Dedicated AI Reasoning Service.
    Interprets deterministically retrieved evidence against marketplace charges.
    Does NOT search the database, retrieve evidence, create claims, or mutate data.
    """

    def __init__(self, client: Optional[Union[GeminiClient, AnthropicClient]] = None):
        self._client = client

    @property
    def client(self) -> Union[GeminiClient, AnthropicClient]:
        if self._client is None:
            self._client = GeminiClient()
        return self._client

    def assess_recovery(self, request: AIAssessmentRequest) -> AIAssessmentResponse:
        """
        Evaluate deterministically retrieved evidence for a charge using AI reasoning.
        Enforces strict schema parsing, evidence ID validation, and claim amount invariants.
        """
        user_prompt = build_user_prompt(request)
        raw_output = self.client.generate_assessment(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=user_prompt,
        )

        return self._parse_and_validate(raw_output=raw_output, request=request)

    def _parse_and_validate(
        self,
        raw_output: str,
        request: AIAssessmentRequest,
    ) -> AIAssessmentResponse:
        """Parse raw model output and deterministically validate business invariants."""
        # 1. Clean markdown code fences if model returned ```json ... ```
        cleaned_output = raw_output.strip()
        if cleaned_output.startswith("```json"):
            cleaned_output = cleaned_output[7:]
        elif cleaned_output.startswith("```"):
            cleaned_output = cleaned_output[3:]
        if cleaned_output.endswith("```"):
            cleaned_output = cleaned_output[:-3]
        cleaned_output = cleaned_output.strip()

        # 2. Parse JSON
        try:
            parsed_json = json.loads(cleaned_output)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("AI model returned malformed JSON output.")
            raise AIOutputValidationError(f"AI response is not valid JSON: {exc}") from exc

        if not isinstance(parsed_json, dict):
            raise AIOutputValidationError("AI response must be a JSON object.")

        # 3. Validate against strict Pydantic schema
        try:
            assessment_response = AIAssessmentResponse.model_validate(parsed_json)
        except ValidationError as exc:
            logger.warning(f"AI model returned schema-violating output: {exc}")
            raise AIOutputValidationError(f"AI output schema violation: {exc}") from exc

        # 4. Deterministic Evidence-ID validation:
        # Every returned evidence_id MUST already exist in the supplied evidence.
        allowed_ids = {ev.evidence_id for ev in request.evidence}
        for eid in assessment_response.evidence_ids:
            if eid not in allowed_ids:
                logger.warning(
                    f"AI model hallucinated invalid evidence_id '{eid}' not in supplied evidence."
                )
                raise InvalidEvidenceIDError(
                    f"Evidence ID '{eid}' returned by AI was not in supplied evidence."
                )

        # 5. Deterministic Claim Amount Invariants:
        # Cannot exceed charge amount
        if assessment_response.claim_amount is not None:
            if assessment_response.claim_amount > request.charge.amount:
                logger.warning(
                    f"AI claim_amount {assessment_response.claim_amount} exceeds charge amount {request.charge.amount}."
                )
                raise ClaimAmountValidationError(
                    f"Claim amount {assessment_response.claim_amount} cannot exceed charge amount {request.charge.amount}."
                )

        # Invariants by assessment outcome
        if assessment_response.assessment == AssessmentType.CONTRADICTED:
            if assessment_response.claim_supported:
                if (
                    assessment_response.claim_amount is None
                    or assessment_response.claim_amount <= Decimal("0.00")
                ):
                    raise ClaimAmountValidationError(
                        "When assessment is CONTRADICTED and claim is supported, claim_amount must be greater than zero."
                    )
            else:
                if (
                    assessment_response.claim_amount is not None
                    and assessment_response.claim_amount > Decimal("0.00")
                ):
                    raise ClaimAmountValidationError(
                        "When claim_supported is false, claim_amount must be null or zero."
                    )
        elif assessment_response.assessment in (
            AssessmentType.SUPPORTED,
            AssessmentType.SILENT,
            AssessmentType.UNCERTAIN,
        ):
            if assessment_response.claim_supported:
                raise ClaimAmountValidationError(
                    f"Assessment '{assessment_response.assessment.value}' cannot produce a supported recovery claim."
                )
            if (
                assessment_response.claim_amount is not None
                and assessment_response.claim_amount > Decimal("0.00")
            ):
                raise ClaimAmountValidationError(
                    f"Assessment '{assessment_response.assessment.value}' cannot have a claim_amount greater than zero."
                )

        return assessment_response


ai_service = AIService()
