"""Phase 7 Claim Engine Service.

Consumes computed outputs from Phase 5 AI Reasoning and Phase 6 Deterministic
Rule Validation to decide whether and how to persist a claim record.

Guarantees:
- Idempotency on charge_id across all claims row statuses.
- Defense-in-depth re-verification before financial claim persistence.
- Single atomic database transaction with fail-closed rollback.
- Collision-resistant unique claim_id generation.
- Full multi-source manager provenance attribution.
"""

from decimal import Decimal
from typing import List, Optional
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.schemas import (
    AIAssessmentResponse,
    AssessmentType,
    EvidenceInputSchema,
    ProcessingStateSchema,
)
from app.claims.exceptions import ClaimIntegrityError, ClaimTransactionError
from app.claims.schemas import ClaimEngineRequest, ClaimEngineResult
from app.core.logging import logger
from app.models.charge import Charge
from app.models.claim import Claim
from app.models.claim_evidence import ClaimEvidence
from app.models.evidence import Evidence
from app.models.assessment_log import AssessmentLog
from app.rules.schemas import RuleValidationResult, ValidationDecision


class ClaimEngine:
    """Core domain service for evaluating and persisting recovery claims."""

    def __init__(self, db: Session):
        self.db = db

    def _generate_unique_claim_id(self) -> str:
        """
        Generate a unique external claim ID formatted as f"CLM-{uuid.uuid4().hex[:8].upper()}".
        Checks database for collisions and retries if needed.
        """
        for _ in range(5):
            candidate = f"CLM-{uuid.uuid4().hex[:8].upper()}"
            stmt = select(Claim.id).where(Claim.claim_id == candidate)
            exists = self.db.scalars(stmt).first()
            if not exists:
                return candidate
        # Extremely unlikely fallback with timestamp hex suffix
        return f"CLM-{uuid.uuid4().hex[:12].upper()}"

    def process_claim(
        self,
        charge_id: str,
        validation_result: RuleValidationResult,
        assessment_response: AIAssessmentResponse,
        evidence: Optional[List[EvidenceInputSchema]] = None,
        processing_state: Optional[ProcessingStateSchema] = None,
    ) -> ClaimEngineResult:
        """
        Process recovery decision and persist claims/claim_evidence records where applicable.

        Args:
            charge_id: External marketplace charge identifier.
            validation_result: Output from Phase 6 Rule Validation.
            assessment_response: Output from Phase 5 AI Reasoning.
            evidence: Operational evidence set supplied to reasoning & rules.
            processing_state: Flags for duplicate/already_reimbursed state.

        Returns:
            ClaimEngineResult structured response.
        """
        if evidence is None:
            evidence = []
        if processing_state is None:
            processing_state = ProcessingStateSchema()

        # Fetch underlying Charge entity by external charge_id
        charge_stmt = select(Charge).where(Charge.charge_id == charge_id)
        charge = self.db.scalars(charge_stmt).first()
        if not charge:
            raise ClaimIntegrityError(f"Charge with charge_id '{charge_id}' does not exist in database.")

        # ----------------------------------------------------------------------
        # 1. IDEMPOTENCY CHECK FIRST
        # Query claims for an existing row linked to this charge.id UUID
        # Reprocessing ANY charge that already has ANY claims row is a strict no-op.
        # ----------------------------------------------------------------------
        existing_claim_stmt = select(Claim).where(Claim.charge_id == charge.id)
        existing_claim = self.db.scalars(existing_claim_stmt).first()
        if existing_claim:
            logger.info(
                f"Idempotency hit: Charge '{charge_id}' already has claim '{existing_claim.claim_id}' "
                f"with status '{existing_claim.status}'."
            )
            # Fetch associated evidence_ids if any
            ev_stmt = (
                select(Evidence.evidence_id)
                .join(ClaimEvidence, ClaimEvidence.evidence_id == Evidence.id)
                .where(ClaimEvidence.claim_id == existing_claim.id)
            )
            linked_evidence_ids = list(self.db.scalars(ev_stmt).all())

            return ClaimEngineResult(
                outcome="ALREADY_CLAIMED",
                charge_id=charge_id,
                claim_id=existing_claim.claim_id,
                status=existing_claim.status,
                reason=(
                    f"Charge '{charge_id}' was already processed. Existing claim '{existing_claim.claim_id}' "
                    f"has status '{existing_claim.status}'."
                ),
                claim_amount=existing_claim.claim_amount,
                evidence_ids=linked_evidence_ids,
            )

        # ----------------------------------------------------------------------
        # Defensive Check: Validate Consistency between Decision & Flags
        # ----------------------------------------------------------------------
        if (
            validation_result.decision == ValidationDecision.HUMAN_REVIEW
            and not validation_result.human_review_required
        ) or (
            validation_result.decision != ValidationDecision.HUMAN_REVIEW
            and validation_result.human_review_required
        ):
            logger.error(
                f"Contract disagreement for charge '{charge_id}': decision='{validation_result.decision}' "
                f"conflicts with human_review_required={validation_result.human_review_required}."
            )
            # Create a REJECTED claim row defensively
            return self._persist_rejected_claim(
                charge=charge,
                assessment_response=assessment_response,
                reason="Validation contract disagreement between decision and human_review_required.",
            )

        # ----------------------------------------------------------------------
        # 2. NON_CLAIM (SUPPORTED / SILENT) -> log to assessment_log, return NO_CLAIM
        # ----------------------------------------------------------------------
        if validation_result.decision == ValidationDecision.NON_CLAIM:
            logger.info(
                f"Charge '{charge_id}' evaluated as NON_CLAIM ({validation_result.assessment.value}). "
                f"No claim row created; logged to assessment_log."
            )
            try:
                conf = (
                    Decimal(str(round(assessment_response.confidence, 4)))
                    if assessment_response.confidence is not None
                    else None
                )
                log_entry = AssessmentLog(
                    charge_id=charge.id,
                    assessment=validation_result.assessment.value,
                    claim_supported=assessment_response.claim_supported,
                    claim_amount=None,
                    confidence=conf,
                    reason=validation_result.reason or assessment_response.reason,
                    evidence_ids=assessment_response.evidence_ids or [],
                    org_id=charge.org_id,
                )
                self.db.add(log_entry)
                self.db.commit()
            except Exception as exc:
                self.db.rollback()
                logger.error(f"Transaction failure while persisting assessment log for charge '{charge_id}': {exc}")
                raise ClaimTransactionError(f"Database transaction failed while logging assessment: {exc}") from exc

            return ClaimEngineResult(
                outcome="NO_CLAIM",
                charge_id=charge_id,
                claim_id=None,
                status=None,
                reason=validation_result.reason,
                claim_amount=None,
                evidence_ids=[],
            )

        # ----------------------------------------------------------------------
        # 3. HUMAN_REVIEW (UNCERTAIN) -> log to assessment_log, return HUMAN_REVIEW
        # ----------------------------------------------------------------------
        if (
            validation_result.decision == ValidationDecision.HUMAN_REVIEW
            and validation_result.human_review_required
        ):
            logger.info(
                f"Charge '{charge_id}' requires human review (UNCERTAIN assessment). "
                f"No claim row created; logged to assessment_log."
            )
            all_evidence_ids = [e.evidence_id for e in evidence] if evidence else list(validation_result.evidence_ids)
            try:
                conf = (
                    Decimal(str(round(assessment_response.confidence, 4)))
                    if assessment_response.confidence is not None
                    else None
                )
                log_entry = AssessmentLog(
                    charge_id=charge.id,
                    assessment=validation_result.assessment.value,
                    claim_supported=assessment_response.claim_supported,
                    claim_amount=None,
                    confidence=conf,
                    reason=assessment_response.reason or validation_result.reason,
                    evidence_ids=all_evidence_ids,
                    org_id=charge.org_id,
                )
                self.db.add(log_entry)
                self.db.commit()
            except Exception as exc:
                self.db.rollback()
                logger.error(f"Transaction failure while persisting assessment log for charge '{charge_id}': {exc}")
                raise ClaimTransactionError(f"Database transaction failed while logging assessment: {exc}") from exc

            return ClaimEngineResult(
                outcome="HUMAN_REVIEW",
                charge_id=charge_id,
                claim_id=None,
                status=None,
                reason=assessment_response.reason or validation_result.reason,
                claim_amount=None,
                evidence_ids=all_evidence_ids,
            )

        # ----------------------------------------------------------------------
        # 4. BLOCKED -> determine DUPLICATE vs ALREADY_REIMBURSED from rule_code
        # ----------------------------------------------------------------------
        if validation_result.decision == ValidationDecision.BLOCKED:
            if validation_result.rule_code == "RULE_DUPLICATE":
                target_status = "DUPLICATE"
            elif validation_result.rule_code == "RULE_ALREADY_REIMBURSED":
                target_status = "ALREADY_REIMBURSED"
            else:
                target_status = "REJECTED"

            return self._persist_blocked_or_rejected_claim(
                charge=charge,
                assessment_response=assessment_response,
                status=target_status,
                outcome="BLOCKED",
                reason=validation_result.reason,
            )

        # ----------------------------------------------------------------------
        # 5. ELIGIBLE (decision == ELIGIBLE and eligible_for_recovery == True)
        # ----------------------------------------------------------------------
        if (
            validation_result.decision == ValidationDecision.ELIGIBLE
            and validation_result.eligible_for_recovery
        ):
            # 5a. Independent re-verification (do not trust upstream blindly)
            # Re-verify assessment is CONTRADICTED
            if assessment_response.assessment != AssessmentType.CONTRADICTED:
                return self._persist_rejected_claim(
                    charge=charge,
                    assessment_response=assessment_response,
                    reason=f"Claim engine re-check failed: assessment '{assessment_response.assessment.value}' is not CONTRADICTED.",
                )

            # Re-verify claim_amount: present, > 0, <= charge.amount fresh from DB
            amt = validation_result.claim_amount or assessment_response.claim_amount
            if amt is None:
                return self._persist_rejected_claim(
                    charge=charge,
                    assessment_response=assessment_response,
                    reason="Claim engine re-check failed: claim_amount is missing.",
                )
            if amt <= Decimal("0.00"):
                return self._persist_rejected_claim(
                    charge=charge,
                    assessment_response=assessment_response,
                    reason=f"Claim engine re-check failed: claim_amount {amt} must be greater than zero.",
                )
            if amt > charge.amount:
                return self._persist_rejected_claim(
                    charge=charge,
                    assessment_response=assessment_response,
                    reason=(
                        f"Claim engine re-check failed: claim_amount {amt} exceeds "
                        f"charge amount {charge.amount}."
                    ),
                )

            # Re-verify evidence_ids: non-empty, and every evidence_id resolves to an actual row in evidence table
            candidate_evidence_ids = validation_result.evidence_ids or assessment_response.evidence_ids
            if not candidate_evidence_ids:
                return self._persist_rejected_claim(
                    charge=charge,
                    assessment_response=assessment_response,
                    reason="Claim engine re-check failed: no evidence IDs provided.",
                )

            # Fresh DB query to fetch evidence rows
            ev_records_stmt = select(Evidence).where(Evidence.evidence_id.in_(candidate_evidence_ids))
            db_evidence_records = list(self.db.scalars(ev_records_stmt).all())
            found_evidence_id_map = {e.evidence_id: e for e in db_evidence_records}

            missing_ids = [eid for eid in candidate_evidence_ids if eid not in found_evidence_id_map]
            if missing_ids:
                return self._persist_rejected_claim(
                    charge=charge,
                    assessment_response=assessment_response,
                    reason=f"Claim engine re-check failed: evidence IDs not found in database: {missing_ids}.",
                )

            # 5b. Generate unique claim_id
            claim_id_str = self._generate_unique_claim_id()

            # 5c. Source manager resolution:
            # If all evidence rows share one source_manager, use it.
            # If evidence spans multiple managers, join distinct sorted values with "+" (e.g. "Prep+Receiving").
            # This preserves full multi-station audit provenance without arbitrarily favoring one department.
            distinct_managers = sorted({e.source_manager for e in db_evidence_records if e.source_manager})
            resolved_source_manager = "+".join(distinct_managers) if distinct_managers else None

            # 5d. SINGLE DATABASE TRANSACTION
            try:
                # 1. INSERT claims row
                new_claim = Claim(
                    claim_id=claim_id_str,
                    charge_id=charge.id,
                    assessment=assessment_response.assessment.value,
                    claim_amount=amt,
                    confidence=Decimal(str(round(assessment_response.confidence, 4))),
                    explanation=assessment_response.reason,
                    status="READY_FOR_REVIEW",
                    source_manager=resolved_source_manager,
                    org_id=charge.org_id,
                )
                self.db.add(new_claim)
                self.db.flush()  # Populates new_claim.id

                # 2. INSERT claim_evidence rows
                for eid in candidate_evidence_ids:
                    ev_model = found_evidence_id_map[eid]
                    link = ClaimEvidence(
                        claim_id=new_claim.id,
                        evidence_id=ev_model.id,
                        org_id=charge.org_id,
                    )
                    self.db.add(link)

                # 3. UPDATE charges.status
                # In 001_initial_schema.sql line 53, charges.status allowed comments: "PENDING, PROCESSED, DISPUTED".
                # When a recovery claim is created, 'DISPUTED' or 'PROCESSED' marks that the charge is now claimed.
                # 'PROCESSED' is standard across schema.md and seed data.
                charge.status = "PROCESSED"
                self.db.add(charge)

                # 4. INSERT assessment_log row in the exact same atomic transaction
                conf = (
                    Decimal(str(round(assessment_response.confidence, 4)))
                    if assessment_response.confidence is not None
                    else None
                )
                log_entry = AssessmentLog(
                    charge_id=charge.id,
                    assessment=assessment_response.assessment.value,
                    claim_supported=assessment_response.claim_supported,
                    claim_amount=amt,
                    confidence=conf,
                    reason=assessment_response.reason,
                    evidence_ids=list(candidate_evidence_ids),
                    org_id=charge.org_id,
                )
                self.db.add(log_entry)

                self.db.commit()
                logger.info(
                    f"Successfully created claim '{claim_id_str}' for charge '{charge_id}' "
                    f"amount={amt} with {len(candidate_evidence_ids)} evidence links and logged assessment."
                )

                return ClaimEngineResult(
                    outcome="CLAIM_CREATED",
                    charge_id=charge_id,
                    claim_id=claim_id_str,
                    status="READY_FOR_REVIEW",
                    reason=assessment_response.reason,
                    claim_amount=amt,
                    evidence_ids=list(candidate_evidence_ids),
                )

            except Exception as exc:
                self.db.rollback()
                logger.error(f"Transaction failure while persisting claim for charge '{charge_id}': {exc}")
                raise ClaimTransactionError(f"Database transaction failed while creating claim: {exc}") from exc

        # Fallback for unexpected state combination
        return self._persist_rejected_claim(
            charge=charge,
            assessment_response=assessment_response,
            reason="Unrecognized decision or invalid recovery eligibility combination.",
        )

    def _persist_blocked_or_rejected_claim(
        self,
        charge: Charge,
        assessment_response: AIAssessmentResponse,
        status: str,
        outcome: str,
        reason: str,
    ) -> ClaimEngineResult:
        """Helper to atomically persist a non-financial claim row (BLOCKED or REJECTED) and assessment_log."""
        claim_id_str = self._generate_unique_claim_id()
        try:
            conf = (
                Decimal(str(round(assessment_response.confidence, 4)))
                if assessment_response.confidence is not None
                else None
            )
            claim_row = Claim(
                claim_id=claim_id_str,
                charge_id=charge.id,
                assessment=assessment_response.assessment.value,
                claim_amount=None,  # Explicitly NULL
                confidence=conf,
                explanation=reason,
                status=status,
                source_manager=None,
                org_id=charge.org_id,
            )
            self.db.add(claim_row)

            # Atomic assessment_log row in same transaction
            log_entry = AssessmentLog(
                charge_id=charge.id,
                assessment=assessment_response.assessment.value,
                claim_supported=assessment_response.claim_supported,
                claim_amount=None,
                confidence=conf,
                reason=reason,
                evidence_ids=assessment_response.evidence_ids or [],
                org_id=charge.org_id,
            )
            self.db.add(log_entry)

            self.db.commit()

            return ClaimEngineResult(
                outcome=outcome,  # "BLOCKED" or "REJECTED_AT_CLAIM_ENGINE"
                charge_id=charge.charge_id,
                claim_id=claim_id_str,
                status=status,
                reason=reason,
                claim_amount=None,
                evidence_ids=[],
            )
        except Exception as exc:
            self.db.rollback()
            logger.error(f"Transaction failure while persisting non-financial claim '{status}': {exc}")
            raise ClaimTransactionError(f"Database transaction failed: {exc}") from exc

    def _persist_rejected_claim(
        self,
        charge: Charge,
        assessment_response: AIAssessmentResponse,
        reason: str,
    ) -> ClaimEngineResult:
        """Helper to persist a REJECTED claim row when claim engine re-verification fails."""
        return self._persist_blocked_or_rejected_claim(
            charge=charge,
            assessment_response=assessment_response,
            status="REJECTED",
            outcome="REJECTED_AT_CLAIM_ENGINE",
            reason=reason,
        )

    def create_human_override_claim(
        self,
        charge: Charge,
        reason: str,
        reviewer_id: str,
        new_verdict: str = "APPROVED",
    ) -> Claim:
        """
        Creates a claim originated from human operator override.
        Reuses ClaimEngine persistence, claim_id generation, evidence linking,
        and atomic status tracking with explicit human-originated audit trail.
        """
        # Fetch any available evidence linked to this charge's identifiers
        evidence_conditions = []
        if charge.unit_id:
            evidence_conditions.append(Evidence.unit_id == charge.unit_id)
        if charge.fnsku:
            evidence_conditions.append(Evidence.fnsku == charge.fnsku)
        if charge.sku:
            evidence_conditions.append(Evidence.sku == charge.sku)
        if charge.shipment_id:
            evidence_conditions.append(Evidence.shipment_id == charge.shipment_id)
        if charge.order_id:
            evidence_conditions.append(Evidence.order_id == charge.order_id)

        if evidence_conditions:
            from sqlalchemy import or_
            evidence_stmt = select(Evidence).where(or_(*evidence_conditions))
            db_evidence = list(self.db.scalars(evidence_stmt).all())
        else:
            db_evidence = []
        distinct_managers = sorted({e.source_manager for e in db_evidence if e.source_manager})
        source_mgr = "+".join(distinct_managers) if distinct_managers else f"HumanOverride:{reviewer_id}"

        claim_id_str = self._generate_unique_claim_id()
        amt = Decimal(str(charge.amount)) if charge.amount is not None else None

        new_claim = Claim(
            claim_id=claim_id_str,
            charge_id=charge.id,
            assessment="CONTRADICTED",
            claim_amount=amt,
            confidence=Decimal("1.0000"),
            explanation=f"Human operator override ({reviewer_id}): {reason}",
            status="READY_FOR_REVIEW",
            source_manager=source_mgr,
            org_id=charge.org_id,
        )
        self.db.add(new_claim)
        self.db.flush()

        for ev in db_evidence:
            link = ClaimEvidence(
                claim_id=new_claim.id,
                evidence_id=ev.id,
                org_id=charge.org_id,
            )
            self.db.add(link)

        charge.status = "PROCESSED"
        self.db.add(charge)

        log_entry = AssessmentLog(
            charge_id=charge.id,
            assessment="CONTRADICTED",
            claim_supported=True,
            claim_amount=amt,
            confidence=None,
            reason=f"Human operator override ({reviewer_id}): {reason}",
            evidence_ids=[e.evidence_id for e in db_evidence if e.evidence_id],
            org_id=charge.org_id,
        )
        self.db.add(log_entry)

        return new_claim
