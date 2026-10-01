"""
Test script to run the 5 real CSV files through the ingestion services
and verify row counts, errors, and rejections.
"""
import sys
import os

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.core.database import SessionLocal, set_org_context, reset_org_context
from app.ingestion.service import ingestion_service
from app.models.charge import Charge
from app.models.evidence import Evidence
from sqlalchemy import text

def test_ingest_all():
    print("=" * 80)
    print("TESTING INGESTION OF 5 REAL SAMPLE CSVS")
    print("=" * 80)

    db = SessionLocal()
    try:
        # 1. Fee Report Sample
        fee_path = os.path.abspath("data/fee_report_sample.csv")
        print(f"\n[1] Ingesting charges from {fee_path}...")
        fee_res = ingestion_service.ingest_charges(fee_path, db=db, auto_create_containers=True)
        print(f"  Charges result: total={fee_res.total_records}, inserted={fee_res.inserted_count}, "
              f"duplicates={fee_res.duplicate_count}, failed={fee_res.failed_count}")
        if fee_res.errors:
            print(f"  Errors: {fee_res.errors[:5]}")

        # 2. Receiving Sample
        rcv_path = os.path.abspath("data/upstream/receiving_sample.csv")
        print(f"\n[2] Ingesting receiving evidence from {rcv_path}...")
        rcv_res = ingestion_service.ingest_receiving_evidence(rcv_path, db=db)
        print(f"  Receiving result: total={rcv_res.total_records}, inserted={rcv_res.inserted_count}, "
              f"duplicates={rcv_res.duplicate_count}, failed={rcv_res.failed_count}")
        if rcv_res.errors:
            print(f"  Errors: {rcv_res.errors[:5]}")

        # 3. Prep Sample
        prep_path = os.path.abspath("data/upstream/prep_sample.csv")
        print(f"\n[3] Ingesting prep evidence from {prep_path}...")
        prep_res = ingestion_service.ingest_prep_evidence(prep_path, db=db)
        print(f"  Prep result: total={prep_res.total_records}, inserted={prep_res.inserted_count}, "
              f"duplicates={prep_res.duplicate_count}, failed={prep_res.failed_count}")
        if prep_res.errors:
            print(f"  Errors: {prep_res.errors[:5]}")

        # 4. Pack Sample
        pack_path = os.path.abspath("data/upstream/pack_sample.csv")
        print(f"\n[4] Ingesting pack evidence from {pack_path}...")
        pack_res = ingestion_service.ingest_pack_evidence(pack_path, db=db)
        print(f"  Pack result: total={pack_res.total_records}, inserted={pack_res.inserted_count}, "
              f"duplicates={pack_res.duplicate_count}, failed={pack_res.failed_count}")
        if pack_res.errors:
            print(f"  Errors: {pack_res.errors[:5]}")

        # 5. Returns Sample
        ret_path = os.path.abspath("data/upstream/returns_sample.csv")
        print(f"\n[5] Ingesting returns evidence from {ret_path}...")
        ret_res = ingestion_service.ingest_returns_evidence(ret_path, db=db)
        print(f"  Returns result: total={ret_res.total_records}, inserted={ret_res.inserted_count}, "
              f"duplicates={ret_res.duplicate_count}, failed={ret_res.failed_count}")
        if ret_res.errors:
            print(f"  Errors: {ret_res.errors[:5]}")

        # Report totals from DB
        charges_cnt = db.execute(text("SELECT count(*) FROM charges;")).scalar()
        evidence_cnt = db.execute(text("SELECT count(*) FROM evidence;")).scalar()
        print("\n" + "=" * 80)
        print(f"DATABASE COUNTS POST-INGESTION: charges={charges_cnt}, evidence={evidence_cnt}")
        print("=" * 80)

    finally:
        db.close()

if __name__ == "__main__":
    test_ingest_all()
