"""Permanent RLS Isolation Tests -- Tier 0 Item 2.

PLAIN STATEMENT about standard pytest RLS context:
All other test files in this repo use SessionLocal() which connects as
the postgres superuser (rolbypassrls=True). Without calling set_org_context,
those sessions bypass RLS entirely. This file uses set_org_context to run
under role authenticated (rolbypassrls=False) and proves cross-tenant isolation.
"""
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

import pytest
from sqlalchemy import select, text

backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.database import SessionLocal, set_org_context
from app.models.charge import Charge
from app.models.shipment import Shipment

ALPHA_CHARGE_ID = "CHG-RLS-ALPHA-001"
BRAVO_CHARGE_ID = "CHG-RLS-BRAVO-001"


def make_rls_session(org_id: str):
    session = SessionLocal()
    set_org_context(session, org_id)
    return session


@pytest.fixture(scope="module", autouse=True)
def setup_rls_test_data():
    db = SessionLocal()
    try:
        db.execute(text("RESET ROLE; RESET app.current_org;"))
        db.commit()
        for ship_id, org in [("SHP-RLS-ALPHA", "org_test_alpha"), ("SHP-RLS-BRAVO", "org_test_bravo")]:
            existing = db.execute(select(Shipment.id).where(Shipment.shipment_id == ship_id)).scalar_one_or_none()
            if not existing:
                db.add(Shipment(shipment_id=ship_id, org_id=org))
        db.execute(text("DELETE FROM charges WHERE org_id LIKE 'org_test_%'"))
        db.flush()
        alpha = Charge(
            charge_id=ALPHA_CHARGE_ID, org_id="org_test_alpha",
            charge_type="inbound_defect_fee", report_type="fee_report",
            amount=Decimal("50.00"), currency="USD",
            charge_date=datetime(2026, 1, 15, tzinfo=timezone.utc),
            status="PENDING", raw_data={},
        )
        bravo = Charge(
            charge_id=BRAVO_CHARGE_ID, org_id="org_test_bravo",
            charge_type="lost_inbound", report_type="fee_report",
            amount=Decimal("75.00"), currency="USD",
            charge_date=datetime(2026, 1, 16, tzinfo=timezone.utc),
            status="PENDING", raw_data={},
        )
        db.add(alpha)
        db.add(bravo)
        db.commit()
        db.refresh(alpha)
        db.refresh(bravo)
        setup_rls_test_data.alpha_uuid = alpha.id
        setup_rls_test_data.bravo_uuid = bravo.id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    yield
    cleanup = SessionLocal()
    try:
        cleanup.execute(text("DELETE FROM charges WHERE org_id LIKE 'org_test_%'"))
        cleanup.commit()
    except Exception:
        cleanup.rollback()
    finally:
        cleanup.close()


def test_rls_alpha_sees_own_charge():
    """org_test_alpha session sees its own charge."""
    db = make_rls_session("org_test_alpha")
    try:
        row = db.execute(select(Charge).where(Charge.charge_id == ALPHA_CHARGE_ID)).scalars().first()
        assert row is not None, "RLS FAIL: alpha cannot see own charge"
        assert row.org_id == "org_test_alpha"
        assert row.amount == Decimal("50.00")
    finally:
        db.close()


def test_rls_alpha_cannot_see_bravo_charge():
    """org_test_alpha session sees zero rows for bravo charge_id."""
    db = make_rls_session("org_test_alpha")
    try:
        row = db.execute(select(Charge).where(Charge.charge_id == BRAVO_CHARGE_ID)).scalars().first()
        assert row is None, "RLS FAIL: alpha can read bravo charge by charge_id -- isolation BROKEN"
    finally:
        db.close()


def test_rls_alpha_cannot_fetch_bravo_uuid():
    """org_test_alpha session cannot fetch bravo row by UUID primary key."""
    bravo_uuid = setup_rls_test_data.bravo_uuid
    db = make_rls_session("org_test_alpha")
    try:
        row = db.execute(select(Charge).where(Charge.id == bravo_uuid)).scalars().first()
        assert row is None, f"RLS FAIL: alpha fetched bravo by UUID {bravo_uuid} -- PK-level isolation BROKEN"
    finally:
        db.close()


def test_rls_bravo_sees_own_charge():
    """org_test_bravo session sees its own charge."""
    db = make_rls_session("org_test_bravo")
    try:
        row = db.execute(select(Charge).where(Charge.charge_id == BRAVO_CHARGE_ID)).scalars().first()
        assert row is not None, "RLS FAIL: bravo cannot see own charge"
        assert row.org_id == "org_test_bravo"
        assert row.amount == Decimal("75.00")
    finally:
        db.close()


def test_rls_bravo_cannot_see_alpha_charge():
    """org_test_bravo session sees zero rows for alpha charge_id."""
    db = make_rls_session("org_test_bravo")
    try:
        row = db.execute(select(Charge).where(Charge.charge_id == ALPHA_CHARGE_ID)).scalars().first()
        assert row is None, "RLS FAIL: bravo can read alpha charge by charge_id -- isolation BROKEN"
    finally:
        db.close()


def test_rls_bravo_cannot_fetch_alpha_uuid():
    """org_test_bravo session cannot fetch alpha row by UUID."""
    alpha_uuid = setup_rls_test_data.alpha_uuid
    db = make_rls_session("org_test_bravo")
    try:
        row = db.execute(select(Charge).where(Charge.id == alpha_uuid)).scalars().first()
        assert row is None, f"RLS FAIL: bravo fetched alpha by UUID {alpha_uuid} -- PK-level isolation BROKEN"
    finally:
        db.close()


def test_superuser_bypass_sees_both_rows():
    """
    Control: postgres superuser bypasses RLS and sees both orgs.
    This is EXACTLY what happens in all other pytest files that use
    SessionLocal() without set_org_context -- they run as superuser bypass.
    """
    db = SessionLocal()
    try:
        alpha = db.execute(select(Charge).where(Charge.charge_id == ALPHA_CHARGE_ID)).scalars().first()
        bravo = db.execute(select(Charge).where(Charge.charge_id == BRAVO_CHARGE_ID)).scalars().first()
        assert alpha is not None, "Superuser should see alpha"
        assert bravo is not None, "Superuser should see bravo"
    finally:
        db.close()


def test_rls_no_header_denies_cross_org_and_returns_zero_rows():
    """
    Tier 0 Verification: When no org context is supplied (org_id is None or empty),
    set_org_context enforces role 'authenticated' with a non-matching sentinel org.
    Proves that missing org context defaults to DENY (zero rows returned),
    never leaking alpha or bravo data.
    """
    db = make_rls_session(None)
    try:
        alpha = db.execute(select(Charge).where(Charge.charge_id == ALPHA_CHARGE_ID)).scalars().first()
        bravo = db.execute(select(Charge).where(Charge.charge_id == BRAVO_CHARGE_ID)).scalars().first()
        all_charges = db.execute(select(Charge)).scalars().all()
        assert alpha is None, "RLS FAIL: session without org context saw alpha charge -- DENY failed"
        assert bravo is None, "RLS FAIL: session without org context saw bravo charge -- DENY failed"
        assert len(all_charges) == 0, f"RLS FAIL: session without org context returned {len(all_charges)} charges -- DENY failed"
    finally:
        db.close()


def test_rls_api_no_header_returns_zero_charges():
    """
    API Test: Issuing a real GET /charges request with NO X-Org-Id header at all
    must invoke get_db() under default DENY and return 0 items -- NOT cross-org data.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get("/charges")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0, f"Expected 0 total charges without X-Org-Id, got {data['total']}"
    assert len(data["items"]) == 0, f"Expected 0 items without X-Org-Id, got {len(data['items'])}"

