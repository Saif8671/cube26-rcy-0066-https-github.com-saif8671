import sys
from pathlib import Path
from decimal import Decimal
from datetime import datetime, timezone
from sqlalchemy import text, select
from unittest.mock import patch

# Ensure backend directory is in sys.path
backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.database import SessionLocal
from app.models.shipment import Shipment
from app.models.order import Order
from app.models.charge import Charge
from app.models.evidence import Evidence
from app.models.claim import Claim
from app.models.claim_evidence import ClaimEvidence
from app.rules.schemas import RuleValidationResult, ValidationDecision
from app.ai.schemas import AIAssessmentResponse, AssessmentType
from app.claims.service import ClaimEngine
from app.claims.exceptions import ClaimTransactionError

def run_verifications():
    db = SessionLocal()
    db_separate = SessionLocal()
    try:
        print("=== CASE A: FORCED MID-TRANSACTION ROLLBACK ===")
        # Count before
        claims_before = db_separate.scalar(text("SELECT count(*) FROM claims"))
        ce_before = db_separate.scalar(text("SELECT count(*) FROM claim_evidence"))
        print(f"RAW QUERY: SELECT count(*) FROM claims -> {claims_before}")
        print(f"RAW QUERY: SELECT count(*) FROM claim_evidence -> {ce_before}")

        # Setup charge and evidence
        shp = Shipment(shipment_id="SHP-VERIF-A")
        db.add(shp); db.flush()
        chg = Charge(charge_id="CHG-VERIF-A", shipment_id=shp.id, amount=Decimal("100.00"), charge_type="Defect", charge_date=datetime(2026, 3, 1, tzinfo=timezone.utc), status="PENDING")
        db.add(chg); db.flush()
        ev = Evidence(evidence_id="EVD-VERIF-A", source_manager="Prep", shipment_id=shp.id, evidence_type="scan", evidence_content={}, evidence_timestamp=datetime(2026, 3, 1, tzinfo=timezone.utc))
        db.add(ev); db.commit()

        engine = ClaimEngine(db)
        ai_resp = AIAssessmentResponse(assessment=AssessmentType.CONTRADICTED, claim_supported=True, claim_amount=Decimal("100.00"), confidence=0.95, reason="Contradicted", evidence_ids=["EVD-VERIF-A"])
        val_res = RuleValidationResult(charge_id="CHG-VERIF-A", assessment=AssessmentType.CONTRADICTED, eligible_for_recovery=True, human_review_required=False, claim_amount=Decimal("100.00"), evidence_ids=["EVD-VERIF-A"], decision=ValidationDecision.ELIGIBLE, status=ValidationDecision.ELIGIBLE, reason="Eligible", rule_code="RULE_RECOVERY_ELIGIBLE")

        # Force failure
        with patch.object(ClaimEvidence, "__init__", side_effect=RuntimeError("Simulated failure")):
            try:
                engine.process_claim("CHG-VERIF-A", val_res, ai_resp)
            except ClaimTransactionError:
                pass

        # Check counts on separate connection
        claims_after = db_separate.scalar(text("SELECT count(*) FROM claims"))
        ce_after = db_separate.scalar(text("SELECT count(*) FROM claim_evidence"))
        print(f"POST-ROLLBACK SEPARATE CONNECTION: SELECT count(*) FROM claims -> {claims_after}")
        print(f"POST-ROLLBACK SEPARATE CONNECTION: SELECT count(*) FROM claim_evidence -> {ce_after}")
        assert claims_before == claims_after
        assert ce_before == ce_after

        # Clean case A charge/evidence
        db.execute(text("DELETE FROM evidence WHERE evidence_id='EVD-VERIF-A'"))
        db.execute(text("DELETE FROM charges WHERE charge_id='CHG-VERIF-A'"))
        db.execute(text("DELETE FROM shipments WHERE shipment_id='SHP-VERIF-A'"))
        db.commit()

        print("\n=== CASE B: TAMPERED EVIDENCE_ID REJECTION ===")
        shp_b = Shipment(shipment_id="SHP-VERIF-B")
        db.add(shp_b); db.flush()
        chg_b = Charge(charge_id="CHG-VERIF-B", shipment_id=shp_b.id, amount=Decimal("75.00"), charge_type="Defect", charge_date=datetime(2026, 3, 1, tzinfo=timezone.utc), status="PENDING")
        db.add(chg_b); db.commit()

        ai_resp_b = AIAssessmentResponse(assessment=AssessmentType.CONTRADICTED, claim_supported=True, claim_amount=Decimal("75.00"), confidence=0.90, reason="Tampered ghost evidence", evidence_ids=["EVD-GHOST-999"])
        val_res_b = RuleValidationResult(charge_id="CHG-VERIF-B", assessment=AssessmentType.CONTRADICTED, eligible_for_recovery=True, human_review_required=False, claim_amount=Decimal("75.00"), evidence_ids=["EVD-GHOST-999"], decision=ValidationDecision.ELIGIBLE, status=ValidationDecision.ELIGIBLE, reason="Fraudulently marked eligible", rule_code="RULE_RECOVERY_ELIGIBLE")

        res_b = engine.process_claim("CHG-VERIF-B", val_res_b, ai_resp_b)
        print("RAW RETURNED ClaimEngineResult:", res_b.model_dump())

        # Raw query for claims row
        claim_b_row = db_separate.execute(text("SELECT claim_id, status, claim_amount, assessment, explanation FROM claims WHERE charge_id = (SELECT id FROM charges WHERE charge_id = 'CHG-VERIF-B')")).mappings().first()
        print("RAW QUERY CLAIMS ROW:", dict(claim_b_row) if claim_b_row else None)

        # Raw query for claim_evidence count
        ce_b_count = db_separate.scalar(text("SELECT count(*) FROM claim_evidence WHERE claim_id = (SELECT id FROM claims WHERE charge_id = (SELECT id FROM charges WHERE charge_id = 'CHG-VERIF-B'))"))
        print(f"RAW QUERY CLAIM_EVIDENCE COUNT: {ce_b_count}")

        # Clean case B
        db.execute(text("DELETE FROM claims WHERE charge_id = (SELECT id FROM charges WHERE charge_id = 'CHG-VERIF-B')"))
        db.execute(text("DELETE FROM charges WHERE charge_id = 'CHG-VERIF-B'"))
        db.execute(text("DELETE FROM shipments WHERE shipment_id='SHP-VERIF-B'"))
        db.commit()

        print("\n=== CASE C: IDEMPOTENCY ACROSS NON-ELIGIBLE OUTCOMES (DUPLICATE) ===")
        shp_c = Shipment(shipment_id="SHP-VERIF-C")
        db.add(shp_c); db.flush()
        chg_c = Charge(charge_id="CHG-VERIF-C", shipment_id=shp_c.id, amount=Decimal("50.00"), charge_type="Duplicate check", charge_date=datetime(2026, 3, 1, tzinfo=timezone.utc), status="PENDING")
        db.add(chg_c); db.commit()

        ai_resp_c = AIAssessmentResponse(assessment=AssessmentType.CONTRADICTED, claim_supported=True, claim_amount=Decimal("50.00"), confidence=0.85, reason="Duplicate charge", evidence_ids=[])
        val_res_c = RuleValidationResult(charge_id="CHG-VERIF-C", assessment=AssessmentType.CONTRADICTED, eligible_for_recovery=False, human_review_required=False, claim_amount=None, evidence_ids=[], decision=ValidationDecision.BLOCKED, status=ValidationDecision.BLOCKED, reason="Blocked duplicate", rule_code="RULE_DUPLICATE")

        res_c1 = engine.process_claim("CHG-VERIF-C", val_res_c, ai_resp_c)
        print("FIRST CALL RESULT:", res_c1.model_dump())

        # Second call
        res_c2 = engine.process_claim("CHG-VERIF-C", val_res_c, ai_resp_c)
        print("SECOND CALL RESULT (IDEMPOTENCY):", res_c2.model_dump())

        # Direct query count
        c_claims_count = db_separate.scalar(text("SELECT count(*) FROM claims WHERE charge_id = (SELECT id FROM charges WHERE charge_id = 'CHG-VERIF-C')"))
        print(f"RAW QUERY CLAIMS ROW COUNT FOR CHG-VERIF-C: {c_claims_count}")

        # Clean case C
        db.execute(text("DELETE FROM claims WHERE charge_id = (SELECT id FROM charges WHERE charge_id = 'CHG-VERIF-C')"))
        db.execute(text("DELETE FROM charges WHERE charge_id = 'CHG-VERIF-C'"))
        db.execute(text("DELETE FROM shipments WHERE shipment_id='SHP-VERIF-C'"))
        db.commit()

        print("\n=== STEP 3: LIVE TRACEABILITY QUERY ON SEED DATA ===")
        trace_query = """
        SELECT
            c.claim_id,
            ch.charge_id,
            s.shipment_id,
            o.order_id,
            ch.sku,
            e.evidence_id,
            e.source_manager,
            e.evidence_timestamp
        FROM claims c
        JOIN charges ch ON c.charge_id = ch.id
        LEFT JOIN shipments s ON ch.shipment_id = s.id
        LEFT JOIN orders o ON ch.order_id = o.id
        JOIN claim_evidence ce ON ce.claim_id = c.id
        JOIN evidence e ON ce.evidence_id = e.id
        WHERE c.claim_id = 'CLM-10092';
        """
        row = db_separate.execute(text(trace_query)).mappings().first()
        print("LIVE TRACEABILITY QUERY RESULT:")
        print(dict(row) if row else "NOT FOUND")

        print("\n=== STEP 4: CHARGES.STATUS DIRECT QUERY ===")
        # Check seed charge CHG-FBA-8901 and CHG-FBA-8903 status
        chg_status_rows = db_separate.execute(text("SELECT charge_id, status FROM charges ORDER BY charge_id")).mappings().all()
        print("CHARGES STATUSES IN DB:")
        for r in chg_status_rows:
            print(dict(r))

        print("\n=== STEP 6: FINAL TABLE COUNTS ===")
        tables = ['shipments', 'orders', 'charges', 'evidence', 'reimbursements', 'claims', 'claim_evidence', 'assessment_log']
        for t in tables:
            cnt = db_separate.scalar(text(f"SELECT count(*) FROM {t}"))
            print(f"TABLE {t}: {cnt}")

    finally:
        db.close()
        db_separate.close()

if __name__ == "__main__":
    run_verifications()
