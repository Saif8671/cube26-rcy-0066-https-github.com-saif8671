"""Read-only live checks required before migration 005."""

from sqlalchemy import text

from app.core.database import engine


TABLES = ("shipments", "orders", "charges", "evidence", "reimbursements", "claims")


with engine.connect() as connection:
    print("CONSTRAINTS")
    for row in connection.execute(text("""
        SELECT conrelid::regclass AS table_name, conname,
               pg_get_constraintdef(oid) AS definition
        FROM pg_constraint
        WHERE conrelid::regclass::text = ANY(:tables)
          AND contype = 'u'
        ORDER BY 1, 2
    """), {"tables": list(TABLES)}):
        print(dict(row._mapping))

    print("NULL_ORG_COUNTS")
    for table in TABLES:
        row = connection.execute(text(f"SELECT count(*) AS n FROM {table} WHERE org_id IS NULL")).one()
        print(table, row.n)

    print("DUPLICATE_ORG_TEXT_ID_GROUPS")
    for table, column in ((table, {"shipments": "shipment_id", "orders": "order_id", "charges": "charge_id", "evidence": "evidence_id", "reimbursements": "reimbursement_id", "claims": "claim_id"}[table]) for table in TABLES):
        rows = connection.execute(text(f"""
            SELECT org_id, {column} AS text_id, count(*) AS n
            FROM {table}
            GROUP BY org_id, {column}
            HAVING count(*) > 1
            ORDER BY org_id, text_id
        """)).all()
        print(table, [dict(row._mapping) for row in rows])

    print("POOL_STATUS")
    print(engine.pool.status())
    print("PG_STAT_ACTIVITY")
    for row in connection.execute(text("""
        SELECT state, count(*) AS n
        FROM pg_stat_activity
        WHERE usename LIKE 'postgres%'
        GROUP BY state
        ORDER BY state
    """)):
        print(dict(row._mapping))
