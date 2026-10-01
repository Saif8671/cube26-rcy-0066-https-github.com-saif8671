from sqlalchemy import text
from app.core.database import engine
with engine.connect() as c:
    for t in ('shipments','orders','charges','evidence','reimbursements','claims','claim_evidence'):
        print(t)
        for r in c.execute(text(f"SELECT org_id, count(*) FROM {t} GROUP BY org_id ORDER BY org_id")):
            print(dict(r._mapping))
