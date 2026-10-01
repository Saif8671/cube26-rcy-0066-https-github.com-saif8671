import sys
sys.path.insert(0, 'backend')
from app.core.database import SessionLocal
from sqlalchemy import text

session = SessionLocal()
tables = ['charges', 'shipments', 'orders', 'evidence', 'claims', 'claim_evidence', 'assessment_logs']
print('=== BEFORE DB ROW COUNTS ===')
for t in tables:
    try:
        count = session.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        print(f"{t}: {count}")
    except Exception as e:
        session.rollback()
        print(f"{t}: error ({e})")
session.close()
