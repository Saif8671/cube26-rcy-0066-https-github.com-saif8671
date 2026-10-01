import sys, json, urllib.request
sys.path.insert(0, 'backend')
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import MagicMock
from app.core.database import SessionLocal
from app.models.charge import Charge
from app.models.shipment import Shipment
from app.models.order import Order
from app.models.reimbursement import Reimbursement
from app.models.claim import Claim
from app.models.assessment_log import AssessmentLog
from app.ai.service import AIService
from app.services.pipeline import process_charge_pipeline
from sqlalchemy import text

def run():
    s = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        shp = Shipment(shipment_id='SHP-LIVE-DASH-01')
        s.add(shp)
        s.flush()
        
        ord_rec = Order(order_id='ORD-LIVE-DASH-01')
        s.add(ord_rec)
        s.flush()
        
        chg = Charge(
            charge_id='CHG-LIVE-DASH-01',
            shipment_id=shp.id,
            order_id=ord_rec.id,
            sku='SKU-LIVE-DASH-01',
            asin='B00LIVEDASH1',
            charge_type='FBA Inbound Weight Discrepancy',
            amount=Decimal('50.00'),
            currency='USD',
            charge_date=now,
            status='PENDING',
        )
        s.add(chg)
        s.flush()

        reimb = Reimbursement(
            reimbursement_id='RMB-LIVE-DASH-01',
            charge_id=chg.id,
            amount=Decimal('50.00'),
            reimbursement_date=now,
            raw_data={'source': 'Carrier refund'}
        )
        s.add(reimb)
        s.flush()
        s.commit()
        print('=== FRESH CHARGE WITH LINKED REIMBURSEMENT CREATED ===')

        mock_ai = MagicMock(spec=AIService)
        mock_ai.assess_recovery.side_effect = RuntimeError("AI should not be called!")

        # Run pipeline
        res = process_charge_pipeline('CHG-LIVE-DASH-01', db=s, ai_service=mock_ai)
        print('Pipeline Result outcome:', res.outcome, 'status:', res.status)

        # Call live GET /dashboard/metrics
        with urllib.request.urlopen('http://localhost:8000/dashboard/metrics') as resp:
            metrics = json.loads(resp.read().decode('utf-8'))

        print('\n=== LIVE GET /dashboard/metrics RESPONSE ===')
        print(json.dumps(metrics, indent=2))

        # Teardown
        s.execute(text("DELETE FROM claim_evidence WHERE claim_id IN (SELECT id FROM claims WHERE charge_id = :cid)").params(cid=chg.id))
        s.execute(text("DELETE FROM claims WHERE charge_id = :cid").params(cid=chg.id))
        s.execute(text("DELETE FROM assessment_log WHERE charge_id = :cid").params(cid=chg.id))
        s.execute(text("DELETE FROM reimbursements WHERE id = :rid").params(rid=reimb.id))
        s.execute(text("DELETE FROM charges WHERE id = :cid").params(cid=chg.id))
        s.execute(text("DELETE FROM shipments WHERE id = :sid").params(sid=shp.id))
        s.execute(text("DELETE FROM orders WHERE id = :oid").params(oid=ord_rec.id))
        s.commit()
        print('\n=== CLEANUP COMPLETED ===')
    finally:
        s.close()

if __name__ == '__main__':
    run()
