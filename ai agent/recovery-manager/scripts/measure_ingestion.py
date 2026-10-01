import csv, time
from pathlib import Path
from sqlalchemy import event
from app.core.database import SessionLocal, set_org_context, reset_org_context, engine
from app.ingestion.service import ingestion_service

root = Path(__file__).resolve().parents[1]
with (root/'data/fee_report_sample.csv').open(newline='', encoding='utf-8') as f:
    records = [r for r in csv.DictReader(f) if r['org_id']=='org_demo_alpha'][:5]

count = {'n': 0}
def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    count['n'] += 1
event.listen(engine, 'before_cursor_execute', before_cursor_execute)
db = SessionLocal()
try:
    set_org_context(db, 'org_demo_alpha')
    t0 = time.perf_counter()
    result = ingestion_service.ingest_charges_records(records, db, source_report='measure_5.csv', auto_create_containers=True)
    elapsed = time.perf_counter() - t0
    print({'rows': len(records), 'seconds': round(elapsed, 4), 'sql_queries': count['n'], 'queries_per_row': round(count['n']/len(records), 2), 'result': result.to_dict()})
finally:
    reset_org_context(db)
    db.close()
    event.remove(engine, 'before_cursor_execute', before_cursor_execute)
