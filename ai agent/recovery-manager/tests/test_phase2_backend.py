"""Tests for Phase 2 Backend:
- Counter exclusivity (inserted + duplicates + failed == total)
- Re-upload idempotence
- Tenant-mismatch error output with exact rows and reasons
- Multi-file evidence events ingestion (POST /ingest/evidence)
- Operational matching service (linking charges to evidence by shipment_id)
- Background task and job status polling (GET /jobs/{job_id})
- Bundle ingestion (ZIP)
"""

import io
import time
import zipfile
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from auth_test_utils import auth_headers
from sqlalchemy import select, text

# Ensure backend directory is on sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app
from app.core.database import SessionLocal
from app.ingestion.service import ingestion_service
from app.ingestion.evidence_events_service import evidence_events_service
from app.models.charge import Charge
from app.models.evidence_event import EvidenceEvent
from app.models.shipment import Shipment
from app.services.matching_service import matching_service

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
UPSTREAM_DIR = DATA_DIR / "upstream"


@pytest.fixture
def client():
    """TestClient for FastAPI app with demo tenant header."""
    return TestClient(app, headers=auth_headers("org_demo_alpha"), raise_server_exceptions=False)


@pytest.fixture
def db():
    """Provides a managed database session with superuser permissions."""
    session = SessionLocal()
    try:
        session.execute(text("RESET ROLE; RESET app.current_org;"))
        yield session
    finally:
        try:
            session.execute(text("RESET ROLE; RESET app.current_org;"))
        except Exception:
            pass
        session.close()


@pytest.fixture(autouse=True)
def clean_phase2_test_records(db):
    """Clean test records before and after each test."""
    def _cleanup():
        db.execute(text("DELETE FROM evidence_events WHERE source_file LIKE '%test%' OR source_file LIKE '%prep%' OR source_file LIKE '%async%' OR shipment_id LIKE '%TEST%' OR shipment_id LIKE '%BUNDLE%' OR shipment_id LIKE '%MULTI%'"))
        db.execute(text("DELETE FROM charges WHERE charge_id LIKE 'CHG-P2-%' OR charge_id LIKE 'TEST-%'"))
        db.commit()

    _cleanup()
    yield
    _cleanup()


# ==============================================================================
# 1. Counter Exclusivity Tests
# ==============================================================================
def test_counter_exclusivity_charge_ingestion(db):
    """
    Test that inserted + duplicates + failed == total exactly,
    and duplicates NEVER increment failed_count.
    """
    # 1. Insert an existing charge
    db.execute(text("""
        INSERT INTO charges (charge_id, amount, charge_type, charge_date, org_id)
        VALUES ('CHG-P2-EXISTING', 10.00, 'inbound_defect_fee', '2026-06-01 10:00:00+00', 'org_demo_alpha')
        ON CONFLICT (charge_id) DO NOTHING;
    """))
    db.commit()

    # Batch with:
    # - 2 valid new charges
    # - 1 DB duplicate (CHG-P2-EXISTING)
    # - 1 intra-batch duplicate (second CHG-P2-NEW-1)
    # - 1 invalid charge (invalid amount)
    batch = [
        {"charge_id": "CHG-P2-NEW-1", "amount": "15.00", "charge_type": "inbound_defect_fee", "charge_date": "2026-06-02T10:00:00Z", "org_id": "org_demo_alpha"},
        {"charge_id": "CHG-P2-NEW-2", "amount": "25.00", "charge_type": "inbound_defect_fee", "charge_date": "2026-06-02T10:00:00Z", "org_id": "org_demo_alpha"},
        {"charge_id": "CHG-P2-EXISTING", "amount": "10.00", "charge_type": "inbound_defect_fee", "charge_date": "2026-06-01T10:00:00Z", "org_id": "org_demo_alpha"},
        {"charge_id": "CHG-P2-NEW-1", "amount": "15.00", "charge_type": "inbound_defect_fee", "charge_date": "2026-06-02T10:00:00Z", "org_id": "org_demo_alpha"},
        {"charge_id": "CHG-P2-INVALID", "amount": "NOT_NUMBER", "charge_type": "inbound_defect_fee", "charge_date": "2026-06-02T10:00:00Z", "org_id": "org_demo_alpha"},
    ]

    res = ingestion_service.ingest_charges_records(batch, db=db, active_tenant="org_demo_alpha")

    assert res.total_records == 5
    assert res.inserted_count == 2
    assert res.duplicate_count == 2
    assert res.failed_count == 1
    # Check strict mutual exclusivity
    assert res.inserted_count + res.duplicate_count + res.failed_count == res.total_records
    # Errors list contains only the genuinely failed row
    assert len(res.errors) == 1
    assert res.errors[0].identifier == "CHG-P2-INVALID"


# ==============================================================================
# 2. Re-upload Idempotence Tests
# ==============================================================================
def test_evidence_reupload_idempotence(db):
    """
    Test that re-uploading an evidence file is idempotent:
    First upload: inserted = total, duplicates = 0, failed = 0
    Second upload: inserted = 0, duplicates = total, failed = 0
    Total database records unchanged on re-upload.
    """
    csv_content = (
        "record_id,unit_id,fba_shipment_id,sku,asin,captured_at,org_id\n"
        "TEST-REC-01,UNIT-01,FBA-TEST-900,SKU-A,ASIN-A,2026-06-10T10:00:00Z,org_demo_alpha\n"
        "TEST-REC-02,UNIT-02,FBA-TEST-900,SKU-B,ASIN-B,2026-06-10T11:00:00Z,org_demo_alpha\n"
        "TEST-REC-03,UNIT-03,FBA-TEST-901,SKU-C,ASIN-C,2026-06-11T12:00:00Z,org_demo_alpha\n"
    ).encode("utf-8")

    # 1. First upload
    res1 = evidence_events_service.ingest_single_file(
        file_bytes=csv_content,
        filename="prep_test_upload.csv",
        db=db,
        org_id="org_demo_alpha",
    )
    assert res1.total == 3
    assert res1.inserted == 3
    assert res1.duplicates == 0
    assert res1.failed == 0
    assert res1.inserted + res1.duplicates + res1.failed == res1.total

    db_count_after_first = db.execute(
        select(text("count(*)")).select_from(EvidenceEvent).where(EvidenceEvent.source_file == "prep_test_upload.csv")
    ).scalar()
    assert db_count_after_first == 3

    # 2. Second upload (re-upload same file)
    res2 = evidence_events_service.ingest_single_file(
        file_bytes=csv_content,
        filename="prep_test_upload.csv",
        db=db,
        org_id="org_demo_alpha",
    )
    assert res2.total == 3
    assert res2.inserted == 0
    assert res2.duplicates == 3
    assert res2.failed == 0
    assert res2.inserted + res2.duplicates + res2.failed == res2.total

    db_count_after_second = db.execute(
        select(text("count(*)")).select_from(EvidenceEvent).where(EvidenceEvent.source_file == "prep_test_upload.csv")
    ).scalar()
    assert db_count_after_second == 3  # Unchanged!


# ==============================================================================
# 3. Tenant-Mismatch Error Output Tests
# ==============================================================================
def test_tenant_mismatch_error_output(db):
    """
    Upload fee_report_sample.csv with active tenant org_demo_alpha.
    Verify:
    - Exactly 21 of 61 rows fail
    - 40 rows inserted
    - 0 duplicates
    - inserted + duplicates + failed == total
    - errors list contains 21 items with exact row numbers and TENANT_MISMATCH reason
    """
    # Clean previous FEE-% charges so test starts fresh
    db.execute(text("DELETE FROM charges WHERE charge_id LIKE 'FEE-%'"))
    db.commit()

    fee_sample_path = DATA_DIR / "fee_report_sample.csv"
    assert fee_sample_path.exists()

    with open(fee_sample_path, "rb") as f:
        content = f.read()

    res = ingestion_service.ingest_charges(
        source=content,
        db=db,
        filename="fee_report_sample.csv",
        auto_create_containers=True,
        active_tenant="org_demo_alpha",
    )

    assert res.total_records == 61
    assert res.inserted_count == 40
    assert res.duplicate_count == 0
    assert res.failed_count == 21
    assert res.inserted_count + res.duplicate_count + res.failed_count == res.total_records

    # Verify per-row errors
    assert len(res.errors) == 21
    expected_failing_rows = {3, 4, 8, 14, 15, 16, 17, 20, 25, 28, 31, 32, 33, 35, 39, 52, 53, 55, 57, 61, 62}
    actual_failing_rows = {e.row_index for e in res.errors}
    assert actual_failing_rows == expected_failing_rows

    for err in res.errors:
        assert err.error_code == "TENANT_MISMATCH"
        assert "org_id" in err.reason
        assert err.row is not None


# ==============================================================================
# 4. Multi-File Evidence Endpoint Tests (POST /ingest/evidence)
# ==============================================================================
def test_api_multi_file_evidence_upload(client):
    """Test POST /ingest/evidence accepts multiple files and returns per-file summary."""
    file1_csv = (
        "record_id,fba_shipment_id,captured_at,org_id\n"
        "TEST-PREP-01,FBA-MULTI-01,2026-06-15T10:00:00Z,org_demo_alpha\n"
        "TEST-PREP-02,FBA-MULTI-01,2026-06-15T11:00:00Z,org_demo_alpha\n"
    ).encode("utf-8")

    file2_csv = (
        "record_id,fba_shipment_id,captured_at,org_id\n"
        "TEST-PACK-01,FBA-MULTI-02,2026-06-16T12:00:00Z,org_demo_alpha\n"
    ).encode("utf-8")

    files = [
        ("files", ("prep_test.csv", file1_csv, "text/csv")),
        ("files", ("pack_test.csv", file2_csv, "text/csv")),
    ]

    response = client.post("/ingest/evidence", files=files)
    assert response.status_code == 200
    data = response.json()

    assert data["total_files"] == 2
    assert len(data["files"]) == 2
    assert data["total_records"] == 3
    assert data["total_inserted"] == 3
    assert data["total_duplicates"] == 0
    assert data["total_failed"] == 0

    # Test re-upload through API to verify idempotence through endpoint
    files_repeat = [
        ("files", ("prep_test.csv", file1_csv, "text/csv")),
        ("files", ("pack_test.csv", file2_csv, "text/csv")),
    ]
    response2 = client.post("/ingest/evidence", files=files_repeat)
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["total_inserted"] == 0
    assert data2["total_duplicates"] == 3


# ==============================================================================
# 5. Matching Service Tests
# ==============================================================================
def test_matching_service_with_and_without_evidence(db):
    """
    Test matching charges against evidence_events by shipment_id.
    - Linked charge returns status MATCHED and attached evidence list
    - Charge with NO operational records returns status NO_EVIDENCE_FOUND
    """
    # 1. Seed shipment and charge
    db.execute(text("""
        INSERT INTO shipments (shipment_id, org_id) VALUES ('FBA-MATCH-01', 'org_demo_alpha')
        ON CONFLICT (shipment_id) DO NOTHING;
    """))
    db.execute(text("""
        INSERT INTO charges (charge_id, shipment_id, amount, charge_type, charge_date, org_id)
        SELECT 'CHG-P2-MATCHED', s.id, 50.00, 'inbound_defect_fee', '2026-06-20 12:00:00+00', 'org_demo_alpha'
        FROM shipments s WHERE s.shipment_id = 'FBA-MATCH-01'
        ON CONFLICT (charge_id) DO NOTHING;
    """))
    # Charge with no evidence
    db.execute(text("""
        INSERT INTO charges (charge_id, amount, charge_type, charge_date, org_id, raw_data)
        VALUES ('CHG-P2-ORPHAN', 30.00, 'fulfilment_fee_weight_tier', '2026-06-20 12:00:00+00', 'org_demo_alpha', '{"shipment_id": "FBA-NO-EVIDENCE"}')
        ON CONFLICT (charge_id) DO NOTHING;
    """))
    # Seed matching evidence event
    db.execute(text("""
        INSERT INTO evidence_events (shipment_id, evidence_type, timestamp, source_file, org_id, idempotency_key)
        VALUES ('FBA-MATCH-01', 'prep', '2026-06-18 10:00:00+00', 'prep_sample.csv', 'org_demo_alpha', 'key-match-01')
        ON CONFLICT (idempotency_key) DO NOTHING;
    """))
    db.commit()

    # 2. Test matched charge
    res_matched = matching_service.match_charge("CHG-P2-MATCHED", db=db, window_days=30)
    assert res_matched.has_evidence is True
    assert res_matched.status == "MATCHED"
    assert res_matched.matched_count >= 1
    assert any(e.shipment_id == "FBA-MATCH-01" for e in res_matched.evidence)

    # 3. Test orphan charge (no matching evidence)
    res_orphan = matching_service.match_charge("CHG-P2-ORPHAN", db=db, window_days=30)
    assert res_orphan.has_evidence is False
    assert res_orphan.status == "NO_EVIDENCE_FOUND"
    assert res_orphan.matched_count == 0
    assert res_orphan.evidence == []


# ==============================================================================
# 6. Background Task & Job Polling (GET /jobs/{job_id})
# ==============================================================================
def test_async_ingestion_and_job_polling(client):
    """Test async upload returning job_id immediately and poll status."""
    csv_content = (
        "record_id,fba_shipment_id,captured_at,org_id\n"
        "ASYNC-REC-01,FBA-ASYNC-01,2026-06-15T10:00:00Z,org_demo_alpha\n"
    ).encode("utf-8")

    files = [("files", ("async_test.csv", csv_content, "text/csv"))]
    resp = client.post("/ingest/evidence?async_mode=true", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    job_id = data["job_id"]

    # Poll /jobs/{job_id} until completed
    max_wait = 10
    start = time.time()
    job_data = None
    while time.time() - start < max_wait:
        j_resp = client.get(f"/jobs/{job_id}")
        assert j_resp.status_code == 200
        job_data = j_resp.json()
        if job_data["status"] in ("completed", "failed"):
            break
        time.sleep(0.2)

    assert job_data is not None
    assert job_data["status"] == "completed"
    assert job_data["progress"] == 1.0
    assert job_data["result"]["total_records"] == 1
    assert job_data["result"]["total_inserted"] == 1


# ==============================================================================
# 7. Bundle Ingestion (ZIP containing charges & evidence)
# ==============================================================================
def test_bundle_ingestion_zip(client):
    """Test POST /ingest/bundle with a ZIP containing charges and evidence."""
    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w") as z:
        charges_csv = (
            "charge_id,amount,charge_type,charge_date,org_id\n"
            "CHG-P2-BUNDLE-1,12.00,inbound_defect_fee,2026-06-01T10:00:00Z,org_demo_alpha\n"
        )
        evidence_csv = (
            "record_id,fba_shipment_id,captured_at,org_id\n"
            "BUNDLE-EV-1,FBA-BUNDLE-10,2026-06-02T10:00:00Z,org_demo_alpha\n"
        )
        z.writestr("charges_batch.csv", charges_csv)
        z.writestr("prep_evidence.csv", evidence_csv)

    zip_bytes = zip_buf.getvalue()
    files = {"file": ("bundle_test.zip", zip_bytes, "application/zip")}

    resp = client.post("/ingest/bundle", files=files)
    assert resp.status_code == 200
    data = resp.json()
    assert data["bundle_filename"] == "bundle_test.zip"
    assert len(data["charge_reports"]) == 1
    assert data["charge_reports"][0]["inserted_count"] == 1
    assert data["evidence_summary"]["total_inserted"] == 1
