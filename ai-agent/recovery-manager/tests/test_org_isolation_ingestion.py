"""Unit tests verifying organization RLS isolation and error handling during ingestion.

Covers:
1. Upload fee_report_sample.csv with X-Org-Id: org_test_alpha (40 alpha accepted, 21 bravo rejected with ORG_MISMATCH)
2. Upload fee_report_sample.csv with X-Org-Id: org_test_bravo (21 bravo accepted, 40 alpha rejected with ORG_MISMATCH)
3. Upload test_upload_charges.csv without org_id uses session org
4. Mixed batch with malformed row and org mismatch isolates failure per row
5. Re-upload detects duplicates and reports DUPLICATE_IDENTIFIER without crashing
6. Evidence ingestion enforces identical org isolation
"""

from pathlib import Path
import sys
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app
from app.core.database import SessionLocal

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_CHARGES_PATH = REPO_ROOT / "test_upload_charges.csv"

ORG_ALPHA = "org_test_alpha"
ORG_BRAVO = "org_test_bravo"


def synthetic_rows():
    return [
        {"charge_id": "CHG-TEST-ALPHA-01", "org_id": ORG_ALPHA, "amount": "10.00", "charge_type": "fulfilment_fee_weight_tier", "charge_date": "2026-06-01T10:00:00Z"},
        {"charge_id": "CHG-TEST-ALPHA-02", "org_id": ORG_ALPHA, "amount": "11.00", "charge_type": "inbound_defect_fee", "charge_date": "2026-06-01T10:00:00Z"},
        {"charge_id": "CHG-TEST-BRAVO-01", "org_id": ORG_BRAVO, "amount": "12.00", "charge_type": "fulfilment_fee_weight_tier", "charge_date": "2026-06-01T10:00:00Z"},
        {"charge_id": "CHG-TEST-BRAVO-02", "org_id": ORG_BRAVO, "amount": "13.00", "charge_type": "inbound_defect_fee", "charge_date": "2026-06-01T10:00:00Z"},
    ]


@pytest.fixture(autouse=True)
def clean_test_ingestion_records():
    """Ensure test charge and evidence records are cleaned before and after tests."""
    def _cleanup():
        session = SessionLocal()
        try:
            session.execute(text("RESET ROLE;"))
            session.execute(text("RESET app.current_org;"))
            session.execute(text("DELETE FROM claim_evidence WHERE org_id LIKE 'org_test_%';"))
            session.execute(text("DELETE FROM claims WHERE org_id LIKE 'org_test_%';"))
            session.execute(text("DELETE FROM assessment_log WHERE org_id LIKE 'org_test_%';"))
            session.execute(text("DELETE FROM reimbursements WHERE org_id LIKE 'org_test_%';"))
            session.execute(text("DELETE FROM evidence WHERE org_id LIKE 'org_test_%';"))
            session.execute(text("DELETE FROM charges WHERE org_id LIKE 'org_test_%';"))
            session.execute(text("DELETE FROM shipments WHERE org_id LIKE 'org_test_%';"))
            session.execute(text("DELETE FROM orders WHERE org_id LIKE 'org_test_%';"))
            session.commit()
        except Exception:
            session.rollback()
        finally:
            session.close()

    _cleanup()
    yield
    _cleanup()


def test_synthetic_alpha_session():
    """Alpha session accepts only its own synthetic rows."""
    client = TestClient(app, headers={"X-Org-Id": ORG_ALPHA}, raise_server_exceptions=False)
    response = client.post("/ingestion/charges", json=synthetic_rows())

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["total_records"] == 4
    assert data["inserted_count"] == 2
    assert data["failed_count"] == 2
    assert data["accepted"] + data["rejected"] == data["total_rows"]

    for err in data["errors"]:
        assert err["error_code"] == "ORG_MISMATCH"
        assert err["reason_code"] == "ORG_MISMATCH"
        assert err.get("charge_id") is not None
        assert err.get("row_index") is not None


def test_synthetic_bravo_session():
    """Bravo session accepts only its own synthetic rows."""
    client = TestClient(app, headers={"X-Org-Id": ORG_BRAVO}, raise_server_exceptions=False)
    response = client.post("/ingestion/charges", json=synthetic_rows())

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["total_records"] == 4
    assert data["inserted_count"] == 2
    assert data["failed_count"] == 2
    assert data["accepted"] + data["rejected"] == data["total_rows"]

    for err in data["errors"]:
        assert err["error_code"] == "ORG_MISMATCH"
        assert err["reason_code"] == "ORG_MISMATCH"
        assert err.get("charge_id") is not None
        assert err.get("row_index") is not None


def test_upload_charges_without_org_id_uses_session_org():
    """test_upload_charges.csv has no org_id column; rows must adopt session org."""
    client = TestClient(app, headers={"X-Org-Id": "org_test_alpha"}, raise_server_exceptions=False)
    with open(TEST_CHARGES_PATH, "rb") as f:
        response = client.post(
            "/ingestion/charges",
            files={"file": ("test_upload_charges.csv", f, "text/csv")},
        )

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["total_records"] == 2
    assert data["inserted_count"] == 2
    assert data["failed_count"] == 0
    assert len(data["errors"]) == 0

    # Verify rows in DB have org_test_alpha
    session = SessionLocal()
    try:
        session.execute(text("SET ROLE authenticated;"))
        session.execute(text("SELECT set_config('app.current_org', 'org_test_alpha', false);"))
        rows = session.execute(
            text("SELECT charge_id, org_id FROM charges WHERE charge_id LIKE 'CHG-UPLOAD-DEMO%';")
        ).fetchall()
        assert len(rows) == 2
        for r in rows:
            assert r[1] == "org_test_alpha"
    finally:
        session.execute(text("RESET ROLE;"))
        session.execute(text("RESET app.current_org;"))
        session.close()


def test_malformed_and_mismatched_rows_rejected_individually():
    """Malformed and mismatched rows fail independently inside per-row savepoint."""
    client = TestClient(app, headers={"X-Org-Id": "org_test_alpha"}, raise_server_exceptions=False)
    batch = [
        # Row 0: valid with matching org
        {
            "charge_id": "CHG-ISO-01",
            "org_id": "org_test_alpha",
            "amount": "45.00",
            "charge_type": "fulfilment_fee_weight_tier",
            "charge_date": "2026-06-01T10:00:00Z",
        },
        # Row 1: malformed (negative amount)
        {
            "charge_id": "CHG-ISO-02",
            "org_id": "org_test_alpha",
            "amount": "-15.00",
            "charge_type": "fulfilment_fee_weight_tier",
            "charge_date": "2026-06-01T10:00:00Z",
        },
        # Row 2: org mismatch (org_test_bravo in alpha session)
        {
            "charge_id": "CHG-ISO-03",
            "org_id": "org_test_bravo",
            "amount": "30.00",
            "charge_type": "fulfilment_fee_weight_tier",
            "charge_date": "2026-06-01T10:00:00Z",
        },
        # Row 3: valid with no explicit org (adopts session org)
        {
            "charge_id": "CHG-ISO-04",
            "amount": "25.00",
            "charge_type": "inbound_defect_fee",
            "charge_date": "2026-06-01T10:00:00Z",
        },
    ]

    response = client.post("/ingestion/charges", json=batch)
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["total_records"] == 4
    assert data["inserted_count"] == 2
    assert data["failed_count"] == 2
    assert "CHG-ISO-01" in data["inserted_ids"]
    assert "CHG-ISO-04" in data["inserted_ids"]

    error_codes = {e["error_code"] for e in data["errors"]}
    assert "VALIDATION_ERROR" in error_codes
    assert "ORG_MISMATCH" in error_codes


def test_duplicate_reupload_detected():
    """Re-uploading the same charges detects duplicates without failing the entire request."""
    client = TestClient(app, headers={"X-Org-Id": "org_test_alpha"}, raise_server_exceptions=False)
    batch = [
        {
            "charge_id": "CHG-ISO-DUP-01",
            "amount": "50.00",
            "charge_type": "fulfilment_fee_weight_tier",
            "charge_date": "2026-06-01T10:00:00Z",
        },
    ]

    # First upload
    res1 = client.post("/ingestion/charges", json=batch)
    assert res1.status_code == 200
    assert res1.json()["inserted_count"] == 1

    # Second upload (same identifier)
    res2 = client.post("/ingestion/charges", json=batch)
    assert res2.status_code == 200
    data2 = res2.json()
    assert data2["inserted_count"] == 0
    assert data2["duplicate_count"] == 1
    assert data2["failed_count"] == 1
    assert any(e["error_code"] == "DUPLICATE_IDENTIFIER" for e in data2["errors"])


def test_missing_charge_id_is_rejected_without_aborting_batch():
    """A malformed row is reported while valid rows in the same batch commit."""
    client = TestClient(app, headers={"X-Org-Id": "org_test_alpha"}, raise_server_exceptions=False)
    response = client.post("/ingestion/charges", json=[
        {
            "charge_id": "CHG-ISO-MALFORMED-OK",
            "amount": "12.00",
            "charge_type": "inbound_defect_fee",
            "charge_date": "2026-06-01T10:00:00Z",
        },
        {
            "amount": "not-a-number",
            "charge_type": "inbound_defect_fee",
            "charge_date": "2026-06-01T10:00:00Z",
        },
    ])

    assert response.status_code == 200, response.text
    data = response.json()
    assert data["accepted"] == 1
    assert data["rejected"] == 1
    assert data["rejected_rows"][0]["row"] == 2
    assert data["rejected_rows"][0]["charge_id"] is None
    assert data["rejected_rows"][0]["reason"]


def test_evidence_ingestion_org_isolation():
    """Evidence ingestion enforces same org-mismatch rejection and per-row savepoint."""
    client = TestClient(app, headers={"X-Org-Id": "org_test_alpha"}, raise_server_exceptions=False)
    batch = [
        # Matching org
        {
            "evidence_id": "EVI-ISO-01",
            "source_manager": "Receiving",
            "evidence_type": "receiving_discrepancy",
            "evidence_content": {"sku": "SKU-A", "qty": 1},
            "evidence_timestamp": "2026-06-01T10:00:00Z",
            "org_id": "org_test_alpha",
        },
        # Mismatched org
        {
            "evidence_id": "EVI-ISO-02",
            "source_manager": "Receiving",
            "evidence_type": "receiving_discrepancy",
            "evidence_content": {"sku": "SKU-B", "qty": 2},
            "evidence_timestamp": "2026-06-01T10:00:00Z",
            "org_id": "org_test_bravo",
        },
    ]

    response = client.post("/ingestion/evidence", json=batch)
    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
    data = response.json()
    assert data["total_records"] == 2
    assert data["inserted_count"] == 1
    assert data["failed_count"] == 1
    assert "EVI-ISO-01" in data["inserted_ids"]
    assert any(e["error_code"] == "ORG_MISMATCH" for e in data["errors"])

