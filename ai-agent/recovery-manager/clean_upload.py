import sys
sys.path.insert(0, 'backend')
from app.core.database import SessionLocal
from sqlalchemy import text

s = SessionLocal()
s.execute(text("DELETE FROM claim_evidence WHERE claim_id IN (SELECT id FROM claims WHERE charge_id IN (SELECT id FROM charges WHERE charge_id LIKE 'CHG-UPLOAD%'))"))
s.execute(text("DELETE FROM claims WHERE charge_id IN (SELECT id FROM charges WHERE charge_id LIKE 'CHG-UPLOAD%')"))
s.execute(text("DELETE FROM assessment_log WHERE charge_id IN (SELECT id FROM charges WHERE charge_id LIKE 'CHG-UPLOAD%')"))
s.execute(text("DELETE FROM charges WHERE charge_id LIKE 'CHG-UPLOAD%'"))
s.commit()
print("Cleaned up CHG-UPLOAD% charges.")
tables = ['charges', 'shipments', 'orders', 'evidence', 'reimbursements', 'claims', 'claim_evidence', 'assessment_log']
for t in tables:
    cnt = s.execute(text(f"SELECT COUNT(1) FROM {t}")).scalar()
    print(f"{t}: {cnt}")
s.close()
