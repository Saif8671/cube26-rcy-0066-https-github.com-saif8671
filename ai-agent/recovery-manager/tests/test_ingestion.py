"""Tests for Phase 3 Ingestion Layer.

Covers all 26 Phase 3 requirements:
1. Valid CSV
2. Valid XLSX
3. Valid JSON
4. Malformed JSON
5. Empty file
6. Unsupported extension
7. Missing required identifier
8. Invalid amount
9. Invalid timestamp
10. Missing required foreign-key reference
11. Valid charge ingestion
12. Valid reimbursement ingestion
13. Valid evidence ingestion
14. Duplicate charge rejected safely
15. Duplicate reimbursement rejected safely
16. Duplicate evidence rejected safely
17. Explicit shipment identifier resolves correctly
18. Explicit order identifier resolves correctly
19. Explicit reimbursement -> charge relationship resolves correctly
20. Unknown identifier is rejected
21. No fuzzy matching occurs
22. Monetary precision preserved
23. No invented identifiers
24. No invented evidence
25. Raw source data preserved appropriately
26. Database remains consistent after failed ingestion
Plus API endpoint integration tests and intra-batch duplicate checks.
"""

from decimal import Decimal
import io
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

# Ensure backend directory is on sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app
from app.core.database import SessionLocal
from app.ingestion.exceptions import (
    EmptyFileError,
    MalformedFileError,
    RecordValidationError,
    UnsupportedFormatError,
)
from app.ingestion.readers import read_csv, read_file, read_json, read_xlsx
from app.ingestion.service import ingestion_service
from app.models.charge import Charge
from app.models.evidence import Evidence
from app.models.order import Order
from app.models.reimbursement import Reimbursement
from app.models.shipment import Shipment

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "ingestion"


@pytest.fixture
def client():
    """TestClient for FastAPI app."""
    return TestClient(app, headers={"X-Org-Id": "org_test_alpha"}, raise_server_exceptions=False)


@pytest.fixture
def db_session():
    """Provides a managed database session for verification.

    Explicitly resets role/org to superuser at fixture start to avoid
    pooled-connection contamination from sessions that previously called
    SET ROLE authenticated (e.g., via get_db()). Ingestion tests write
    multi-org data and must operate under BYPASSRLS.
    """
    session = SessionLocal()
    try:
        # Reset any pooled session that may have had SET ROLE authenticated
        session.execute(text("RESET ROLE;"))
        session.execute(text("RESET app.current_org;"))
        yield session
    finally:
        try:
            session.execute(text("RESET ROLE;"))
            session.execute(text("RESET app.current_org;"))
        except Exception:
            pass
        session.close()


@pytest.fixture(autouse=True)
def clean_test_data():
    """Clean up test records before and after each test."""
    def _cleanup():
        db = SessionLocal()
        try:
            db.execute(text("DELETE FROM claim_evidence WHERE org_id LIKE 'org_test_%'"))
            db.execute(text("DELETE FROM claims WHERE org_id LIKE 'org_test_%'"))
            db.execute(text("DELETE FROM assessment_log WHERE org_id LIKE 'org_test_%'"))
            db.execute(text("DELETE FROM reimbursements WHERE org_id LIKE 'org_test_%'"))
            db.execute(text("DELETE FROM evidence WHERE org_id LIKE 'org_test_%'"))
            db.execute(text("DELETE FROM charges WHERE org_id LIKE 'org_test_%'"))
            db.execute(text("DELETE FROM shipments WHERE org_id LIKE 'org_test_%'"))
            db.execute(text("DELETE FROM orders WHERE org_id LIKE 'org_test_%'"))
            db.commit()
        except Exception:
            db.rollback()
        finally:
            db.close()

    _cleanup()
    yield
    _cleanup()


# ==============================================================================
# 1-6. Reader Tests
# ==============================================================================

def test_01_valid_csv():
    """Test 1: Read valid CSV file."""
    rows = read_csv(FIXTURES_DIR / "charges.csv")
    assert len(rows) == 2
    assert rows[0]["charge_id"] == "CHG-TEST-CSV-01"
    assert rows[0]["amount"] == "35.50"
    assert rows[0]["shipment_id"] == "FBA17Z88Y12"


def test_02_valid_xlsx():
    """Test 2: Read valid XLSX file."""
    rows = read_xlsx(FIXTURES_DIR / "charges.xlsx")
    assert len(rows) == 2
    assert rows[0]["charge_id"] == "CHG-TEST-XLSX-01"
    assert str(rows[0]["amount"]) == "65.0" or str(rows[0]["amount"]) == "65" or rows[0]["amount"] == 65.0
    assert rows[0]["shipment_id"] == "FBA17Z88Y13"


def test_03_valid_json():
    """Test 3: Read valid JSON file."""
    rows = read_json(FIXTURES_DIR / "charges.json")
    assert len(rows) == 2
    assert rows[0]["charge_id"] == "CHG-TEST-JSON-01"
    assert rows[1]["charge_id"] == "CHG-TEST-JSON-02"


def test_04_malformed_json():
    """Test 4: Malformed JSON raises MalformedFileError."""
    with pytest.raises(MalformedFileError) as exc_info:
        read_file(FIXTURES_DIR / "malformed.json")
    assert "Malformed JSON" in str(exc_info.value)


def test_05_empty_file():
    """Test 5: Empty file or empty record set raises EmptyFileError."""
    # 0 bytes CSV
    with pytest.raises(EmptyFileError):
        read_csv(b"")

    # CSV with only whitespace
    with pytest.raises(EmptyFileError):
        read_csv(b"   \n  ")

    # CSV with only header row
    with pytest.raises(EmptyFileError):
        read_csv(b"charge_id,amount,charge_type\n")

    # JSON with empty array
    with pytest.raises(EmptyFileError):
        read_json(b"[]")


def test_06_unsupported_extension():
    """Test 6: Unsupported file extension raises UnsupportedFormatError."""
    with pytest.raises(UnsupportedFormatError):
        read_file(b"data", filename="report.pdf")

    with pytest.raises(UnsupportedFormatError):
        read_file(b"data", filename="report.txt")


# ==============================================================================
# 7-10. Validation Tests
# ==============================================================================

def test_07_missing_required_identifier(db_session):
    """Test 7: Missing required business identifier is rejected."""
    # Charge without charge_id
    res_charge = ingestion_service.ingest_charges_records(
        records=[{"amount": "25.00", "charge_type": "Prep fee", "charge_date": "2026-03-15T10:00:00Z"}],
        db=db_session,
    )
    assert res_charge.failed_count == 1
    assert res_charge.inserted_count == 0
    assert any("Missing required field 'charge_id'" in e.reason for e in res_charge.errors)

    # Reimbursement without reimbursement_id
    res_reimb = ingestion_service.ingest_reimbursements_records(
        records=[{"amount": "25.00", "reimbursement_date": "2026-03-15T10:00:00Z"}],
        db=db_session,
    )
    assert res_reimb.failed_count == 1
    assert any("Missing required field 'reimbursement_id'" in e.reason for e in res_reimb.errors)

    # Evidence without evidence_id
    res_evd = ingestion_service.ingest_evidence_records(
        records=[{
            "source_manager": "Prep",
            "evidence_type": "check",
            "evidence_content": {"status": "ok"},
            "evidence_timestamp": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res_evd.failed_count == 1
    assert any("Missing required field 'evidence_id'" in e.reason for e in res_evd.errors)


def test_08_invalid_amount(db_session):
    """Test 8: Invalid or non-positive amount is rejected."""
    # Non-numeric amount
    res1 = ingestion_service.ingest_charges_records(
        records=[{
            "charge_id": "CHG-TEST-BAD-AMT-1",
            "amount": "NOT_A_NUMBER",
            "charge_type": "Fee",
            "charge_date": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res1.failed_count == 1
    assert any("Invalid monetary value" in e.reason for e in res1.errors)

    # Negative amount
    res2 = ingestion_service.ingest_charges_records(
        records=[{
            "charge_id": "CHG-TEST-BAD-AMT-2",
            "amount": "-50.00",
            "charge_type": "Fee",
            "charge_date": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res2.failed_count == 1
    assert any("must be positive" in e.reason for e in res2.errors)

    # Zero amount
    res3 = ingestion_service.ingest_reimbursements_records(
        records=[{
            "reimbursement_id": "RMB-TEST-BAD-AMT",
            "amount": "0.00",
            "reimbursement_date": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res3.failed_count == 1
    assert any("must be positive" in e.reason for e in res3.errors)


def test_09_invalid_timestamp(db_session):
    """Test 9: Invalid timestamp string is rejected."""
    res = ingestion_service.ingest_charges_records(
        records=[{
            "charge_id": "CHG-TEST-BAD-TIME",
            "amount": "25.00",
            "charge_type": "Fee",
            "charge_date": "INVALID_TIMESTAMP_STRING",
        }],
        db=db_session,
    )
    assert res.failed_count == 1
    assert any("Invalid timestamp format" in e.reason for e in res.errors)


def test_10_missing_required_foreign_key_reference(db_session):
    """Test 10: Referencing a non-existent foreign key target is rejected."""
    res = ingestion_service.ingest_charges_records(
        records=[{
            "charge_id": "CHG-TEST-BAD-FK",
            "shipment_id": "NONEXISTENT_SHIPMENT_12345",
            "amount": "25.00",
            "charge_type": "Fee",
            "charge_date": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res.failed_count == 1
    assert res.inserted_count == 0
    print(f"DEBUG ERRORS: {res.errors}")
    assert any(e.error_code == "FOREIGN_KEY_NOT_FOUND" for e in res.errors)
    assert any("NONEXISTENT_SHIPMENT_12345" in e.reason for e in res.errors)


# ==============================================================================
# 11-16. Persistence and Duplicate Tests
# ==============================================================================

def test_11_valid_charge_ingestion(db_session):
    """Test 11: Valid charges in CSV are inserted into PostgreSQL database."""
    res = ingestion_service.ingest_charges(
        FIXTURES_DIR / "charges.csv",
        db=db_session,
    )
    assert res.inserted_count == 2
    assert res.failed_count == 0
    assert "CHG-TEST-CSV-01" in res.inserted_ids
    assert "CHG-TEST-CSV-02" in res.inserted_ids

    # Verify directly in DB
    c1 = db_session.execute(
        select(Charge).where(Charge.charge_id == "CHG-TEST-CSV-01")
    ).scalar_one()
    assert c1.amount == Decimal("35.50")
    assert c1.currency == "USD"
    assert c1.sku == "SKU-A1"
    assert c1.shipment_id is not None  # Resolved to shipment UUID


def test_12_valid_reimbursement_ingestion(db_session):
    """Test 12: Valid reimbursements are inserted into PostgreSQL database."""
    res = ingestion_service.ingest_reimbursements(
        FIXTURES_DIR / "reimbursements.csv",
        db=db_session,
    )
    assert res.inserted_count == 2
    assert res.failed_count == 0

    # Verify directly in DB
    r1 = db_session.execute(
        select(Reimbursement).where(Reimbursement.reimbursement_id == "RMB-TEST-CSV-01")
    ).scalar_one()
    assert r1.amount == Decimal("125.00")
    assert r1.charge_id is not None  # Linked to CHG-FBA-8901

    r2 = db_session.execute(
        select(Reimbursement).where(Reimbursement.reimbursement_id == "RMB-TEST-CSV-02")
    ).scalar_one()
    assert r2.amount == Decimal("30.00")
    assert r2.charge_id is None  # Unlinked reimbursement


def test_13_valid_evidence_ingestion(db_session):
    """Test 13: Valid operational evidence is inserted into PostgreSQL database."""
    res = ingestion_service.ingest_evidence(
        FIXTURES_DIR / "evidence.csv",
        db=db_session,
    )
    assert res.inserted_count == 2
    assert res.failed_count == 0

    # Verify directly in DB
    evd = db_session.execute(
        select(Evidence).where(Evidence.evidence_id == "EVD-TEST-CSV-01")
    ).scalar_one()
    assert evd.source_manager == "Prep"
    assert evd.evidence_type == "packaging_audit"
    assert evd.evidence_content == {"label_verified": True, "barcode_type": "FNSKU"}
    assert evd.shipment_id is not None
    assert evd.order_id is not None


def test_14_duplicate_charge_rejected_safely(db_session):
    """Test 14: Duplicate charge_id (already existing in DB) is rejected safely."""
    # CHG-FBA-8901 exists in seed data
    res = ingestion_service.ingest_charges_records(
        records=[{
            "charge_id": "CHG-FBA-8901",
            "amount": "99.99",
            "charge_type": "Duplicate attempt",
            "charge_date": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res.inserted_count == 0
    assert res.failed_count == 1
    assert res.duplicate_count == 1
    assert any(e.error_code == "DUPLICATE_IDENTIFIER" for e in res.errors)
    assert any("CHG-FBA-8901" in e.reason for e in res.errors)

    # Verify original seed row is unchanged
    original = db_session.execute(
        select(Charge).where(Charge.charge_id == "CHG-FBA-8901")
    ).scalar_one()
    assert original.amount == Decimal("125.00")  # Untouched


def test_15_duplicate_reimbursement_rejected_safely(db_session):
    """Test 15: Duplicate reimbursement_id is rejected safely."""
    # RMB-AMZ-7711 exists in seed data
    res = ingestion_service.ingest_reimbursements_records(
        records=[{
            "reimbursement_id": "RMB-AMZ-7711",
            "amount": "999.00",
            "reimbursement_date": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res.inserted_count == 0
    assert res.failed_count == 1
    assert res.duplicate_count == 1
    assert any(e.error_code == "DUPLICATE_IDENTIFIER" for e in res.errors)

    # Verify original seed row is unchanged
    original = db_session.execute(
        select(Reimbursement).where(Reimbursement.reimbursement_id == "RMB-AMZ-7711")
    ).scalar_one()
    assert original.amount == Decimal("45.50")


def test_16_duplicate_evidence_rejected_safely(db_session):
    """Test 16: Duplicate evidence_id is rejected safely."""
    # EVD-PREP-8821 exists in seed data
    res = ingestion_service.ingest_evidence_records(
        records=[{
            "evidence_id": "EVD-PREP-8821",
            "source_manager": "Pack",
            "evidence_type": "fake_audit",
            "evidence_content": {"tampered": True},
            "evidence_timestamp": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res.inserted_count == 0
    assert res.failed_count == 1
    assert res.duplicate_count == 1
    assert any(e.error_code == "DUPLICATE_IDENTIFIER" for e in res.errors)

    # Verify original seed row is unchanged
    original = db_session.execute(
        select(Evidence).where(Evidence.evidence_id == "EVD-PREP-8821")
    ).scalar_one()
    assert original.source_manager == "Prep"


# ==============================================================================
# 17-21. Identifier Resolution Tests
# ==============================================================================

def test_17_explicit_shipment_identifier_resolves_correctly(db_session):
    """Test 17: External shipment_id resolves to internal shipments.id UUID."""
    expected_shipment = db_session.execute(
        select(Shipment).where(Shipment.shipment_id == "FBA17Z88Y12")
    ).scalar_one()

    res = ingestion_service.ingest_charges_records(
        records=[{
            "charge_id": "CHG-TEST-RESOLVE-SHIP",
            "shipment_id": "FBA17Z88Y12",
            "amount": "10.00",
            "charge_type": "Fee",
            "charge_date": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res.inserted_count == 1

    charge = db_session.execute(
        select(Charge).where(Charge.charge_id == "CHG-TEST-RESOLVE-SHIP")
    ).scalar_one()
    assert charge.shipment_id == expected_shipment.id


def test_18_explicit_order_identifier_resolves_correctly(db_session):
    """Test 18: External order_id resolves to internal orders.id UUID."""
    expected_order = db_session.execute(
        select(Order).where(Order.order_id == "111-2000001-0000001")
    ).scalar_one()

    res = ingestion_service.ingest_charges_records(
        records=[{
            "charge_id": "CHG-TEST-RESOLVE-ORD",
            "order_id": "111-2000001-0000001",
            "amount": "15.00",
            "charge_type": "Fee",
            "charge_date": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res.inserted_count == 1

    charge = db_session.execute(
        select(Charge).where(Charge.charge_id == "CHG-TEST-RESOLVE-ORD")
    ).scalar_one()
    assert charge.order_id == expected_order.id


def test_19_explicit_reimbursement_charge_relationship_resolves_correctly(db_session):
    """Test 19: Reimbursement charge_id resolves to internal charges.id UUID."""
    expected_charge = db_session.execute(
        select(Charge).where(Charge.charge_id == "CHG-FBA-8901")
    ).scalar_one()

    res = ingestion_service.ingest_reimbursements_records(
        records=[{
            "reimbursement_id": "RMB-TEST-RESOLVE-CHG",
            "charge_id": "CHG-FBA-8901",
            "amount": "125.00",
            "reimbursement_date": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res.inserted_count == 1

    reimb = db_session.execute(
        select(Reimbursement).where(Reimbursement.reimbursement_id == "RMB-TEST-RESOLVE-CHG")
    ).scalar_one()
    assert reimb.charge_id == expected_charge.id


def test_20_unknown_identifier_is_rejected(db_session):
    """Test 20: Unknown external identifier is rejected with clear error."""
    res = ingestion_service.ingest_reimbursements_records(
        records=[{
            "reimbursement_id": "RMB-TEST-UNKNOWN-CHG",
            "charge_id": "CHG-NONEXISTENT-9999",
            "amount": "45.00",
            "reimbursement_date": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res.inserted_count == 0
    assert res.failed_count == 1
    assert any(e.error_code == "FOREIGN_KEY_NOT_FOUND" for e in res.errors)
    assert any("CHG-NONEXISTENT-9999" in e.reason for e in res.errors)


def test_21_no_fuzzy_matching_occurs(db_session):
    """Test 21: No fuzzy matching or near-identifier guessing occurs."""
    # Near miss for FBA17Z88Y12: missing last character
    res = ingestion_service.ingest_charges_records(
        records=[{
            "charge_id": "CHG-FUZZY-TEST-01",
            "shipment_id": "FBA17Z88Y1",
            "amount": "20.00",
            "charge_type": "Fee",
            "charge_date": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res.inserted_count == 0
    assert res.failed_count == 1
    assert any(e.error_code == "FOREIGN_KEY_NOT_FOUND" for e in res.errors)


# ==============================================================================
# 22-26. Safety and Traceability Tests
# ==============================================================================

def test_22_monetary_precision_preserved(db_session):
    """Test 22: Monetary precision is strictly preserved as Decimal without float distortion."""
    test_amount_str = "12345.67"
    res = ingestion_service.ingest_charges_records(
        records=[{
            "charge_id": "CHG-PREC-TEST-01",
            "amount": test_amount_str,
            "charge_type": "Precision fee",
            "charge_date": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res.inserted_count == 1

    charge = db_session.execute(
        select(Charge).where(Charge.charge_id == "CHG-PREC-TEST-01")
    ).scalar_one()
    assert isinstance(charge.amount, Decimal)
    assert charge.amount == Decimal("12345.67")


def test_23_no_invented_identifiers(db_session):
    """Test 23: Ingestion never invents shipment or order identifiers."""
    res = ingestion_service.ingest_charges_records(
        records=[{
            "charge_id": "CHG-TEST-NO-INVENT",
            "amount": "25.00",
            "charge_type": "Fee without container",
            "charge_date": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res.inserted_count == 1

    charge = db_session.execute(
        select(Charge).where(Charge.charge_id == "CHG-TEST-NO-INVENT")
    ).scalar_one()
    assert charge.shipment_id is None
    assert charge.order_id is None


def test_24_no_invented_evidence(db_session):
    """Test 24: Evidence is preserved exactly as supplied without synthesized findings."""
    exact_payload = {
        "inspector": "QA-88",
        "seal_intact": True,
        "measured_thickness_mil": 1.72,
    }
    res = ingestion_service.ingest_evidence_records(
        records=[{
            "evidence_id": "EVD-TEST-NO-INVENT",
            "source_manager": "Prep",
            "evidence_type": "exact_proof",
            "evidence_content": exact_payload,
            "evidence_timestamp": "2026-03-15T10:00:00Z",
        }],
        db=db_session,
    )
    assert res.inserted_count == 1

    evd = db_session.execute(
        select(Evidence).where(Evidence.evidence_id == "EVD-TEST-NO-INVENT")
    ).scalar_one()
    assert evd.evidence_content == exact_payload


def test_25_raw_source_data_preserved_appropriately(db_session):
    """Test 25: Raw source data is preserved in raw_data JSONB column for auditability."""
    raw_input = {
        "charge_id": "CHG-TEST-RAW-DATA",
        "amount": "42.00",
        "charge_type": "Audit trail fee",
        "charge_date": "2026-03-15T10:00:00Z",
        "arbitrary_custom_field": "preserved_value_xyz",
        "carrier_code": "UPS-GROUND",
    }
    res = ingestion_service.ingest_charges_records(
        records=[raw_input],
        db=db_session,
    )
    assert res.inserted_count == 1

    charge = db_session.execute(
        select(Charge).where(Charge.charge_id == "CHG-TEST-RAW-DATA")
    ).scalar_one()
    assert "arbitrary_custom_field" in charge.raw_data
    assert charge.raw_data["arbitrary_custom_field"] == "preserved_value_xyz"
    assert charge.raw_data["carrier_code"] == "UPS-GROUND"


def test_26_database_remains_consistent_after_failed_ingestion(db_session):
    """Test 26: Ingestion of invalid rows rejects bad records without corrupting DB or dropping valid records."""
    # invalid_rows.csv has 4 invalid rows and 1 valid row (CHG-VALID-ROW)
    res = ingestion_service.ingest_charges(
        FIXTURES_DIR / "invalid_rows.csv",
        db=db_session,
    )
    assert res.total_records == 5
    assert res.inserted_count == 1
    assert res.failed_count == 4
    assert "CHG-VALID-ROW" in res.inserted_ids

    # Verify the valid record is in DB
    valid_charge = db_session.execute(
        select(Charge).where(Charge.charge_id == "CHG-VALID-ROW")
    ).scalar_one()
    assert valid_charge.amount == Decimal("15.50")


# ==============================================================================
# Additional Tests: Intra-batch Duplicates & API Endpoints
# ==============================================================================

def test_intra_batch_duplicate_charges(db_session):
    """Verify duplicate IDs inside the same file batch are rejected."""
    batch = [
        {
            "charge_id": "CHG-DUP-BATCH-01",
            "amount": "10.00",
            "charge_type": "Fee",
            "charge_date": "2026-03-15T10:00:00Z",
        },
        {
            "charge_id": "CHG-DUP-BATCH-01",  # Intra-batch duplicate
            "amount": "20.00",
            "charge_type": "Fee",
            "charge_date": "2026-03-15T11:00:00Z",
        },
    ]
    res = ingestion_service.ingest_charges_records(batch, db=db_session)
    assert res.total_records == 2
    assert res.inserted_count == 1
    assert res.failed_count == 1
    assert res.duplicate_count == 1
    assert any("current batch" in e.reason for e in res.errors)


def test_api_post_charges_csv(client, db_session):
    """Test API endpoint POST /ingestion/charges with multipart CSV upload."""
    csv_bytes = (
        b"charge_id,amount,charge_type,charge_date\n"
        b"CHG-TEST-API-01,75.00,Storage fee,2026-03-15T10:00:00Z\n"
    )
    response = client.post(
        "/ingestion/charges",
        files={"file": ("api_charges.csv", csv_bytes, "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["record_type"] == "charge"
    assert data["inserted_count"] == 1
    assert "CHG-TEST-API-01" in data["inserted_ids"]


def test_api_post_reimbursements_json(client, db_session):
    """Test API endpoint POST /ingestion/reimbursements with direct JSON payload."""
    payload = [
        {
            "reimbursement_id": "RMB-TEST-API-01",
            "amount": "50.00",
            "reimbursement_date": "2026-03-15T10:00:00Z",
        }
    ]
    response = client.post(
        "/ingestion/reimbursements",
        json=payload,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["record_type"] == "reimbursement"
    assert data["inserted_count"] == 1


def test_api_post_evidence_csv(client, db_session):
    """Test API endpoint POST /ingestion/evidence with multipart CSV upload."""
    csv_bytes = (
        b"evidence_id,source_manager,evidence_type,evidence_content,evidence_timestamp\n"
        b"EVD-TEST-API-01,Receiving,dock_log,\"{\"\"dock\"\": 4}\",2026-03-15T10:00:00Z\n"
    )
    response = client.post(
        "/ingestion/evidence",
        files={"file": ("api_evidence.csv", csv_bytes, "text/csv")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["record_type"] == "evidence"
    assert data["inserted_count"] == 1


def test_api_malformed_file_returns_400(client):
    """Test API returns 400 Bad Request on malformed file upload."""
    response = client.post(
        "/ingestion/charges",
        files={"file": ("broken.json", b"[invalid-json", "application/json")},
    )
    assert response.status_code == 400
    assert "Malformed JSON" in response.json()["detail"]


def test_api_unsupported_format_returns_400(client):
    """Test API returns 400 Bad Request on unsupported file extension."""
    response = client.post(
        "/ingestion/charges",
        files={"file": ("report.pdf", b"%PDF-1.4...", "application/pdf")},
    )
    assert response.status_code == 400
    assert "Unsupported file format" in response.json()["detail"]


# ==============================================================================
# Manager Evidence Ingestion Tests (Receiving / Prep / Pack / Returns)
# Use real upstream sample files from data/upstream/
# ==============================================================================

UPSTREAM_DIR = Path(__file__).resolve().parent.parent / "data" / "upstream"


def test_ingest_receiving_evidence_from_sample_csv(db_session):
    """Receiving normalizer produces correct structure; service handles all rows without errors."""
    from app.ingestion.normalizers import normalize_receiving_evidence
    from app.ingestion.readers import read_csv

    sample_path = UPSTREAM_DIR / "receiving_sample.csv"
    assert sample_path.exists(), f"Sample file missing: {sample_path}"

    raw_rows = read_csv(sample_path)
    assert len(raw_rows) >= 1, "receiving_sample.csv must have at least 1 data row"

    # --- Parser unit test: validate normalizer output structure ---
    first = normalize_receiving_evidence(raw_rows[0])
    assert first["source_manager"] == "Receiving"
    assert first["evidence_type"] == "receiving_inspection"
    assert isinstance(first["evidence_content"], dict)
    assert "unit_id" in first["evidence_content"]
    assert first["evidence_content"]["unit_id"] is not None

    # --- Service integration test: all rows handled cleanly (insert OR idempotent dedup) ---
    norm_rows = [normalize_receiving_evidence(r) for r in raw_rows]
    result = ingestion_service.ingest_evidence_records(
        records=norm_rows,
        db=db_session,
        source_report="receiving_sample_test",
        auto_create_containers=True,
    )
    assert result.record_type == "evidence"
    assert result.total_records == len(norm_rows)
    # All records either inserted or safely deduplicated — no unhandled errors
    assert result.inserted_count + result.duplicate_count == result.total_records, (
        f"Receiving: inserted={result.inserted_count} + duplicate={result.duplicate_count} "
        f"!= total={result.total_records} — some records raised unexpected errors"
    )


def test_ingest_prep_evidence_from_sample_csv(db_session):
    """Prep normalizer produces correct structure; service handles all rows without errors."""
    from app.ingestion.normalizers import normalize_prep_evidence
    from app.ingestion.readers import read_csv

    sample_path = UPSTREAM_DIR / "prep_sample.csv"
    assert sample_path.exists(), f"Sample file missing: {sample_path}"

    raw_rows = read_csv(sample_path)
    assert len(raw_rows) >= 1, "prep_sample.csv must have at least 1 data row"

    first = normalize_prep_evidence(raw_rows[0])
    assert first["source_manager"] == "Prep"
    assert first["evidence_type"] == "prep_inspection"
    assert isinstance(first["evidence_content"], dict)
    assert "requirements" in first["evidence_content"] or "wo_polybag" in first["evidence_content"]

    norm_rows = [normalize_prep_evidence(r) for r in raw_rows]
    result = ingestion_service.ingest_evidence_records(
        records=norm_rows,
        db=db_session,
        source_report="prep_sample_test",
        auto_create_containers=True,
    )
    assert result.record_type == "evidence"
    assert result.total_records == len(norm_rows)
    assert result.inserted_count + result.duplicate_count == result.total_records, (
        f"Prep: inserted={result.inserted_count} + duplicate={result.duplicate_count} "
        f"!= total={result.total_records} — some records raised unexpected errors"
    )


def test_ingest_pack_evidence_from_sample_csv(db_session):
    """Pack normalizer produces correct structure; service handles all rows without errors."""
    from app.ingestion.normalizers import normalize_pack_evidence
    from app.ingestion.readers import read_csv

    sample_path = UPSTREAM_DIR / "pack_sample.csv"
    assert sample_path.exists(), f"Sample file missing: {sample_path}"

    raw_rows = read_csv(sample_path)
    assert len(raw_rows) >= 1, "pack_sample.csv must have at least 1 data row"

    first = normalize_pack_evidence(raw_rows[0])
    assert first["source_manager"] == "Pack"
    assert first["evidence_type"] == "pack_verification"
    assert isinstance(first["evidence_content"], dict)
    assert "operator_verdict" in first["evidence_content"]

    norm_rows = [normalize_pack_evidence(r) for r in raw_rows]
    result = ingestion_service.ingest_evidence_records(
        records=norm_rows,
        db=db_session,
        source_report="pack_sample_test",
        auto_create_containers=True,
    )
    assert result.record_type == "evidence"
    assert result.total_records == len(norm_rows)
    assert result.inserted_count + result.duplicate_count == result.total_records, (
        f"Pack: inserted={result.inserted_count} + duplicate={result.duplicate_count} "
        f"!= total={result.total_records} — some records raised unexpected errors"
    )


def test_ingest_returns_evidence_from_sample_csv(db_session):
    """Returns normalizer produces correct structure; service handles all rows without errors."""
    from app.ingestion.normalizers import normalize_returns_evidence
    from app.ingestion.readers import read_csv

    sample_path = UPSTREAM_DIR / "returns_sample.csv"
    assert sample_path.exists(), f"Sample file missing: {sample_path}"

    raw_rows = read_csv(sample_path)
    assert len(raw_rows) >= 1, "returns_sample.csv must have at least 1 data row"

    first = normalize_returns_evidence(raw_rows[0])
    assert first["source_manager"] == "Returns"
    assert first["evidence_type"] == "return_evaluation"
    assert isinstance(first["evidence_content"], dict)
    assert "operator_disposition" in first["evidence_content"]

    norm_rows = [normalize_returns_evidence(r) for r in raw_rows]
    result = ingestion_service.ingest_evidence_records(
        records=norm_rows,
        db=db_session,
        source_report="returns_sample_test",
        auto_create_containers=True,
    )
    assert result.record_type == "evidence"
    assert result.total_records == len(norm_rows)
    assert result.inserted_count + result.duplicate_count == result.total_records, (
        f"Returns: inserted={result.inserted_count} + duplicate={result.duplicate_count} "
        f"!= total={result.total_records} — some records raised unexpected errors"
    )

