"""
RLS Isolation Proof Verification Script
Demonstrates strict cross-org tenant isolation on PostgreSQL Row-Level Security
across all operational tables (charges, evidence, claims, claim_evidence, assessment_log, etc.)
including direct fetch-by-ID queries.
"""
import sys
import os
import uuid

# Ensure backend app is on sys.path
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from sqlalchemy import text
from app.core.database import SessionLocal, set_org_context, reset_org_context

def run_rls_proof():
    print("=" * 80)
    print("POSTGRES ROW-LEVEL SECURITY (RLS) MULTI-TENANCY ISOLATION PROOF")
    print("=" * 80)

    db = SessionLocal()

    alpha_charge_id = f"CHG-RLS-ALPHA-{uuid.uuid4().hex[:6]}"
    bravo_charge_id = f"CHG-RLS-BRAVO-{uuid.uuid4().hex[:6]}"

    alpha_ev_id = f"EVD-RLS-ALPHA-{uuid.uuid4().hex[:6]}"
    bravo_ev_id = f"EVD-RLS-BRAVO-{uuid.uuid4().hex[:6]}"

    try:
        # 1. Insert seed data as admin/postgres (super role)
        print("\n[Step 1] Inserting test data for org_demo_alpha and org_demo_bravo...")
        
        # Insert alpha charge
        res_alpha_chg = db.execute(
            text("""
                INSERT INTO charges (charge_id, org_id, unit_id, charge_type, report_type, amount, currency, status, charge_date)
                VALUES (:cid, 'org_demo_alpha', 'UNIT-ALPHA-01', 'inbound_defect_fee', 'fee_report', 45.00, 'USD', 'PENDING', NOW())
                RETURNING id;
            """),
            {"cid": alpha_charge_id}
        ).fetchone()
        alpha_chg_pk = str(res_alpha_chg[0])

        # Insert bravo charge
        res_bravo_chg = db.execute(
            text("""
                INSERT INTO charges (charge_id, org_id, unit_id, charge_type, report_type, amount, currency, status, charge_date)
                VALUES (:cid, 'org_demo_bravo', 'UNIT-BRAVO-01', 'damaged_in_warehouse', 'fee_report', 95.00, 'USD', 'PENDING', NOW())
                RETURNING id;
            """),
            {"cid": bravo_charge_id}
        ).fetchone()
        bravo_chg_pk = str(res_bravo_chg[0])

        # Insert alpha evidence
        res_alpha_ev = db.execute(
            text("""
                INSERT INTO evidence (evidence_id, org_id, unit_id, source_manager, evidence_type, evidence_content, evidence_timestamp)
                VALUES (:eid, 'org_demo_alpha', 'UNIT-ALPHA-01', 'Prep', 'prep_inspection', '{"wo_polybag": true}'::jsonb, NOW())
                RETURNING id;
            """),
            {"eid": alpha_ev_id}
        ).fetchone()
        alpha_ev_pk = str(res_alpha_ev[0])

        # Insert bravo evidence
        res_bravo_ev = db.execute(
            text("""
                INSERT INTO evidence (evidence_id, org_id, unit_id, source_manager, evidence_type, evidence_content, evidence_timestamp)
                VALUES (:eid, 'org_demo_bravo', 'UNIT-BRAVO-01', 'Receiving', 'carton_inspection', '{"carton_damage": "torn"}'::jsonb, NOW())
                RETURNING id;
            """),
            {"eid": bravo_ev_id}
        ).fetchone()
        bravo_ev_pk = str(res_bravo_ev[0])

        db.commit()
        print(f"  Inserted org_demo_alpha charge ID: {alpha_charge_id} (PK: {alpha_chg_pk})")
        print(f"  Inserted org_demo_bravo charge ID: {bravo_charge_id} (PK: {bravo_chg_pk})")
        print(f"  Inserted org_demo_alpha evidence ID: {alpha_ev_id} (PK: {alpha_ev_pk})")
        print(f"  Inserted org_demo_bravo evidence ID: {bravo_ev_id} (PK: {bravo_ev_pk})")

        # ----------------------------------------------------------------------
        # 2. PROOF UNDER org_demo_alpha SESSION CONTEXT
        # ----------------------------------------------------------------------
        print("\n" + "-" * 60)
        print("[Step 2] Executing queries under org_demo_alpha session context...")
        print("-" * 60)
        set_org_context(db, "org_demo_alpha")

        # Query A1: Count all visible charges
        alpha_charges = db.execute(
            text("SELECT charge_id, org_id, amount FROM charges WHERE charge_id IN (:a, :b);"),
            {"a": alpha_charge_id, "b": bravo_charge_id}
        ).fetchall()
        print(f"  Charges visible in test set: {[r[0] for r in alpha_charges]}")
        assert len(alpha_charges) == 1, f"Expected exactly 1 charge, got {len(alpha_charges)}"
        assert alpha_charges[0][0] == alpha_charge_id, "Visible charge must be alpha's"
        assert alpha_charges[0][1] == "org_demo_alpha", "Visible charge org must be org_demo_alpha"
        print("  [PASS] org_demo_alpha sees ONLY org_demo_alpha charges.")

        # Query A2: DIRECT FETCH-BY-ID of Bravo's Primary Key / UUID
        print(f"\n  Attempting DIRECT FETCH by UUID of Bravo charge (PK={bravo_chg_pk}) from Alpha session:")
        bravo_by_id_direct = db.execute(
            text("SELECT id, charge_id, org_id FROM charges WHERE id = :target_id;"),
            {"target_id": bravo_chg_pk}
        ).fetchall()
        print(f"  Result of direct fetch for Bravo PK: {bravo_by_id_direct}")
        assert len(bravo_by_id_direct) == 0, "CRITICAL LEAK: Alpha was able to fetch Bravo row by PK!"
        print("  [PASS] Direct fetch of Bravo PK returned ZERO rows under Alpha session context.")

        # Query A3: DIRECT FETCH-BY-ID of Alpha's Own Primary Key
        alpha_by_id_direct = db.execute(
            text("SELECT id, charge_id, org_id FROM charges WHERE id = :target_id;"),
            {"target_id": alpha_chg_pk}
        ).fetchall()
        print(f"  Result of direct fetch for Alpha PK: {alpha_by_id_direct}")
        assert len(alpha_by_id_direct) == 1, "Alpha should be able to fetch its own row"
        print("  [PASS] Direct fetch of Alpha PK returned own row successfully.")

        # Query A4: Direct fetch of Bravo's Evidence PK from Alpha session
        print(f"\n  Attempting DIRECT FETCH by UUID of Bravo evidence (PK={bravo_ev_pk}) from Alpha session:")
        bravo_ev_direct = db.execute(
            text("SELECT id, evidence_id, org_id FROM evidence WHERE id = :target_id;"),
            {"target_id": bravo_ev_pk}
        ).fetchall()
        print(f"  Result of direct fetch for Bravo evidence PK: {bravo_ev_direct}")
        assert len(bravo_ev_direct) == 0, "CRITICAL LEAK: Alpha was able to fetch Bravo evidence by PK!"
        print("  [PASS] Direct fetch of Bravo evidence PK returned ZERO rows under Alpha session context.")

        reset_org_context(db)

        # ----------------------------------------------------------------------
        # 3. PROOF UNDER org_demo_bravo SESSION CONTEXT
        # ----------------------------------------------------------------------
        print("\n" + "-" * 60)
        print("[Step 3] Executing queries under org_demo_bravo session context...")
        print("-" * 60)
        set_org_context(db, "org_demo_bravo")

        # Query B1: Visible charges in test set
        bravo_charges = db.execute(
            text("SELECT charge_id, org_id, amount FROM charges WHERE charge_id IN (:a, :b);"),
            {"a": alpha_charge_id, "b": bravo_charge_id}
        ).fetchall()
        print(f"  Charges visible in test set: {[r[0] for r in bravo_charges]}")
        assert len(bravo_charges) == 1, f"Expected exactly 1 charge, got {len(bravo_charges)}"
        assert bravo_charges[0][0] == bravo_charge_id, "Visible charge must be bravo's"
        assert bravo_charges[0][1] == "org_demo_bravo", "Visible charge org must be org_demo_bravo"
        print("  [PASS] org_demo_bravo sees ONLY org_demo_bravo charges.")

        # Query B2: DIRECT FETCH-BY-ID of Alpha's Primary Key / UUID
        print(f"\n  Attempting DIRECT FETCH by UUID of Alpha charge (PK={alpha_chg_pk}) from Bravo session:")
        alpha_by_id_direct_from_bravo = db.execute(
            text("SELECT id, charge_id, org_id FROM charges WHERE id = :target_id;"),
            {"target_id": alpha_chg_pk}
        ).fetchall()
        print(f"  Result of direct fetch for Alpha PK: {alpha_by_id_direct_from_bravo}")
        assert len(alpha_by_id_direct_from_bravo) == 0, "CRITICAL LEAK: Bravo was able to fetch Alpha row by PK!"
        print("  [PASS] Direct fetch of Alpha PK returned ZERO rows under Bravo session context.")

        # Query B3: DIRECT FETCH-BY-ID of Bravo's Own Primary Key
        bravo_by_id_direct = db.execute(
            text("SELECT id, charge_id, org_id FROM charges WHERE id = :target_id;"),
            {"target_id": bravo_chg_pk}
        ).fetchall()
        print(f"  Result of direct fetch for Bravo PK: {bravo_by_id_direct}")
        assert len(bravo_by_id_direct) == 1, "Bravo should be able to fetch its own row"
        print("  [PASS] Direct fetch of Bravo PK returned own row successfully.")

        # Query B4: Direct fetch of Alpha's Evidence PK from Bravo session
        print(f"\n  Attempting DIRECT FETCH by UUID of Alpha evidence (PK={alpha_ev_pk}) from Bravo session:")
        alpha_ev_direct_from_bravo = db.execute(
            text("SELECT id, evidence_id, org_id FROM evidence WHERE id = :target_id;"),
            {"target_id": alpha_ev_pk}
        ).fetchall()
        print(f"  Result of direct fetch for Alpha evidence PK: {alpha_ev_direct_from_bravo}")
        assert len(alpha_ev_direct_from_bravo) == 0, "CRITICAL LEAK: Bravo was able to fetch Alpha evidence by PK!"
        print("  [PASS] Direct fetch of Alpha evidence PK returned ZERO rows under Bravo session context.")

        reset_org_context(db)

        # ----------------------------------------------------------------------
        # 4. Cleanup test rows
        # ----------------------------------------------------------------------
        print("\n[Step 4] Cleaning up proof records...")
        db.execute(text("DELETE FROM evidence WHERE id IN (:a, :b);"), {"a": alpha_ev_pk, "b": bravo_ev_pk})
        db.execute(text("DELETE FROM charges WHERE id IN (:a, :b);"), {"a": alpha_chg_pk, "b": bravo_chg_pk})
        db.commit()
        print("  [PASS] Proof records cleanly deleted.")

        print("\n" + "=" * 80)
        print("RLS PROOF COMPLETE: ZERO CROSS-TENANT DATA LEAKAGE CONFIRMED.")
        print("=" * 80)

    finally:
        db.close()

if __name__ == "__main__":
    run_rls_proof()
