"""Apply the approved provenance labels in one transaction and print raw evidence.

This script deliberately does not touch any source/report columns or delete rows.
Run only after setting the intended DATABASE_URL explicitly.
"""

from sqlalchemy import text

from app.core.database import engine

LABELS = {
    "evidence": ("evidence_id", ["EVD-RECV-3301", "EVD-SCALE-4412", "EVD-PREP-8821", "EVD-PACK-9102"]),
    "charges": ("charge_id", ["CHG-FBA-8901", "CHG-FBA-8902", "CHG-FBA-8903", "CHG-FBA-8904"]),
    "reimbursements": ("reimbursement_id", ["RMB-AMZ-7711", "RMB-AMZ-7712", "RMB-AMZ-7713"]),
    "claims": ("claim_id", ["CLM-10092"]),
}
TEST_CHARGES = ["CHG-UPLOAD-DEMO-01", "CHG-UPLOAD-DEMO-02", "CHG-VALID-ROW"]


def _print_rows(connection, label):
    print(f"BEFORE {label}")
    for table, (column, ids) in LABELS.items():
        rows = connection.execute(
            text(f"SELECT id, {column}, org_id, data_origin FROM {table} WHERE {column} = ANY(:ids) ORDER BY {column}"),
            {"ids": ids},
        ).mappings().all()
        for row in rows:
            print(dict(row))
    rows = connection.execute(
        text("SELECT id, charge_id, org_id, data_origin FROM charges WHERE charge_id = ANY(:ids) ORDER BY charge_id"),
        {"ids": TEST_CHARGES},
    ).mappings().all()
    for row in rows:
        print(dict(row))


with engine.begin() as connection:
    _print_rows(connection, "approved ids")
    for table, (column, ids) in LABELS.items():
        connection.execute(text(f"UPDATE {table} SET data_origin = 'seed_example' WHERE {column} = ANY(:ids)"), {"ids": ids})
    connection.execute(text("UPDATE charges SET data_origin = 'test' WHERE charge_id = ANY(:ids)"), {"ids": TEST_CHARGES})

    operator_claim = connection.execute(text("""
        SELECT c.id, c.claim_id, c.created_at,
               CASE WHEN EXISTS (
                   SELECT 1 FROM information_schema.columns
                   WHERE table_name = 'claims' AND column_name = 'created_by'
               ) THEN NULL ELSE NULL END AS created_by
        FROM claims c
        JOIN overrides o ON o.claim_id = c.id
        WHERE o.reviewer_id = 'operator'
        ORDER BY c.created_at DESC, c.id DESC
        LIMIT 1
    """)).mappings().first()
    if operator_claim:
        print("OPERATOR_OVERRIDE_CLAIM", dict(operator_claim))
        links = connection.execute(text("""
            SELECT ce.id, ce.claim_id, ce.evidence_id, e.evidence_id AS evidence_business_id
            FROM claim_evidence ce
            JOIN evidence e ON e.id = ce.evidence_id
            WHERE ce.claim_id = :claim_id ORDER BY ce.id
        """), {"claim_id": operator_claim["id"]}).mappings().all()
        print("OPERATOR_OVERRIDE_CLAIM_EVIDENCE", [dict(row) for row in links])
        connection.execute(text("UPDATE claims SET data_origin = 'unverified' WHERE id = :id"), {"id": operator_claim["id"]})
    else:
        print("OPERATOR_OVERRIDE_CLAIM NOT FOUND; no origin assigned")

    for table in ("charges", "evidence", "reimbursements", "claims"):
        rows = connection.execute(text(f"SELECT data_origin, count(*) AS n FROM {table} GROUP BY data_origin ORDER BY data_origin"))
        print(f"AFTER {table}", [dict(row._mapping) for row in rows])
