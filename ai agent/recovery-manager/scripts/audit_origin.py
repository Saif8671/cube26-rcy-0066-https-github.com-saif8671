from app.core.database import engine
from sqlalchemy import text

with engine.connect() as c:
    for table in ("charges", "evidence", "reimbursements", "claims"):
        print(table)
        for row in c.execute(text(f"SELECT * FROM {table} WHERE data_origin IS DISTINCT FROM 'judge_data' ORDER BY created_at")):
            print(dict(row._mapping))
    print("ALPHA_CHARGES")
    for row in c.execute(text("""
        SELECT charge_id, created_at, source_report, data_origin
        FROM charges WHERE org_id='org_demo_alpha' ORDER BY created_at, charge_id
    """)):
        print(dict(row._mapping))
    print("ALL_CLAIMS")
    for row in c.execute(text("SELECT claim_id, org_id, charge_id, assessment, explanation, created_at, data_origin FROM claims ORDER BY created_at, claim_id")):
        print(dict(row._mapping))
