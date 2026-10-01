import csv, json
from pathlib import Path
from sqlalchemy import text
from app.core.database import engine

root = Path(__file__).resolve().parents[1]
with (root/'data/fee_report_sample.csv').open(newline='', encoding='utf-8') as f:
    fees = list(csv.DictReader(f))
print('FEE_0071_SOURCE_ROWS')
for r in fees:
    if r.get('line_id','').startswith('FEE-0071-'): print(r)

def raw(row):
    d=dict(row._mapping)
    for k,v in list(d.items()):
        if hasattr(v,'isoformat'): d[k]=v.isoformat()
        elif v is not None: d[k]=str(v)
    return d

with engine.connect() as c:
    print('FEE_0071_LIVE_CHARGES')
    for r in c.execute(text("""SELECT charge_id,org_id,unit_id,shipment_id,order_id,sku,charge_type,amount,charge_date,report_type,raw_data FROM charges WHERE charge_id LIKE 'FEE-0071-%' ORDER BY charge_id""")): print(raw(r))
    print('REIMBURSEMENTS_AND_INVENTORY_ADJUSTMENTS_RAW')
    for r in c.execute(text("""SELECT 'reimbursement' AS kind,reimbursement_id,org_id,charge_id,amount,reimbursement_date,raw_data FROM reimbursements
                              UNION ALL
                              SELECT 'inventory_adjustment',charge_id,org_id,NULL,amount,charge_date,raw_data FROM charges WHERE report_type='inventory_adjustment'
                              UNION ALL
                              SELECT 'reimbursement_report',charge_id,org_id,NULL,amount,charge_date,raw_data FROM charges WHERE report_type='reimbursement_report'
                              ORDER BY kind, reimbursement_id""")): print(raw(r))
    print('PACK_SAMPLES_RAW')
    for r in c.execute(text("""SELECT evidence_id,org_id,unit_id,order_id,source_manager,evidence_content FROM evidence WHERE source_manager='Pack' ORDER BY evidence_id LIMIT 5""")): print(raw(r))
    print('FEE_SAMPLES_RAW')
    for r in c.execute(text("""SELECT charge_id,org_id,unit_id,order_id,sku,charge_type,amount,charge_date FROM charges WHERE source_report='fee_report_sample.csv' ORDER BY charge_id LIMIT 5""")): print(raw(r))
    print('DUPLICATE_SCENARIO_COUNT')
    q=text("""SELECT count(*) AS n FROM (SELECT org_id,unit_id,charge_type,amount,charge_date, count(DISTINCT charge_id) AS ids FROM charges GROUP BY 1,2,3,4,5 HAVING count(DISTINCT charge_id)>1) x""")
    print(c.execute(q).scalar_one())
    print('UNIT_0071_EVIDENCE_RAW')
    for r in c.execute(text("""SELECT evidence_id,org_id,unit_id,source_manager,shipment_id,order_id,sku,asin,evidence_type,evidence_content,evidence_timestamp FROM evidence WHERE org_id='org_demo_alpha' AND unit_id='UNIT-0071' ORDER BY source_manager,evidence_id""")): print(raw(r))
    print('CONFLICT_CANDIDATES_SAME_UNIT_MANAGER_FIELD')
    for r in c.execute(text("""SELECT org_id,source_manager,unit_id,evidence_type, count(*) AS n, count(DISTINCT evidence_content::text) AS values_n
                              FROM evidence WHERE unit_id IS NOT NULL GROUP BY 1,2,3,4 HAVING count(DISTINCT evidence_content::text)>1 ORDER BY 1,2,3,4""")): print(raw(r))
