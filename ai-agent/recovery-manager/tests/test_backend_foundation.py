import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Numeric
from sqlalchemy.exc import OperationalError

# Ensure backend directory is on sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app
from app.core.logging import SensitiveDataFilter
from app.models import (
    Base,
    Shipment,
    Order,
    Charge,
    Evidence,
    Reimbursement,
    Claim,
    ClaimEvidence,
    AssessmentOutcome,
    AssessmentLog,
    Override,
    PipelineError,
)


@pytest.fixture
def client():
    """Test client for FastAPI application."""
    return TestClient(app, headers={"X-Org-Id": "org_test_alpha"}, raise_server_exceptions=False)


# ==============================================================================
# Test A: Application Import
# ==============================================================================
def test_application_import():
    """Verify FastAPI application and its core modules import successfully."""
    from app.main import app as main_app
    assert main_app is not None
    assert main_app.title == "Recovery Manager API"


# ==============================================================================
# Test B: Health Endpoint Responds
# ==============================================================================
def test_health_endpoint_responds(client):
    """Verify GET /health returns structured JSON with expected keys."""
    response = client.get("/health")
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert "database" in data
    assert "version" in data
    assert "environment" in data


# ==============================================================================
# Test C: Live Database Health Check
# ==============================================================================
def test_database_health_live(client):
    """Verify GET /health reports connected when PostgreSQL is reachable."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


# ==============================================================================
# Test D: Invalid / Unavailable Database Scenario
# ==============================================================================
def test_invalid_database_scenario(client):
    """
    Verify GET /health returns 503 Service Unavailable and reports
    disconnected when database cannot be reached. Does not damage real DB.
    """
    with patch("app.api.routes.health.check_database_connection", return_value=False):
        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] == "disconnected"


# ==============================================================================
# Test E: Model Metadata Mirrors Phase 1 Schema Exactly
# ==============================================================================
def test_model_metadata_mirrors_phase1_schema():
    """
    Verify that all 7 ORM models map to the exact Phase 1 table names,
    have primary keys, and define required fields without calling create_all().
    """
    expected_tables = {
        "shipments": Shipment,
        "orders": Order,
        "charges": Charge,
        "evidence": Evidence,
        "reimbursements": Reimbursement,
        "claims": Claim,
        "claim_evidence": ClaimEvidence,
        "assessment_log": AssessmentLog,
        "overrides": Override,
        "pipeline_errors": PipelineError,
    }

    assert len(Base.metadata.tables) == 10

    for table_name, model_cls in expected_tables.items():
        assert table_name in Base.metadata.tables
        table = Base.metadata.tables[table_name]
        assert model_cls.__tablename__ == table_name
        assert "id" in table.c
        assert table.c.id.primary_key

    # Check claims assessment enum values
    valid_assessments = {"CONTRADICTED", "SUPPORTED", "SILENT", "UNCERTAIN"}
    enum_values = {e.value for e in AssessmentOutcome}
    assert enum_values == valid_assessments


# ==============================================================================
# Test F: Financial Precision (Monetary fields must NOT use Float)
# ==============================================================================
def test_financial_precision_numeric_type():
    """
    Verify monetary fields (charges.amount, reimbursements.amount, claims.claim_amount)
    use fixed-precision Numeric/Decimal representation rather than floating-point.
    """
    charges_table = Base.metadata.tables["charges"]
    reimbursements_table = Base.metadata.tables["reimbursements"]
    claims_table = Base.metadata.tables["claims"]

    # charges.amount
    charge_amt_col = charges_table.c.amount
    assert isinstance(charge_amt_col.type, Numeric)
    assert charge_amt_col.type.precision == 12
    assert charge_amt_col.type.scale == 2

    # reimbursements.amount
    reimb_amt_col = reimbursements_table.c.amount
    assert isinstance(reimb_amt_col.type, Numeric)
    assert reimb_amt_col.type.precision == 12
    assert reimb_amt_col.type.scale == 2

    # claims.claim_amount
    claim_amt_col = claims_table.c.claim_amount
    assert isinstance(claim_amt_col.type, Numeric)
    assert claim_amt_col.type.precision == 12
    assert claim_amt_col.type.scale == 2


# ==============================================================================
# Test G: Error Handling - Database Error Sanitization
# ==============================================================================
def test_database_error_handler_sanitizes(client):
    """Verify SQLAlchemy exceptions return 500 without leaking SQL or DB credentials."""
    with patch("app.api.routes.health.check_database_connection", side_effect=OperationalError("SELECT 1", {}, Exception("Connection refused"))):
        response = client.get("/health")
        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "Database Error"
        assert "password" not in response.text
        assert "SELECT 1" not in response.text


# ==============================================================================
# Test H: Error Handling - Unexpected Error
# ==============================================================================
def test_unhandled_exception_handler(client):
    """Verify unhandled exceptions return 500 without crashing."""
    with patch("app.api.routes.health.check_database_connection", side_effect=RuntimeError("Simulated unexpected crash")):
        response = client.get("/health")
        assert response.status_code == 500
        data = response.json()
        assert data["error"] == "Internal Server Error"


# ==============================================================================
# Test I: Security - Sensitive Data Log Filter
# ==============================================================================
def test_sensitive_data_log_filter():
    """Verify SensitiveDataFilter scrubs credentials, tokens, and URIs."""
    import logging
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="",
        lineno=0,
        msg="Connecting to postgresql://postgres:SecretPassword123@db.supabase.co:5432/postgres with sk-ant-api03-1234567890",
        args=(),
        exc_info=None,
    )
    f = SensitiveDataFilter()
    f.filter(record)
    assert "SecretPassword123" not in record.msg
    assert "://postgres:***@" in record.msg
    assert "sk-ant-***" in record.msg

