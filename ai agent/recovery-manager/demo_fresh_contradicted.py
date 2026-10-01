import sys, json
sys.path.insert(0, 'backend')
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import MagicMock
from app.core.database import SessionLocal
from app.models.charge import Charge
from app.models.shipment import Shipment
from app.models.order import Order
from app.models.evidence import Evidence
from app.models.claim import Claim
from app.models.claim_evidence import ClaimEvidence
from app.models.assessment_log import AssessmentLog
from app.ai.service import AIService
from app.ai.client import AnthropicClient
from app.services.pipeline import process_charge_pipeline
from sqlalchemy import select, text

def run():
    s = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        shp = Shipment(shipment_id='SHP-DEMO-LIVE-01')
        s.add(shp)
        s.flush()
        
        ord_rec = Order(order_id='ORD-DEMO-LIVE-01')
        s.add(ord_rec)
        s.flush()
        
        chg = Charge(
            charge_id='CHG-DEMO-LIVE-01',
            shipment_id=shp.id,
            order_id=ord_rec.id,
            sku='SKU-DEMO-LIVE-01',
            asin='B00DEMO01',
            charge_type='FBA Inbound Weight Discrepancy',
            amount=Decimal('85.50'),
            currency='USD',
            charge_date=now,
            status='PENDING',
        )
        s.add(chg)
        s.flush()
        
        evd = Evidence(
            evidence_id='EVD-DEMO-LIVE-01',
            shipment_id=shp.id,
            order_id=ord_rec.id,
            sku='SKU-DEMO-LIVE-01',
            asin='B00DEMO01',
            source_manager='Receiving',
            evidence_type='WEIGHT_DIM_SCAN',
            evidence_timestamp=now,
            evidence_content={
                'discrepancy_found': True,
                'measured_weight_kg': 0.45,
                'carrier_claimed_weight_kg': 1.20,
                'scan_location': 'Dock Door 4'
            }
        )
        s.add(evd)
        s.flush()
        s.commit()
        print('=== STEP 1: FRESH CHARGE CREATED ===')
        print(f"Charge ID: {chg.charge_id}, Amount: ${chg.amount}, Status: {chg.status}")

        mock_client = MagicMock(spec=AnthropicClient)
        mock_client.generate_assessment.return_value = json.dumps({
            'assessment': 'CONTRADICTED',
            'claim_supported': True,
            'claim_amount': 85.50,
            'confidence': 0.96,
            'reason': 'Receiving weight scan verifies shipment weight was 0.45 kg, contradicting 1.20 kg billed.',
            'evidence_ids': ['EVD-DEMO-LIVE-01']
        })
        mock_ai = AIService(client=mock_client)

        print('\n=== STEP 2: RUNNING PIPELINE E2E ===')
        res = process_charge_pipeline('CHG-DEMO-LIVE-01', db=s, ai_service=mock_ai)
        print('PIPELINE_RESULT:')
        print(res.model_dump_json(indent=2))

        claim_row = s.scalars(select(Claim).where(Claim.charge_id == chg.id)).first()
        ce_rows = s.scalars(select(ClaimEvidence).where(ClaimEvidence.claim_id == claim_row.id)).all() if claim_row else []
        log_row = s.scalars(select(AssessmentLog).where(AssessmentLog.charge_id == chg.id)).first()
        updated_chg = s.scalars(select(Charge).where(Charge.id == chg.id)).first()

        print('\n=== STEP 3: DB ROWS CREATED ===')
        print(f"Charge Updated Status: {updated_chg.status}")
        print('DB CLAIMS ROW:')
        print({
            'id': str(claim_row.id),
            'claim_id': claim_row.claim_id,
            'charge_id': str(claim_row.charge_id),
            'assessment': claim_row.assessment,
            'claim_amount': str(claim_row.claim_amount),
            'confidence': str(claim_row.confidence),
            'status': claim_row.status,
            'explanation': claim_row.explanation
        } if claim_row else None)

        print('DB CLAIM_EVIDENCE ROWS:')
        print([{'id': str(ce.id), 'claim_id': str(ce.claim_id), 'evidence_id': str(ce.evidence_id)} for ce in ce_rows])

        print('DB ASSESSMENT_LOG ROW:')
        print({
            'id': str(log_row.id),
            'charge_id': str(log_row.charge_id),
            'assessment': log_row.assessment,
            'claim_supported': log_row.claim_supported,
            'claim_amount': str(log_row.claim_amount),
            'confidence': str(log_row.confidence),
            'reason': log_row.reason,
            'evidence_ids': log_row.evidence_ids
        } if log_row else None)

        # Clean up
        s.execute(text("DELETE FROM claim_evidence WHERE claim_id IN (SELECT id FROM claims WHERE charge_id = :cid)").params(cid=chg.id))
        s.execute(text("DELETE FROM claims WHERE charge_id = :cid").params(cid=chg.id))
        s.execute(text("DELETE FROM assessment_log WHERE charge_id = :cid").params(cid=chg.id))
        s.execute(text("DELETE FROM evidence WHERE id = :eid").params(eid=evd.id))
        s.execute(text("DELETE FROM charges WHERE id = :cid").params(cid=chg.id))
        s.execute(text("DELETE FROM shipments WHERE id = :sid").params(sid=shp.id))
        s.execute(text("DELETE FROM orders WHERE id = :oid").params(oid=ord_rec.id))
        s.commit()
        print('\n=== STEP 4: CLEANUP COMPLETED SUCCESSFULLY ===')
    finally:
        s.close()

if __name__ == '__main__':
    run()
