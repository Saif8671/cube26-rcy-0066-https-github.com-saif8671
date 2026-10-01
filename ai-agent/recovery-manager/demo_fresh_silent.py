import sys, json
sys.path.insert(0, 'backend')
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import MagicMock
from app.core.database import SessionLocal
from app.models.charge import Charge
from app.models.shipment import Shipment
from app.models.order import Order
from app.models.claim import Claim
from app.models.assessment_log import AssessmentLog
from app.ai.service import AIService
from app.ai.client import AnthropicClient
from app.services.pipeline import process_charge_pipeline
from sqlalchemy import select, text

def run():
    s = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        shp = Shipment(shipment_id='SHP-DEMO-SILENT-01')
        s.add(shp)
        s.flush()
        
        ord_rec = Order(order_id='ORD-DEMO-SILENT-01')
        s.add(ord_rec)
        s.flush()
        
        chg = Charge(
            charge_id='CHG-DEMO-SILENT-01',
            shipment_id=shp.id,
            order_id=ord_rec.id,
            sku='SKU-DEMO-SILENT-01',
            asin='B00SILENT01',
            charge_type='Packaging defect - Missing label',
            amount=Decimal('40.00'),
            currency='USD',
            charge_date=now,
            status='PENDING',
        )
        s.add(chg)
        s.flush()
        s.commit()
        print('=== STEP 1: FRESH CHARGE WITH NO EVIDENCE CREATED ===')
        print(f"Charge ID: {chg.charge_id}, Amount: ${chg.amount}, Status: {chg.status}")

        mock_client = MagicMock(spec=AnthropicClient)
        mock_client.generate_assessment.return_value = json.dumps({
            'assessment': 'SILENT',
            'claim_supported': False,
            'claim_amount': None,
            'confidence': 0.0,
            'reason': 'No warehouse operational evidence or inspection records found for this charge.',
            'evidence_ids': []
        })
        mock_ai = AIService(client=mock_client)

        print('\n=== STEP 2: RUNNING PIPELINE E2E ===')
        res = process_charge_pipeline('CHG-DEMO-SILENT-01', db=s, ai_service=mock_ai)
        print('PIPELINE_RESULT:')
        print(res.model_dump_json(indent=2))

        claim_row = s.scalars(select(Claim).where(Claim.charge_id == chg.id)).first()
        log_row = s.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == chg.id)).first()
        updated_chg = s.scalars(select(Charge).where(Charge.id == chg.id)).first()

        print('\n=== STEP 3: DB ROWS CREATED / VERIFIED ===')
        print(f"Charge Updated Status: {updated_chg.status}")
        print(f"DB CLAIMS ROW (MUST BE NONE): {claim_row}")
        print('DB ASSESSMENT_LOG ROW:')
        print({
            'id': str(log_row.id),
            'charge_id': str(log_row.charge_id),
            'assessment': log_row.assessment,
            'claim_supported': log_row.claim_supported,
            'claim_amount': str(log_row.claim_amount) if log_row.claim_amount else None,
            'confidence': str(log_row.confidence),
            'reason': log_row.reason,
            'evidence_ids': log_row.evidence_ids
        } if log_row else None)

        # Clean up
        s.execute(text("DELETE FROM assessment_log WHERE charge_id = :cid").params(cid=chg.id))
        s.execute(text("DELETE FROM charges WHERE id = :cid").params(cid=chg.id))
        s.execute(text("DELETE FROM shipments WHERE id = :sid").params(sid=shp.id))
        s.execute(text("DELETE FROM orders WHERE id = :oid").params(oid=ord_rec.id))
        s.commit()
        print('\n=== STEP 4: CLEANUP COMPLETED SUCCESSFULLY ===')
    finally:
        s.close()

if __name__ == '__main__':
    run()
