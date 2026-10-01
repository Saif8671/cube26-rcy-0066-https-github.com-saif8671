"""Phase 9 Synchronous Pipeline Orchestration Service.

Orchestrates the entire recovery evaluation lifecycle for a single marketplace charge:
  1. Evidence Retrieval (Phase 4 Deterministic Evidence Engine)
  2. AI Reasoning (Phase 5 AI Service)
  3. Rule Validation (Phase 6 Deterministic Rule Validator)
  4. Claim Engine (Phase 7 Claim Persistence & Audit Logger)

Guarantees:
  - Strictly SYNCHRONOUS: Blocks and returns real results without background queues or polling.
  - Fail-safe charge lookup: Returns NOT_FOUND result instead of raising unhandled exceptions.
  - Strict Idempotency: Checks assessment_log and claims tables before doing any work or calling AI.
  - Provenance integrity: Passes verified inputs/outputs between phases in memory untouched.
"""

from decimal import Decimal
from typing import List, Optional
from sqlalchemy import desc, select, func
from sqlalchemy.orm import Session

from app.ai.schemas import (
    AIAssessmentRequest,
    ChargeInputSchema,
    EvidenceInputSchema,
    ProcessingStateSchema,
)
from app.ai.service import AIService
from app.claims.service import ClaimEngine
from app.core.database import SessionLocal
from app.core.logging import logger
from app.models.assessment_log import AssessmentLog
from app.models.charge import Charge
from app.models.claim import Claim
from app.models.claim_evidence import ClaimEvidence
from app.models.evidence import Evidence
from app.models.reimbursement import Reimbursement
from app.models.pipeline_error import PipelineError
from app.rules.service import rule_validator
from app.schemas.pipeline import PipelineResult
from app.services.evidence_engine import evidence_engine


def _record_pipeline_error(
    db: Session,
    charge: Charge,
    stage: str,
    error_reason: str,
) -> None:
    """
    Engineering Rule 3 (Fail Open):
    A model error or timeout still saves the capture and still produces a record,
    marked pending. Nothing blocks the operator.
    Durable persistence of failed pipeline executions with status='pending'.
    """
    try:
        err_stmt = select(PipelineError).where(
            PipelineError.charge_id == charge.id,
            PipelineError.status == "pending",
        )
        existing_err = db.scalars(err_stmt).first()
        if existing_err:
            existing_err.stage = stage
            existing_err.error_reason = error_reason
            existing_err.updated_at = func.now()
        else:
            new_err = PipelineError(
                charge_id=charge.id,
                org_id=charge.org_id,
                stage=stage,
                error_reason=error_reason,
                status="pending",
            )
            db.add(new_err)
        db.commit()
    except Exception as db_exc:
        db.rollback()
        logger.error(f"Failed to persist durable pipeline error for charge '{charge.charge_id}': {db_exc}")


def _execute_pipeline(
    charge_id: str,
    db: Session,
    ai_service: Optional[AIService] = None,
) -> PipelineResult:
    """Internal synchronous execution of the 4-phase recovery pipeline within an active DB session."""
    clean_id = charge_id.strip() if charge_id else ""
    if not clean_id:
        return PipelineResult(
            outcome="NOT_FOUND",
            charge_id=clean_id,
            reason="Charge identifier is empty or invalid.",
        )

    # --------------------------------------------------------------------------
    # 1. Fetch Charge from Database
    # --------------------------------------------------------------------------
    charge = evidence_engine.find_charge(clean_id, db)
    if not charge:
        logger.info(f"Pipeline: Charge '{clean_id}' not found in database.")
        return PipelineResult(
            outcome="NOT_FOUND",
            charge_id=clean_id,
            reason=f"Charge with identifier '{clean_id}' does not exist in database.",
        )

    # --------------------------------------------------------------------------
    # 1b. Exclude non-fee records (e.g. inventory_adjustment)
    # inventory_adjustment rows are quantity-loss records, NOT disputable dollar
    # charges. They are stored for evidence context but excluded from claim assessment.
    # --------------------------------------------------------------------------
    if charge.report_type == "inventory_adjustment":
        logger.info(
            f"Pipeline Exclusion: Charge '{charge.charge_id}' has report_type='inventory_adjustment'. "
            f"Excluded from claim-eligible assessment pipeline."
        )
        return PipelineResult(
            outcome="INELIGIBLE_INVENTORY_ADJUSTMENT",
            charge_id=charge.charge_id,
            reason=f"Charge '{charge.charge_id}' is an inventory adjustment record (report_type='inventory_adjustment'), not a disputable fee.",
            evidence_count=0,
            evidence_ids=[],
        )

    if charge.amount <= Decimal("0.00"):
        logger.info(
            f"Pipeline Exclusion: Charge '{charge.charge_id}' has amount={charge.amount} <= 0. "
            f"Excluded from financial recovery pipeline."
        )
        _zero_reason = (
            f"Charge '{charge.charge_id}' has non-positive amount ({charge.amount}); "
            f"no financial recovery claim possible."
        )
        _zero_log = AssessmentLog(
            charge_id=charge.id,
            assessment="SILENT",
            claim_supported=False,
            claim_amount=None,
            confidence=None,
            reason=_zero_reason,
            evidence_ids=[],
            org_id=charge.org_id,
        )
        db.add(_zero_log)
        db.commit()
        return PipelineResult(
            outcome="NO_CLAIM",
            charge_id=charge.charge_id,
            reason=_zero_reason,
            evidence_count=0,
            evidence_ids=[],
        )

    # --------------------------------------------------------------------------
    # 2. IDEMPOTENCY CHECK (Before any AI call or mutating work)
    # Check assessment_log and claims for an existing record linked to this charge.
    # --------------------------------------------------------------------------
    log_stmt = (
        select(AssessmentLog)
        .where(AssessmentLog.charge_id == charge.id)
        .order_by(desc(AssessmentLog.created_at))
    )
    existing_log = db.scalars(log_stmt).first()

    claim_stmt = (
        select(Claim)
        .where(Claim.charge_id == charge.id)
        .order_by(desc(Claim.created_at))
    )
    existing_claim = db.scalars(claim_stmt).first()

    if existing_log is not None or existing_claim is not None:
        logger.info(
            f"Pipeline Idempotency Hit: Charge '{charge.charge_id}' has already been processed "
            f"(claim={existing_claim.claim_id if existing_claim else None}, "
            f"log_assessment={existing_log.assessment if existing_log else None}). "
            f"Skipping pipeline execution to prevent duplicate AI calls and logs."
        )

        ev_ids: List[str] = []
        if existing_claim:
            ev_stmt = (
                select(Evidence.evidence_id)
                .join(ClaimEvidence, ClaimEvidence.evidence_id == Evidence.id)
                .where(ClaimEvidence.claim_id == existing_claim.id)
            )
            ev_ids = list(db.scalars(ev_stmt).all())
        elif existing_log and existing_log.evidence_ids:
            ev_ids = list(existing_log.evidence_ids)

        claim_id_val = existing_claim.claim_id if existing_claim else None
        status_val = existing_claim.status if existing_claim else charge.status
        assessment_val = (
            existing_claim.assessment
            if existing_claim
            else (existing_log.assessment if existing_log else None)
        )
        amt_val = (
            existing_claim.claim_amount
            if existing_claim
            else (existing_log.claim_amount if existing_log else None)
        )
        conf_val = (
            float(existing_claim.confidence)
            if existing_claim and existing_claim.confidence is not None
            else (float(existing_log.confidence) if existing_log and existing_log.confidence is not None else None)
        )
        reason_val = (
            existing_claim.explanation
            if (existing_claim and existing_claim.explanation)
            else (existing_log.reason if (existing_log and existing_log.reason) else "Charge has already been evaluated.")
        )

        return PipelineResult(
            outcome="ALREADY_PROCESSED",
            charge_id=charge.charge_id,
            claim_id=claim_id_val,
            status=status_val,
            assessment=assessment_val,
            claim_amount=amt_val,
            confidence=conf_val,
            reason=(
                f"Idempotency hit: Charge '{charge.charge_id}' was already processed. "
                f"Outcome: {assessment_val or 'EVALUATED'} ({status_val or 'NO_CLAIM'}). {reason_val}"
            ).strip(),
            evidence_count=len(ev_ids),
            evidence_ids=ev_ids,
        )

    # --------------------------------------------------------------------------
    # 3. Determine processing_state (duplicate, already_reimbursed)
    # --------------------------------------------------------------------------
    # duplicate is False because step 2 verified neither assessment_log nor claim exists
    is_duplicate = False

    # already_reimbursed is True if a reimbursements row exists referencing this charge
    reimb_stmt = select(Reimbursement.id).where(Reimbursement.charge_id == charge.id)
    is_already_reimbursed = db.scalars(reimb_stmt).first() is not None

    processing_state = ProcessingStateSchema(
        duplicate=is_duplicate,
        already_reimbursed=is_already_reimbursed,
    )

    # --------------------------------------------------------------------------
    # 3b. SHORT-CIRCUIT: ALREADY_REIMBURSED (or DUPLICATE)
    # If the charge is already reimbursed, skip Evidence Engine & AI Reasoning
    # entirely to save paid API costs. Atomically persist the BLOCKED claim row
    # and assessment_log entry directly.
    # --------------------------------------------------------------------------
    if is_already_reimbursed:
        logger.info(
            f"Pipeline Short-Circuit: Charge '{charge.charge_id}' has already been reimbursed. "
            f"Skipping Evidence Retrieval and AI Reasoning entirely to save API costs."
        )
        claim_engine = ClaimEngine(db=db)
        claim_id_str = claim_engine._generate_unique_claim_id()
        block_reason = "Charge has already been reimbursed; blocked from automatic recovery."

        claim_row = Claim(
            claim_id=claim_id_str,
            charge_id=charge.id,
            assessment="CONTRADICTED",  # Valid assessment value satisfying DB CHECK constraint
            claim_amount=None,  # Explicitly NULL for non-financial blocked claim
            confidence=None,  # AI was not invoked
            explanation=block_reason,
            status="ALREADY_REIMBURSED",
            source_manager=None,
            org_id=charge.org_id,
        )
        db.add(claim_row)

        log_entry = AssessmentLog(
            charge_id=charge.id,
            assessment="CONTRADICTED",  # Valid assessment value satisfying DB CHECK constraint
            claim_supported=False,
            claim_amount=None,
            confidence=None,  # AI was not invoked
            reason=block_reason,
            evidence_ids=[],
            org_id=charge.org_id,
        )
        db.add(log_entry)
        db.commit()

        return PipelineResult(
            outcome="BLOCKED",
            charge_id=charge.charge_id,
            claim_id=claim_id_str,
            status="ALREADY_REIMBURSED",
            assessment="CONTRADICTED",
            claim_amount=None,
            confidence=None,
            reason=block_reason,
            rule_code="RULE_ALREADY_REIMBURSED",
            decision="BLOCKED",
            evidence_count=0,
            evidence_ids=[],
        )

    # --------------------------------------------------------------------------
    # 4. Phase 4: Deterministic Evidence Retrieval
    # --------------------------------------------------------------------------
    evidence_retrieval = evidence_engine.get_evidence_for_charge_model(charge, db)
    evidence_inputs: List[EvidenceInputSchema] = [
        EvidenceInputSchema(
            evidence_id=em.evidence_id,
            source_manager=em.source_manager,
            evidence_type=em.evidence_type,
            evidence_timestamp=em.evidence_timestamp,
            evidence_content=em.evidence_content,
            matched_by=em.matched_by,
            match_value=em.match_value,
            matched_keys=em.matched_keys,
        )
        for em in evidence_retrieval.evidence
    ]

    # --------------------------------------------------------------------------
    # 5. Phase 5: AI Reasoning / Recovery Assessment
    # --------------------------------------------------------------------------
    shipment_ext = (
        charge.shipment.shipment_id
        if charge.shipment
        else (str(charge.shipment_id) if charge.shipment_id else None)
    )
    order_ext = (
        charge.order.order_id
        if charge.order
        else (str(charge.order_id) if charge.order_id else None)
    )

    charge_input = ChargeInputSchema(
        charge_id=charge.charge_id,
        charge_type=charge.charge_type,
        amount=charge.amount,
        shipment_id=shipment_ext,
        order_id=order_ext,
        sku=charge.sku.strip() if charge.sku else None,
        asin=charge.asin.strip() if charge.asin else None,
        unit_id=charge.unit_id.strip() if charge.unit_id else None,
        fnsku=charge.fnsku.strip() if charge.fnsku else None,
        charge_date=charge.charge_date,
    )

    ai_request = AIAssessmentRequest(
        charge=charge_input,
        evidence=evidence_inputs,
        processing_state=processing_state,
    )

    if ai_service is None:
        from app.ai.service import ai_service as default_ai_service
        active_ai_service = default_ai_service
    else:
        active_ai_service = ai_service

    try:
        ai_response = active_ai_service.assess_recovery(ai_request)
    except Exception as exc:
        logger.error(f"Pipeline: AI reasoning failed for charge '{charge.charge_id}': {exc}")
        _record_pipeline_error(
            db=db,
            charge=charge,
            stage="ai_reasoning",
            error_reason=f"Pipeline execution failed: {type(exc).__name__}: {str(exc)}",
        )
        return PipelineResult(
            outcome="ERROR",
            charge_id=charge.charge_id,
            reason=f"Pipeline execution failed: {type(exc).__name__}: {str(exc)}",
            evidence_count=len(evidence_inputs),
            evidence_ids=[e.evidence_id for e in evidence_inputs],
        )

    # --------------------------------------------------------------------------
    # 6. Phase 6: Deterministic Rule Validation
    # --------------------------------------------------------------------------
    rule_result = rule_validator.validate_assessment(ai_request, ai_response)

    # --------------------------------------------------------------------------
    # 7. Phase 7: Claim Engine Persistence & Audit Trail
    # --------------------------------------------------------------------------
    claim_engine = ClaimEngine(db=db)
    try:
        claim_result = claim_engine.process_claim(
            charge_id=charge.charge_id,
            validation_result=rule_result,
            assessment_response=ai_response,
            evidence=evidence_inputs,
            processing_state=processing_state,
        )
    except Exception as exc:
        db.rollback()
        logger.error(f"Pipeline: Claim persistence failed for charge '{charge.charge_id}': {exc}")
        _record_pipeline_error(
            db=db,
            charge=charge,
            stage="claim_engine",
            error_reason=f"Pipeline persistence error: {type(exc).__name__}: {str(exc)}",
        )
        return PipelineResult(
            outcome="ERROR",
            charge_id=charge.charge_id,
            reason=f"Pipeline persistence error: {type(exc).__name__}: {str(exc)}",
            evidence_count=len(evidence_inputs),
            evidence_ids=[e.evidence_id for e in evidence_inputs],
        )

    # --------------------------------------------------------------------------
    # 8. Assemble and Return PipelineResult
    # --------------------------------------------------------------------------
    # Engineering Rule 3: On successful completion, mark any previous pending pipeline errors as resolved
    try:
        pending_errs = list(
            db.scalars(
                select(PipelineError).where(
                    PipelineError.charge_id == charge.id,
                    PipelineError.status == "pending",
                )
            ).all()
        )
        for pe in pending_errs:
            pe.status = "resolved"
            pe.updated_at = func.now()
        if pending_errs:
            db.commit()
    except Exception:
        db.rollback()

    linked_evidence_ids = claim_result.evidence_ids or rule_result.evidence_ids or []
    conf = (
        float(ai_response.confidence)
        if ai_response.confidence is not None
        else None
    )

    return PipelineResult(
        outcome=claim_result.outcome,
        charge_id=charge.charge_id,
        claim_id=claim_result.claim_id,
        status=claim_result.status,
        assessment=rule_result.assessment.value,
        claim_amount=claim_result.claim_amount,
        confidence=conf,
        reason=claim_result.reason,
        rule_code=rule_result.rule_code,
        decision=rule_result.decision.value,
        evidence_count=len(evidence_inputs),
        evidence_ids=linked_evidence_ids,
    )


def process_charge_pipeline(
    charge_id: str,
    db: Optional[Session] = None,
    ai_service: Optional[AIService] = None,
) -> PipelineResult:
    """
    Public entry point for the synchronous Phase 9 recovery pipeline.

    Args:
        charge_id: External marketplace charge identifier.
        db: Optional SQLAlchemy Session. If not provided, a managed session is created.
        ai_service: Optional AIService instance (useful for dependency injection / mocking in tests).

    Returns:
        PipelineResult with the full orchestration outcome.
    """
    if db is not None:
        return _execute_pipeline(charge_id=charge_id, db=db, ai_service=ai_service)

    with SessionLocal() as session:
        return _execute_pipeline(charge_id=charge_id, db=session, ai_service=ai_service)


def process_batch_pipeline(
    charge_ids: Optional[List[str]] = None,
    db: Optional[Session] = None,
    ai_service: Optional[AIService] = None,
) -> "BatchProcessResponse":
    """
    Process multiple charges sequentially through the recovery pipeline.

    Error isolation: if one charge fails (AI error, DB error, etc.), the failure
    is captured as an ERROR PipelineResult for that charge and processing continues
    for the remaining charges.

    Args:
        charge_ids: Explicit list of charge identifiers to process. If None or empty,
                    defaults to all charges with no assessment_log row.
        db: Optional SQLAlchemy Session. If not provided, a managed session is created.
        ai_service: Optional AIService instance for dependency injection.

    Returns:
        BatchProcessResponse with per-charge results and summary counts.
    """
    from app.schemas.pipeline import BatchProcessResponse

    def _run_batch(session: Session) -> BatchProcessResponse:
        # Resolve charge_ids if not provided
        resolved_ids = charge_ids
        if not resolved_ids:
            # Find all charges with NO assessment_log row, excluding inventory_adjustment records
            stmt = (
                select(Charge.charge_id)
                .outerjoin(AssessmentLog, AssessmentLog.charge_id == Charge.id)
                .where(
                    AssessmentLog.id.is_(None),
                    (Charge.report_type != "inventory_adjustment") | (Charge.report_type.is_(None)),
                )
            )
            resolved_ids = list(session.scalars(stmt).all())
            logger.info(f"Batch pipeline: No explicit charge_ids provided. Found {len(resolved_ids)} unassessed fee charges.")

        results: List[PipelineResult] = []
        succeeded = 0
        failed = 0
        already_processed = 0

        for cid in resolved_ids:
            try:
                result = _execute_pipeline(charge_id=cid, db=session, ai_service=ai_service)
                results.append(result)

                if result.outcome == "ALREADY_PROCESSED":
                    already_processed += 1
                elif result.outcome in ("ERROR", "NOT_FOUND"):
                    failed += 1
                elif result.outcome == "INELIGIBLE_INVENTORY_ADJUSTMENT":
                    # Recorded as handled/succeeded without claim
                    already_processed += 1
                else:
                    succeeded += 1

            except Exception as exc:
                session.rollback()
                logger.error(f"Batch pipeline: Charge '{cid}' failed with exception: {exc}")
                try:
                    target_chg = evidence_engine.find_charge(str(cid), session)
                    if target_chg:
                        _record_pipeline_error(
                            db=session,
                            charge=target_chg,
                            stage="orchestration",
                            error_reason=f"Pipeline execution failed: {type(exc).__name__}: {str(exc)}",
                        )
                except Exception:
                    pass
                error_result = PipelineResult(
                    outcome="ERROR",
                    charge_id=cid,
                    reason=f"Pipeline execution failed: {type(exc).__name__}: {str(exc)}",
                )
                results.append(error_result)
                failed += 1
                # Continue processing remaining charges — do NOT abort the batch

        return BatchProcessResponse(
            results=results,
            succeeded=succeeded,
            failed=failed,
            already_processed=already_processed,
            total=len(resolved_ids),
        )

    if db is not None:
        return _run_batch(db)

    with SessionLocal() as session:
        return _run_batch(session)

