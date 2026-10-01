from sqlalchemy import text
from app.core.database import engine

with engine.connect() as c:
    backups = c.execute(text("""
        SELECT c.relname AS table_name, c.reltuples::bigint AS approx_rows
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        WHERE n.nspname='public' AND c.relname IN (
          'shipments_bak_pre005','orders_bak_pre005','charges_bak_pre005',
          'evidence_bak_pre005','reimbursements_bak_pre005','claims_bak_pre005',
          'claim_evidence_bak_pre005') ORDER BY c.relname
    """))
    print('BACKUPS')
    for row in backups:
        print(dict(row._mapping))
    constraints = c.execute(text("""
        SELECT conrelid::regclass AS table_name, conname,
               pg_get_constraintdef(oid) AS definition
        FROM pg_constraint
        WHERE conrelid::regclass::text IN
          ('shipments','orders','charges','evidence','reimbursements','claims')
          AND contype='u' ORDER BY 1,2
    """))
    print('CONSTRAINTS')
    for row in constraints:
        print(dict(row._mapping))
    print('EXACT_BACKUP_COUNTS')
    for name in ('shipments','orders','charges','evidence','reimbursements','claims','claim_evidence'):
        print(name, c.execute(text(f'SELECT count(*) FROM {name}_bak_pre005')).scalar_one())
    print('MIGRATION_TABLES')
    for row in c.execute(text("""
        SELECT table_schema, table_name
        FROM information_schema.tables
        WHERE table_name ILIKE '%migration%' ORDER BY 1,2
    """)):
        print(dict(row._mapping))
