"""Phase 6 Deterministic Rule Validation Service.

Enforces business rules on Phase 5 AI recovery assessments.
Acts as a strict gating layer before future Phase 7 claim generation.

100% Deterministic:
- NO Anthropic API calls or LLM reasoning
- NO evidence retrieval or database queries
- NO claim creation or persistence
- NO database mutation
- NO fuzzy matching, semantic search, or vector embeddings
- Fail-closed validation logic
- Decimal precision for monetary amounts
"""

from decimal import Decimal
from typing import Set

from app.ai.schemas import (
    AIAssessmentRequest,
    AIAssessmentResponse,
    AssessmentType,
)
from app.core.logging import logger
from app.rules.schemas import (
    RuleValidationRequest,
    RuleValidationResult,
    ValidationDecision,
)


class RuleValidationService:
    """
    Deterministic Rule Validation Service.

    Validation Order:
    1. Operational Block — Duplicate Check:
       If processing_state.duplicate is True, block automatic recovery immediately.
    2. Operational Block — Already Reimbursed Check:
       If processing_state.already_reimbursed is True, block automatic recovery immediately.
    3. Terminal Non-Recovery — UNCERTAIN Assessment:
       Assessment is UNCERTAIN; flag for human review, no claim.
    4. Terminal Non-Recovery — SILENT Assessment:
       Assessment is SILENT; terminal non-claim due to lack of evidence.
    5. Terminal Non-Recovery — SUPPORTED Assessment:
       Assessment is SUPPORTED; marketplace charge corroborated by evidence; claim withheld.
    6. Recovery Rule A — CONTRADICTED Claim Supported Check:
       If assessment is CONTRADICTED but claim_supported is False, block recovery.
    7. Recovery Rule A — CONTRADICTED Evidence Presence Check:
       At least one evidence ID is required. If evidence_ids is empty, block recovery.
    8. Recovery Rule A — CONTRADICTED Evidence ID Validation:
       Every referenced evidence ID must exist in the supplied evidence set.
    9. Recovery Rule A — CONTRADICTED Monetary Precision & Boundary Check:
       Claim amount must be > 0 and <= charge.amount, verified with Decimal arithmetic.
    10. Recovery Rule A — Recovery Eligibility:
       All checks passed; charge is eligible for recovery claim generation.
    """

    def validate(self, request: RuleValidationRequest) -> RuleValidationResult:
        """
        Deterministically evaluate recovery assessment against operational business rules.
        Does NOT call AI, does NOT query DB, does NOT create claims.
        """
        charge_id = request.charge.charge_id
        assessment = request.assessment

        # ----------------------------------------------------------------------
        # Rule 1: Duplicate Check (Operational Block)
        # ----------------------------------------------------------------------
        if request.processing_state.duplicate:
            logger.info(f"Charge '{charge_id}' blocked: processing_state.duplicate is True.")
            return RuleValidationResult(
                charge_id=charge_id,
                assessment=assessment,
                eligible_for_recovery=False,
                human_review_required=False,
                claim_amount=None,
                evidence_ids=list(request.evidence_ids),
                decision=ValidationDecision.BLOCKED,
                status=ValidationDecision.BLOCKED,
                reason="Charge is flagged as duplicate in processing state; blocked from automatic recovery.",
                rule_code="RULE_DUPLICATE",
            )

        # ----------------------------------------------------------------------
        # Rule 2: Already Reimbursed Check (Operational Block)
        # ----------------------------------------------------------------------
        if request.processing_state.already_reimbursed:
            logger.info(f"Charge '{charge_id}' blocked: processing_state.already_reimbursed is True.")
            return RuleValidationResult(
                charge_id=charge_id,
                assessment=assessment,
                eligible_for_recovery=False,
                human_review_required=False,
                claim_amount=None,
                evidence_ids=list(request.evidence_ids),
                decision=ValidationDecision.BLOCKED,
                status=ValidationDecision.BLOCKED,
                reason="Charge has already been reimbursed; blocked from automatic recovery.",
                rule_code="RULE_ALREADY_REIMBURSED",
            )

        # ----------------------------------------------------------------------
        # Rule 3: UNCERTAIN Assessment (Human Review Required)
        # ----------------------------------------------------------------------
        if assessment == AssessmentType.UNCERTAIN:
            logger.info(f"Charge '{charge_id}' assessment is UNCERTAIN: flagged for human review.")
            return RuleValidationResult(
                charge_id=charge_id,
                assessment=assessment,
                eligible_for_recovery=False,
                human_review_required=True,
                claim_amount=None,
                evidence_ids=list(request.evidence_ids),
                decision=ValidationDecision.HUMAN_REVIEW,
                status=ValidationDecision.HUMAN_REVIEW,
                reason="Assessment is UNCERTAIN due to ambiguous or conflicting operational evidence; human review required.",
                rule_code="RULE_UNCERTAIN",
            )

        # ----------------------------------------------------------------------
        # Rule 4: SILENT Assessment (Terminal Non-Claim)
        # ----------------------------------------------------------------------
        if assessment == AssessmentType.SILENT:
            logger.info(f"Charge '{charge_id}' assessment is SILENT: terminal non-claim.")
            return RuleValidationResult(
                charge_id=charge_id,
                assessment=assessment,
                eligible_for_recovery=False,
                human_review_required=False,
                claim_amount=None,
                evidence_ids=list(request.evidence_ids),
                decision=ValidationDecision.NON_CLAIM,
                status=ValidationDecision.NON_CLAIM,
                reason="Assessment is SILENT; insufficient operational evidence to dispute charge.",
                rule_code="RULE_SILENT",
            )

        # ----------------------------------------------------------------------
        # Rule 5: SUPPORTED Assessment (Terminal Non-Claim)
        # Must never become claim-eligible regardless of claim_supported or claim_amount.
        # ----------------------------------------------------------------------
        if assessment == AssessmentType.SUPPORTED:
            logger.info(f"Charge '{charge_id}' assessment is SUPPORTED: claim withheld.")
            return RuleValidationResult(
                charge_id=charge_id,
                assessment=assessment,
                eligible_for_recovery=False,
                human_review_required=False,
                claim_amount=None,
                evidence_ids=list(request.evidence_ids),
                decision=ValidationDecision.NON_CLAIM,
                status=ValidationDecision.NON_CLAIM,
                reason="Assessment is SUPPORTED; operational evidence corroborates marketplace charge; claim withheld.",
                rule_code="RULE_SUPPORTED",
            )

        # ----------------------------------------------------------------------
        # CONTRADICTED Assessment Validation Pipeline
        # ----------------------------------------------------------------------
        if assessment == AssessmentType.CONTRADICTED:
            # Rule 6: claim_supported must be True
            if not request.claim_supported:
                logger.info(f"Charge '{charge_id}' CONTRADICTED assessment has claim_supported=False.")
                return RuleValidationResult(
                    charge_id=charge_id,
                    assessment=assessment,
                    eligible_for_recovery=False,
                    human_review_required=False,
                    claim_amount=None,
                    evidence_ids=list(request.evidence_ids),
                    decision=ValidationDecision.BLOCKED,
                    status=ValidationDecision.BLOCKED,
                    reason="Assessment is CONTRADICTED but claim_supported is False; recovery cannot proceed.",
                    rule_code="RULE_CLAIM_NOT_SUPPORTED",
                )

            # Rule 7: Documentary Evidence Requirement (evidence_ids must not be empty)
            if not request.evidence_ids:
                logger.info(f"Charge '{charge_id}' CONTRADICTED assessment has empty evidence_ids.")
                return RuleValidationResult(
                    charge_id=charge_id,
                    assessment=assessment,
                    eligible_for_recovery=False,
                    human_review_required=False,
                    claim_amount=None,
                    evidence_ids=[],
                    decision=ValidationDecision.BLOCKED,
                    status=ValidationDecision.BLOCKED,
                    reason="Assessment is CONTRADICTED but no evidence IDs were supplied; documentary evidence is required for recovery.",
                    rule_code="RULE_NO_EVIDENCE",
                )

            # Rule 8: Unknown Evidence IDs (every ID must exist in supplied evidence objects)
            allowed_ids: Set[str] = {ev.evidence_id for ev in request.evidence}

            unknown_ids = [eid for eid in request.evidence_ids if eid not in allowed_ids]
            if unknown_ids:
                logger.info(
                    f"Charge '{charge_id}' CONTRADICTED assessment referenced unknown evidence ID(s): {unknown_ids}."
                )
                return RuleValidationResult(
                    charge_id=charge_id,
                    assessment=assessment,
                    eligible_for_recovery=False,
                    human_review_required=False,
                    claim_amount=None,
                    evidence_ids=list(request.evidence_ids),
                    decision=ValidationDecision.BLOCKED,
                    status=ValidationDecision.BLOCKED,
                    reason=f"Referenced evidence ID(s) {sorted(unknown_ids)} do not exist in supplied evidence.",
                    rule_code="RULE_UNKNOWN_EVIDENCE",
                )

            # Rule 9: Monetary Precision & Boundary Check (Decimal arithmetic only)
            if request.claim_amount is None:
                logger.info(f"Charge '{charge_id}' CONTRADICTED assessment is missing claim_amount.")
                return RuleValidationResult(
                    charge_id=charge_id,
                    assessment=assessment,
                    eligible_for_recovery=False,
                    human_review_required=False,
                    claim_amount=None,
                    evidence_ids=list(request.evidence_ids),
                    decision=ValidationDecision.BLOCKED,
                    status=ValidationDecision.BLOCKED,
                    reason="Claim amount is missing for contradicted recovery.",
                    rule_code="RULE_MISSING_AMOUNT",
                )

            if request.claim_amount <= Decimal("0.00"):
                logger.info(
                    f"Charge '{charge_id}' CONTRADICTED assessment has non-positive claim_amount: {request.claim_amount}."
                )
                return RuleValidationResult(
                    charge_id=charge_id,
                    assessment=assessment,
                    eligible_for_recovery=False,
                    human_review_required=False,
                    claim_amount=None,
                    evidence_ids=list(request.evidence_ids),
                    decision=ValidationDecision.BLOCKED,
                    status=ValidationDecision.BLOCKED,
                    reason=f"Claim amount ({request.claim_amount}) must be greater than zero.",
                    rule_code="RULE_INVALID_AMOUNT",
                )

            if request.claim_amount > request.charge.amount:
                logger.info(
                    f"Charge '{charge_id}' claim_amount ({request.claim_amount}) exceeds charge amount ({request.charge.amount})."
                )
                return RuleValidationResult(
                    charge_id=charge_id,
                    assessment=assessment,
                    eligible_for_recovery=False,
                    human_review_required=False,
                    claim_amount=None,
                    evidence_ids=list(request.evidence_ids),
                    decision=ValidationDecision.BLOCKED,
                    status=ValidationDecision.BLOCKED,
                    reason=f"Claim amount ({request.claim_amount}) exceeds charge amount ({request.charge.amount}).",
                    rule_code="RULE_AMOUNT_EXCEEDS_CHARGE",
                )

            # Rule 10: All validation rules passed -> ELIGIBLE
            logger.info(f"Charge '{charge_id}' passed all business rules: eligible for recovery.")
            return RuleValidationResult(
                charge_id=charge_id,
                assessment=assessment,
                eligible_for_recovery=True,
                human_review_required=False,
                claim_amount=request.claim_amount,
                evidence_ids=list(request.evidence_ids),
                decision=ValidationDecision.ELIGIBLE,
                status=ValidationDecision.ELIGIBLE,
                reason=(
                    f"Assessment CONTRADICTED is verified with {len(request.evidence_ids)} valid evidence record(s); "
                    f"claim amount {request.claim_amount} does not exceed charge amount {request.charge.amount}; "
                    "eligible for recovery."
                ),
                rule_code="RULE_ELIGIBLE",
            )

        # Fail-closed fallback for any unrecognized assessment type
        logger.warning(f"Charge '{charge_id}' encountered unrecognized assessment: {assessment}.")
        return RuleValidationResult(
            charge_id=charge_id,
            assessment=assessment,
            eligible_for_recovery=False,
            human_review_required=False,
            claim_amount=None,
            evidence_ids=list(request.evidence_ids),
            decision=ValidationDecision.BLOCKED,
            status=ValidationDecision.BLOCKED,
            reason=f"Unrecognized assessment type: '{assessment}'.",
            rule_code="RULE_UNKNOWN_ASSESSMENT",
        )

    def validate_assessment(
        self,
        request: AIAssessmentRequest,
        response: AIAssessmentResponse,
    ) -> RuleValidationResult:
        """Convenience method to validate a Phase 5 assessment directly."""
        validation_request = RuleValidationRequest.from_ai_context(request, response)
        return self.validate(validation_request)


# Singleton instances
rule_validator = RuleValidationService()
rule_service = rule_validator
