import sys
import json
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent.parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.core.database import SessionLocal
from app.models.charge import Charge
from app.models.claim import Claim
from app.models.evidence import Evidence
from app.models.assessment_log import AssessmentLog
from app.services.evidence_engine import evidence_engine
from sqlalchemy import select, or_

session = SessionLocal()
target_cids = [
    "CHG-FBA-8901",
    "CHG-FBA-8902",
    "CHG-FBA-8903",
    "CHG-FBA-8904",
    "FEE-0002-1",
    "FEE-0003-1",
    "FEE-0003-2",
    "FEE-0005-1",
    "FEE-0007-1",
    "FEE-0011-1",
    "FEE-0012-1",
    "FEE-0013-1",
    "FEE-0014-1",
    "FEE-0014-2",
    "FEE-0014-3",
]

print("=== INSPECTING CANDIDATE CHARGES FOR EVAL SET ===")
for cid in target_cids:
    chg = evidence_engine.find_charge(cid, session)
    if not chg:
        print(f"Charge {cid} NOT FOUND")
        continue

    # Retrieve candidate evidence
    ev_list = evidence_engine.get_evidence_for_charge(cid, session)
    claim = session.scalars(select(Claim).where(Claim.charge_id == chg.id)).first()
    log = session.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == chg.id)).first()

    print(f"\n--- {cid} ---")
    print(f"Type: {chg.charge_type} | Amount: {chg.amount} {chg.currency} | Status: {chg.status}")
    print(f"Identifiers: unit_id={chg.unit_id}, fnsku={chg.fnsku}, sku={chg.sku}, shipment={chg.shipment_id}")
    print(f"Existing Claim: {claim.claim_id if claim else 'None'} ({claim.status if claim else ''})")
    print(f"Existing Log: {log.assessment if log else 'None'} - {log.reason if log else ''}")
    records = ev_list.evidence_records if hasattr(ev_list, "evidence_records") else []
    print(f"Retrieved Evidence Count: {len(records)}")
    for ev in records:
        print(f"   [EV] {ev.evidence_id} ({ev.evidence_type} from {ev.source_manager}): {json.dumps(ev.evidence_content)[:120]}")

session.close()
