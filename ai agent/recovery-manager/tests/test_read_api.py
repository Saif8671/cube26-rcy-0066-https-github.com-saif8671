"""Comprehensive Phase 8a Read API Layer Tests.

Verifies:
1. Each endpoint returns real data matching direct raw SQL queries.
2. Pagination works correctly (limit, offset, item separation).
3. GET /claims/{claim_id} traceability matches the Phase 7 live traceability query exactly.
4. GET /dashboard/metrics returns numbers independently verifiable against raw COUNT/SUM queries.
5. Endpoints handle not-found cases (404) correctly.
6. Zero mutation: verifies table row counts before and after running the test suite.
"""

from decimal import Decimal
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.main import app
from app.core.database import SessionLocal


TABLES = [
    "shipments",
    "orders",
    "charges",
    "evidence",
    "reimbursements",
    "claims",
    "claim_evidence",
    "assessment_log",
]


@pytest.fixture(scope="module")
def client():
    """FastAPI TestClient for Phase 8a Read API endpoints."""
    return TestClient(app, headers={"X-Org-Id": "org_test_alpha"}, raise_server_exceptions=False)


@pytest.fixture(scope="module")
def db_session():
    """Direct SQLAlchemy session for independent verification queries scoped to org_test_alpha."""
    from app.core.database import set_org_context, reset_org_context
    session = SessionLocal()
    set_org_context(session, "org_test_alpha")
    try:
        yield session
    finally:
        reset_org_context(session)
        session.close()


@pytest.fixture(autouse=True)
def scope_db_session_to_org(db_session):
    """Enforce that db_session maintains org_test_alpha RLS context across test transactions."""
    from app.core.database import set_org_context
    set_org_context(db_session, "org_test_alpha")
    yield
    set_org_context(db_session, "org_test_alpha")


@pytest.fixture(scope="module", autouse=True)
def verify_zero_database_mutation(db_session):
    """
    Enforces that Phase 8a Read API is strictly read-only and additive.
    Captures exact row counts for all database tables before tests and
    asserts zero mutations after tests.
    """
    counts_before = {
        t: db_session.scalar(text(f"SELECT count(*) FROM {t}")) for t in TABLES
    }

    yield

    counts_after = {
        t: db_session.scalar(text(f"SELECT count(*) FROM {t}")) for t in TABLES
    }

    for t in TABLES:
        assert (
            counts_before[t] == counts_after[t]
        ), f"DATABASE MUTATION DETECTED in table '{t}': before={counts_before[t]}, after={counts_after[t]}"


# ==============================================================================
# 1. GET /charges Tests
# ==============================================================================
def test_get_charges_matches_raw_query(client, db_session):
    """Verify GET /charges returns records matching direct database join query."""
    resp = client.get("/charges?limit=1000&offset=0")
    assert resp.status_code == 200
    data = resp.json()

    raw_total = db_session.scalar(text("SELECT count(*) FROM charges"))
    assert data["total"] == raw_total
    assert len(data["items"]) == min(raw_total, 1000)

    # Raw query for latest claim and charge details
    raw_query = text(
        """
        WITH ranked_claims AS (
            SELECT
                claim_id,
                charge_id,
                status,
                ROW_NUMBER() OVER (PARTITION BY charge_id ORDER BY created_at DESC, id DESC) as rn
            FROM claims
        )
        SELECT
            ch.charge_id,
            s.shipment_id,
            o.order_id,
            ch.sku,
            ch.asin,
            ch.charge_type,
            ch.amount,
            ch.currency,
            ch.status,
            rc.status AS latest_claim_status,
            rc.claim_id AS latest_claim_id
        FROM charges ch
        LEFT JOIN shipments s ON ch.shipment_id = s.id
        LEFT JOIN orders o ON ch.order_id = o.id
        LEFT JOIN ranked_claims rc ON rc.charge_id = ch.id AND rc.rn = 1
        ORDER BY ch.charge_date DESC, ch.created_at DESC;
        """
    )
    raw_rows = {r["charge_id"]: dict(r) for r in db_session.execute(raw_query).mappings().all()}

    for item in data["items"]:
        cid = item["charge_id"]
        assert cid in raw_rows
        raw = raw_rows[cid]
        assert item["shipment_id"] == raw["shipment_id"]
        assert item["order_id"] == raw["order_id"]
        assert item["sku"] == raw["sku"]
        assert item["asin"] == raw["asin"]
        assert item["charge_type"] == raw["charge_type"]
        assert Decimal(str(item["amount"])) == raw["amount"]
        assert item["currency"] == raw["currency"]
        assert item["status"] == raw["status"]
        assert item["latest_claim_status"] == raw["latest_claim_status"]
        assert item["latest_claim_id"] == raw["latest_claim_id"]


def test_get_charges_pagination(client, db_session):
    """Verify limit and offset pagination on GET /charges."""
    raw_total = db_session.scalar(text("SELECT count(*) FROM charges"))
    if raw_total < 2:
        pytest.skip("Need at least 2 charges for pagination test.")

    resp_page1 = client.get("/charges?limit=2&offset=0")
    assert resp_page1.status_code == 200
    data_page1 = resp_page1.json()
    assert len(data_page1["items"]) == 2
    assert data_page1["total"] == raw_total

    resp_page2 = client.get("/charges?limit=2&offset=2")
    assert resp_page2.status_code == 200
    data_page2 = resp_page2.json()

    # Ensure no overlap between page 1 and page 2 items
    page1_ids = {item["charge_id"] for item in data_page1["items"]}
    page2_ids = {item["charge_id"] for item in data_page2["items"]}
    assert not page1_ids.intersection(page2_ids)


def test_get_charges_filter_by_status(client, db_session):
    """Verify status query parameter filter on GET /charges."""
    for st in ("PROCESSED", "PENDING"):
        resp = client.get(f"/charges?status={st}")
        assert resp.status_code == 200
        data = resp.json()
        raw_count = db_session.scalar(text(f"SELECT count(*) FROM charges WHERE status = '{st}'"))
        assert data["total"] == raw_count
        for item in data["items"]:
            assert item["status"] == st


# ==============================================================================
# 2. GET /charges/{charge_id} Tests
# ==============================================================================
def test_get_charge_detail_with_claim(client, db_session):
    """Verify GET /charges/{charge_id} for a charge that has an associated claim."""
    # CHG-FBA-8902 is associated with CLM-10092 in seed data
    resp = client.get("/charges/CHG-FBA-8902")
    assert resp.status_code == 200
    data = resp.json()

    assert data["charge_id"] == "CHG-FBA-8902"
    assert data["shipment_id"] == "FBA17Z88Y13"
    assert data["order_id"] == "111-2000001-0000002"
    assert Decimal(str(data["amount"])) == Decimal("45.50")
    assert data["status"] == "PROCESSED"
    assert data["claim"] is not None
    assert data["claim"]["claim_id"] == "CLM-10092"
    assert data["claim"]["assessment"] == "CONTRADICTED"
    assert len(data["claim"]["evidence"]) == 1
    assert data["claim"]["evidence"][0]["evidence_id"] == "EVD-SCALE-4412"
    assert "CLM-10092" in data["claim_status_explanation"]
    assert data["evidence_retrieval_persisted"] is True
    assert "assessment_log" in data["persistence_notes"]


def test_get_charge_detail_non_claim_surfaces_assessment_log(client):
    """Verify GET /charges/{charge_id} for a charge evaluated as non-claim surfaces assessment_log."""
    resp = client.get("/charges/CHG-FBA-8901")
    assert resp.status_code == 200
    data = resp.json()

    assert data["charge_id"] == "CHG-FBA-8901"
    assert data["claim"] is None
    assert "SUPPORTED" in data["claim_status_explanation"]
    assert data["evidence_retrieval_persisted"] is False


def test_get_charge_detail_not_found(client):
    """Verify 404 response for non-existent charge_id."""
    resp = client.get("/charges/CHG-GHOST-UNKNOWN-999")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ==============================================================================
# 3. GET /charges/pending-review Tests
# ==============================================================================
def test_get_charges_pending_review(client, db_session):
    """Verify GET /charges/pending-review returns charges with UNCERTAIN assessments from assessment_log."""
    resp = client.get("/charges/pending-review")
    assert resp.status_code == 200
    data = resp.json()

    raw_uncertain_count = db_session.scalar(
        text(
            "SELECT count(DISTINCT al.charge_id) FROM assessment_log al "
            "WHERE al.assessment = 'UNCERTAIN' "
            "AND NOT EXISTS (SELECT 1 FROM claims c WHERE c.charge_id = al.charge_id)"
        )
    )
    assert data["total"] == raw_uncertain_count
    assert data["persistence_gap_notice"] is None

    for item in data["items"]:
        # Verify the charge in DB is indeed linked to an UNCERTAIN assessment in assessment_log
        raw_assessment = db_session.scalar(
            text(
                f"SELECT assessment FROM assessment_log WHERE charge_id = (SELECT id FROM charges WHERE charge_id = '{item['charge_id']}')"
            )
        )
        assert raw_assessment == "UNCERTAIN"
        assert item["latest_claim_id"] is None
        assert item["latest_claim_status"] is None


# ==============================================================================
# 4. GET /claims Tests
# ==============================================================================
def test_get_claims_matches_raw_query(client, db_session):
    """Verify GET /claims returns records matching direct database query."""
    resp = client.get("/claims?limit=100&offset=0")
    assert resp.status_code == 200
    data = resp.json()

    raw_total = db_session.scalar(text("SELECT count(*) FROM claims"))
    assert data["total"] == raw_total
    assert len(data["items"]) == raw_total

    raw_query = text(
        """
        SELECT
            c.claim_id,
            ch.charge_id,
            c.assessment,
            c.claim_amount,
            c.status,
            c.confidence,
            c.source_manager
        FROM claims c
        JOIN charges ch ON c.charge_id = ch.id
        ORDER BY c.created_at DESC, c.id DESC;
        """
    )
    raw_claims = {r["claim_id"]: dict(r) for r in db_session.execute(raw_query).mappings().all()}

    for item in data["items"]:
        cid = item["claim_id"]
        assert cid in raw_claims
        raw = raw_claims[cid]
        assert item["charge_id"] == raw["charge_id"]
        assert item["assessment"] == raw["assessment"]
        assert item["status"] == raw["status"]
        if raw["claim_amount"] is not None:
            assert Decimal(str(item["claim_amount"])) == raw["claim_amount"]
        else:
            assert item["claim_amount"] is None


def test_get_claims_filter_by_status(client, db_session):
    """Verify filtering claims by status query parameter."""
    for st in ("READY_FOR_REVIEW", "REJECTED"):
        resp = client.get(f"/claims?status={st}")
        assert resp.status_code == 200
        data = resp.json()
        raw_count = db_session.scalar(text(f"SELECT count(*) FROM claims WHERE status = '{st}'"))
        assert data["total"] == raw_count
        for item in data["items"]:
            assert item["status"] == st


def test_get_claims_pagination(client, db_session):
    """Verify limit and offset pagination on GET /claims."""
    import uuid

    raw_total = db_session.scalar(text("SELECT count(*) FROM claims"))
    temp_claim_uuid = uuid.uuid4()
    created_temp = False

    if raw_total < 2:
        # Programmatically ensure at least 2 claims exist for pagination test
        db_session.execute(
            text(
                "INSERT INTO claims (id, claim_id, org_id, charge_id, assessment, claim_amount, status, data_origin, created_at) "
                "VALUES (:id, 'CLM-TEMP-PAGINATE', 'org_test_alpha', 'c0000000-0000-0000-0000-000000000001', 'CONTRADICTED', 10.00, 'READY_FOR_REVIEW', 'test', now())"
            ),
            {"id": str(temp_claim_uuid)},
        )
        db_session.commit()
        created_temp = True

    try:
        resp1 = client.get("/claims?limit=1&offset=0")
        resp2 = client.get("/claims?limit=1&offset=1")
        assert resp1.status_code == 200
        assert resp2.status_code == 200

        items1 = resp1.json()["items"]
        items2 = resp2.json()["items"]
        assert len(items1) >= 1
        assert len(items2) >= 1
        assert items1[0]["claim_id"] != items2[0]["claim_id"]
    finally:
        if created_temp:
            db_session.execute(text("DELETE FROM claims WHERE org_id LIKE 'org_test_%'"))
            db_session.commit()


# ==============================================================================
# 5. GET /claims/{claim_id} Traceability Tests
# ==============================================================================
def test_get_claim_traceability_matches_phase7_query(client, db_session):
    """
    Verify GET /claims/{claim_id} returns exact end-to-end traceability
    matching the Phase 7-verified live query on CLM-10092.
    """
    phase7_query = text(
        """
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
    )
    raw_row = dict(db_session.execute(phase7_query).mappings().first())

    resp = client.get("/claims/CLM-10092")
    assert resp.status_code == 200
    data = resp.json()

    assert data["claim_id"] == raw_row["claim_id"]
    assert data["charge_id"] == raw_row["charge_id"]
    assert data["shipment_id"] == raw_row["shipment_id"]
    assert data["order_id"] == raw_row["order_id"]
    assert data["sku"] == raw_row["sku"]
    assert len(data["evidence"]) == 1
    assert data["evidence"][0]["evidence_id"] == raw_row["evidence_id"]
    assert data["evidence"][0]["source_manager"] == raw_row["source_manager"]


def test_get_claim_traceability_multi_evidence(client, db_session):
    """
    Verify GET /claims/{claim_id} returns all linked evidence items when a claim
    joins 2+ distinct evidence rows (e.g. from Prep and Receiving managers).
    Constructed programmatically and cleaned up cleanly with targeted DELETEs.
    """
    import uuid

    charge_uuid = uuid.uuid4()
    evd1_uuid = uuid.uuid4()
    evd2_uuid = uuid.uuid4()
    claim_uuid = uuid.uuid4()
    ce1_uuid = uuid.uuid4()
    ce2_uuid = uuid.uuid4()

    test_charge_id = "CHG-TEST-MULTI-EV"
    test_claim_id = "CLM-TEST-MULTI-EV"
    test_evd1_id = "EVD-PREP-MULTI-01"
    test_evd2_id = "EVD-RECV-MULTI-02"

    # Pre-test count baseline
    pre_counts = {
        table: db_session.scalar(text(f"SELECT count(*) FROM {table}"))
        for table in ("charges", "evidence", "claims", "claim_evidence")
    }

    try:
        # 1. Create a new test charge
        db_session.execute(
            text(
                "INSERT INTO charges (id, charge_id, org_id, shipment_id, order_id, sku, asin, "
                "charge_type, amount, currency, charge_date, source_report, status, data_origin, created_at) "
                "VALUES (:id, :cid, 'org_test_alpha', 'a0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', "
                "'TECH-CABLE-01', 'B08N5WRWNW', 'inbound_defect_fee', 85.00, 'USD', "
                "'2026-03-08 10:00:00+00', 'audit_report.csv', 'PROCESSED', 'test', now())"
            ),
            {"id": str(charge_uuid), "cid": test_charge_id},
        )
        # 2. Create 2 distinct evidence rows from different managers (Prep and Receiving)
        db_session.execute(
            text(
                "INSERT INTO evidence (id, evidence_id, org_id, shipment_id, order_id, sku, asin, "
                "source_manager, evidence_type, evidence_content, evidence_timestamp, data_origin, created_at) "
                "VALUES (:id, :eid, 'org_test_alpha', 'a0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', "
                "'TECH-CABLE-01', 'B08N5WRWNW', 'Prep', 'packaging_inspection', "
                "'{\"inspection\": \"passed\", \"prep_verified\": true}'::jsonb, '2026-03-08 09:30:00+00', 'test', now())"
            ),
            {"id": str(evd1_uuid), "eid": test_evd1_id},
        )
        db_session.execute(
            text(
                "INSERT INTO evidence (id, evidence_id, org_id, shipment_id, order_id, sku, asin, "
                "source_manager, evidence_type, evidence_content, evidence_timestamp, data_origin, created_at) "
                "VALUES (:id, :eid, 'org_test_alpha', 'a0000000-0000-0000-0000-000000000001', 'b0000000-0000-0000-0000-000000000001', "
                "'TECH-CABLE-01', 'B08N5WRWNW', 'Receiving', 'dock_weight_log', "
                "'{\"dock\": \"D-04\", \"verified\": true}'::jsonb, '2026-03-08 09:45:00+00', 'test', now())"
            ),
            {"id": str(evd2_uuid), "eid": test_evd2_id},
        )
        # 3. Create a claims row for that charge
        db_session.execute(
            text(
                "INSERT INTO claims (id, claim_id, org_id, charge_id, assessment, claim_amount, confidence, "
                "explanation, status, source_manager, data_origin, created_at) "
                "VALUES (:id, :cid, 'org_test_alpha', :charge_id, 'CONTRADICTED', 85.00, 0.9500, "
                "'Multi-evidence operational confirmation from Prep and Receiving.', 'READY_FOR_REVIEW', 'Inbound Ops', 'test', now())"
            ),
            {"id": str(claim_uuid), "cid": test_claim_id, "charge_id": str(charge_uuid)},
        )
        # 4. Create 2 claim_evidence junction rows linking the claim to both evidence rows
        db_session.execute(
            text(
                "INSERT INTO claim_evidence (id, claim_id, evidence_id, org_id, created_at) VALUES "
                "(:ce1, :cid, :e1, 'org_test_alpha', now()), (:ce2, :cid, :e2, 'org_test_alpha', now())"
            ),
            {
                "ce1": str(ce1_uuid),
                "ce2": str(ce2_uuid),
                "cid": str(claim_uuid),
                "e1": str(evd1_uuid),
                "e2": str(evd2_uuid),
            },
        )
        db_session.commit()

        # 5. Call GET /claims/{claim_id}
        resp = client.get(f"/claims/{test_claim_id}")
        assert resp.status_code == 200
        data = resp.json()

        assert data["claim_id"] == test_claim_id
        assert data["charge_id"] == test_charge_id
        assert len(data["evidence"]) == 2

        evidence_ids = {e["evidence_id"] for e in data["evidence"]}
        assert evidence_ids == {test_evd1_id, test_evd2_id}

        source_managers = {e["source_manager"] for e in data["evidence"]}
        assert source_managers == {"Prep", "Receiving"}

    finally:
        # Scoped targeted cleanup in reverse foreign-key order
        db_session.execute(
            text("DELETE FROM claim_evidence WHERE org_id LIKE 'org_test_%'"),
        )
        db_session.execute(
            text("DELETE FROM claims WHERE org_id LIKE 'org_test_%'"),
        )
        db_session.execute(
            text("DELETE FROM evidence WHERE org_id LIKE 'org_test_%'"),
        )
        db_session.execute(
            text("DELETE FROM charges WHERE org_id LIKE 'org_test_%'"),
        )
        db_session.commit()
        from app.core.database import set_org_context
        set_org_context(db_session, "org_test_alpha")

        # Verify zero leakage
        post_counts = {
            table: db_session.scalar(text(f"SELECT count(*) FROM {table}"))
            for table in ("charges", "evidence", "claims", "claim_evidence")
        }
        assert post_counts == pre_counts


def test_get_claim_not_found(client):
    """Verify 404 response for non-existent claim_id."""
    resp = client.get("/claims/CLM-NONEXISTENT-999")
    assert resp.status_code == 404
    assert "not found" in resp.json()["detail"].lower()


# ==============================================================================
# 6. GET /evidence Tests
# ==============================================================================
def test_get_evidence_matches_raw_query(client, db_session):
    """Verify GET /evidence returns records matching database query."""
    resp = client.get("/evidence?limit=100&offset=0")
    assert resp.status_code == 200
    data = resp.json()

    raw_total = db_session.scalar(text("SELECT count(*) FROM evidence"))
    assert data["total"] == raw_total
    assert len(data["items"]) == min(100, raw_total)

    raw_query = text(
        """
        SELECT
            e.evidence_id,
            e.source_manager,
            s.shipment_id,
            o.order_id,
            e.sku,
            e.asin,
            e.evidence_type
        FROM evidence e
        LEFT JOIN shipments s ON e.shipment_id = s.id
        LEFT JOIN orders o ON e.order_id = o.id
        ORDER BY e.evidence_timestamp DESC, e.created_at DESC;
        """
    )
    raw_ev = {r["evidence_id"]: dict(r) for r in db_session.execute(raw_query).mappings().all()}

    for item in data["items"]:
        eid = item["evidence_id"]
        assert eid in raw_ev
        raw = raw_ev[eid]
        assert item["source_manager"] == raw["source_manager"]
        assert item["shipment_id"] == raw["shipment_id"]
        assert item["order_id"] == raw["order_id"]
        assert item["sku"] == raw["sku"]
        assert item["asin"] == raw["asin"]
        assert item["evidence_type"] == raw["evidence_type"]


def test_get_evidence_filters(client, db_session):
    """Verify filters on GET /evidence: source_manager, shipment_id, order_id."""
    # 1. Filter by source_manager
    resp = client.get("/evidence?source_manager=Prep")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    for it in data["items"]:
        assert it["source_manager"] == "Prep"

    # 2. Filter by shipment_id
    resp = client.get("/evidence?shipment_id=FBA17Z88Y12")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    for it in data["items"]:
        assert it["shipment_id"] == "FBA17Z88Y12"

    # 3. Filter by order_id
    resp = client.get("/evidence?order_id=111-2000001-0000001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 1
    for it in data["items"]:
        assert it["order_id"] == "111-2000001-0000001"


# ==============================================================================
# 7. GET /dashboard/metrics Tests
# ==============================================================================
def test_get_dashboard_metrics_matches_independent_queries(client, db_session):
    """
    Verify GET /dashboard/metrics numbers match independent raw COUNT and SUM queries.
    Never hardcoded or estimated.
    """
    resp = client.get("/dashboard/metrics")
    assert resp.status_code == 200
    data = resp.json()

    # Raw counts
    raw_total_charges = db_session.scalar(text("SELECT count(*) FROM charges"))
    raw_total_claims = db_session.scalar(text("SELECT count(*) FROM claims"))
    raw_potential_recovery = db_session.scalar(
        text("SELECT COALESCE(SUM(claim_amount), 0.00) FROM claims WHERE status = 'READY_FOR_REVIEW' AND assessment = 'CONTRADICTED'")
    )

    assert data["total_charges"] == raw_total_charges
    assert data["total_claims"] == raw_total_claims
    assert Decimal(str(data["total_potential_recovery"])) == Decimal(str(raw_potential_recovery))

    # Evaluations by assessment type computed from assessment_log (only genuine AI evaluations where confidence IS NOT NULL)
    raw_assessments = dict(
        db_session.execute(text("SELECT assessment, count(*) FROM assessment_log WHERE confidence IS NOT NULL GROUP BY assessment")).all()
    )
    for outcome in ("SUPPORTED", "CONTRADICTED", "SILENT", "UNCERTAIN"):
        expected_cnt = raw_assessments.get(outcome, 0)
        assert data["claims_by_assessment"][outcome] == expected_cnt

    # Claims by status
    raw_statuses = dict(
        db_session.execute(text("SELECT status, count(*) FROM claims GROUP BY status")).all()
    )
    for st in ("READY_FOR_REVIEW", "DUPLICATE", "ALREADY_REIMBURSED", "REJECTED", "APPROVED"):
        expected_cnt = raw_statuses.get(st, 0)
        assert data["claims_by_status"][st] == expected_cnt

    # Unprocessed charges count (never evaluated - no assessment_log row)
    raw_unprocessed = db_session.scalar(
        text(
            "SELECT count(*) FROM charges ch WHERE NOT EXISTS (SELECT 1 FROM assessment_log al WHERE al.charge_id = ch.id)"
        )
    )
    assert data["unprocessed_charges_count"] == raw_unprocessed

    # Processed no-claim charges count (evaluated in assessment_log but no claims row)
    raw_processed_no_claim = db_session.scalar(
        text(
            "SELECT count(*) FROM charges ch WHERE EXISTS (SELECT 1 FROM assessment_log al WHERE al.charge_id = ch.id) AND NOT EXISTS (SELECT 1 FROM claims c WHERE c.charge_id = ch.id)"
        )
    )
    assert data["processed_no_claim_charges_count"] == raw_processed_no_claim

    # Persistence gap disclosure is null now that assessment_log is active
    assert data["persistence_gap_notice"] is None

