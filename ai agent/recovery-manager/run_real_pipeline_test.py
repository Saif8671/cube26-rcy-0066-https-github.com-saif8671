"""
Execute the synchronous recovery pipeline against real units from the ingested sample data.
Captures real PipelineResults and database rows (claims, claim_evidence, assessment_log).
"""
import sys
import os
import json

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.core.database import SessionLocal, set_org_context, reset_org_context
from app.services.pipeline import process_charge_pipeline
from app.models.claim import Claim
from app.models.claim_evidence import ClaimEvidence
from app.models.assessment_log import AssessmentLog
from app.models.charge import Charge
from sqlalchemy import select

def run_real_pipeline():
    print("=" * 80)
    print("RUNNING PIPELINE AGAINST REAL INGESTED DATA (3-5 UNITS)")
    print("=" * 80)

    # Selected real units covering multiple scenarios
    test_charges = [
        ("FEE-0026-1", "org_demo_alpha", "UNIT-0026: Contradicted inbound defect fee (Receiving & Prep show no damage/defect)"),
        ("FEE-0018-1", "org_demo_bravo", "UNIT-0018: Supported inbound defect fee (Receiving flagged obvious_defect)"),
        ("FEE-0003-1", "org_demo_bravo", "UNIT-0003: Inventory adjustment exclusion (report_type=inventory_adjustment, amount=0.00)"),
        ("FEE-0014-4", "org_demo_alpha", "UNIT-0014: Zero-dollar refund notification (amount=0.00)"),
        ("FEE-0002-1", "org_demo_alpha", "UNIT-0002: Weight tier fulfillment fee ($4.25)"),
    ]

    results = []

    for cid, org, desc in test_charges:
        print("\n" + "-" * 80)
        print(f"PROCESSING CHARGE: {cid} ({desc})")
        print(f"TENANT CONTEXT: {org}")
        print("-" * 80)

        db = SessionLocal()
        try:
            # Set tenant org context
            set_org_context(db, org)

            # Run pipeline
            res = process_charge_pipeline(charge_id=cid, db=db)
            print(f"\n  PipelineResult:")
            print(f"    Outcome:       {res.outcome}")
            print(f"    Charge ID:     {res.charge_id}")
            print(f"    Claim ID:      {res.claim_id}")
            print(f"    Status:        {res.status}")
            print(f"    Assessment:    {res.assessment}")
            print(f"    Claim Amount:  {res.claim_amount}")
            print(f"    Confidence:    {res.confidence}")
            print(f"    Rule Code:     {res.rule_code}")
            print(f"    Decision:      {res.decision}")
            print(f"    Evidence Count:{res.evidence_count}")
            print(f"    Evidence IDs:  {res.evidence_ids}")
            print(f"    Reason:        {res.reason}")

            # Check DB rows directly
            charge_obj = db.scalars(select(Charge).where(Charge.charge_id == cid)).first()
            if charge_obj:
                claims_rows = db.scalars(select(Claim).where(Claim.charge_id == charge_obj.id)).all()
                logs_rows = db.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == charge_obj.id)).all()
                print(f"\n  Database Persistence Check:")
                print(f"    Charge DB Status: {charge_obj.status}")
                print(f"    Claims persisted: {len(claims_rows)}")
                for cl in claims_rows:
                    print(f"      -> Claim {cl.claim_id}: status={cl.status}, amt={cl.claim_amount}, org={cl.org_id}")
                print(f"    AssessmentLog persisted: {len(logs_rows)}")
                for lg in logs_rows:
                    print(f"      -> AssessmentLog {lg.id}: assessment={lg.assessment}, supported={lg.claim_supported}, org={lg.org_id}")

            results.append({
                "charge_id": cid,
                "org_id": org,
                "description": desc,
                "outcome": res.outcome,
                "assessment": res.assessment,
                "claim_id": res.claim_id,
                "status": res.status,
                "claim_amount": str(res.claim_amount) if res.claim_amount is not None else None,
                "confidence": res.confidence,
                "rule_code": res.rule_code,
                "reason": res.reason,
            })

            reset_org_context(db)
        finally:
            db.close()

    print("\n" + "=" * 80)
    print("ALL REAL PIPELINE RUNS COMPLETED")
    print("=" * 80)
    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    run_real_pipeline()
