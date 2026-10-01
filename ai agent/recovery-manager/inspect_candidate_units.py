import sys
import os
import json

backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "backend"))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

from app.core.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()
try:
    units = ['UNIT-0014', 'UNIT-0026', 'UNIT-0002', 'UNIT-0018', 'UNIT-0095', 'UNIT-0003']
    for u in units:
        print("=" * 80)
        print(f"UNIT: {u}")
        print("=" * 80)
        charges = db.execute(
            text("SELECT charge_id, charge_type, report_type, amount, org_id FROM charges WHERE unit_id = :u"),
            {"u": u}
        ).fetchall()
        print("CHARGES:")
        for c in charges:
            print(f"  {c[0]} | type={c[1]} | report_type={c[2]} | amount={c[3]} | org={c[4]}")
        
        evidence = db.execute(
            text("SELECT evidence_id, source_manager, evidence_type, evidence_content FROM evidence WHERE unit_id = :u"),
            {"u": u}
        ).fetchall()
        print("EVIDENCE:")
        for e in evidence:
            print(f"  {e[0]} | manager={e[1]} | type={e[2]}")
            content = e[3]
            if isinstance(content, dict):
                # Print relevant keys
                reqs = content.get("requirements", {})
                obs = content.get("observed", {})
                if reqs or obs:
                    print(f"    Requirements: {reqs}")
                    print(f"    Observed:     {obs}")
                else:
                    summary = {k: v for k, v in content.items() if k not in ("photo_refs", "raw_record")}
                    print(f"    Content: {summary}")
finally:
    db.close()
