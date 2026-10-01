import csv, json
from pathlib import Path
from sqlalchemy import text
from app.core.database import engine

root = Path(__file__).resolve().parents[1]
files = {
    'receiving': root/'data/upstream/receiving_sample.csv',
    'prep': root/'data/upstream/prep_sample.csv',
    'pack': root/'data/upstream/pack_sample.csv',
    'returns': root/'data/upstream/returns_sample.csv',
    'fee': root/'data/fee_report_sample.csv',
}
rows = {}
for key, path in files.items():
    with path.open(newline='', encoding='utf-8') as f:
        rows[key] = list(csv.DictReader(f))
    print(f'SOURCE {key} path={path} rows={len(rows[key])}')

def raw(row):
    d = dict(row._mapping)
    for k, v in list(d.items()):
        if hasattr(v, 'isoformat'):
            d[k] = v.isoformat()
        elif v is not None:
            d[k] = str(v)
    return d

with engine.connect() as c:
    print('COUNTS_BY_MANAGER_ORG')
    q = text("""
      SELECT source_manager, org_id, count(*) AS n,
             count(*) FILTER (WHERE shipment_id IS NULL) AS null_shipment_id,
             count(*) FILTER (WHERE order_id IS NULL) AS null_order_id
      FROM evidence GROUP BY source_manager, org_id ORDER BY source_manager, org_id
    """)
    for r in c.execute(q): print(raw(r))

    print('PREEXISTING_EVIDENCE_NOT_IN_SOURCE_BY_MANAGER')
    source_ids = {key: {r.get('record_id') for r in vals} for key, vals in rows.items() if key != 'fee'}
    for manager, key in [('Receiving','receiving'),('Prep','prep'),('Pack','pack'),('Returns','returns')]:
        q = text("""SELECT evidence_id, org_id, unit_id, source_manager, evidence_content,
                          evidence_timestamp, created_at, shipment_id, order_id
                   FROM evidence WHERE source_manager=:m ORDER BY evidence_id""")
        for r in c.execute(q, {'m':manager}):
            d = raw(r)
            if d['evidence_id'] not in source_ids[key]: print(d)

    print('ALPHA_CHARGES_NOT_IN_FEE_SOURCE')
    fee_ids = {r.get('line_id') for r in rows['fee']}
    for r in c.execute(text("""SELECT charge_id, org_id, report_type, unit_id, shipment_id,
                                      order_id, sku, charge_type, amount, charge_date,
                                      source_report, raw_data, created_at
                               FROM charges WHERE org_id='org_demo_alpha' ORDER BY charge_id""")):
        d = raw(r)
        if d['charge_id'] not in fee_ids: print(d)

    print('ALPHA_REIMBURSEMENTS')
    for r in c.execute(text("""SELECT reimbursement_id, org_id, charge_id, amount,
                                      reimbursement_date, raw_data, created_at
                               FROM reimbursements WHERE org_id='org_demo_alpha'
                               ORDER BY reimbursement_id""")): print(raw(r))

    fee_shipments = {r.get('fba_shipment_id') for r in rows['fee'] if r.get('org_id')=='org_demo_alpha' and r.get('fba_shipment_id')}
    fee_orders = {r.get('order_id') for r in rows['fee'] if r.get('org_id')=='org_demo_alpha' and r.get('order_id')}
    live_shipments = {r[0] for r in c.execute(text("SELECT shipment_id FROM shipments WHERE org_id='org_demo_alpha'"))}
    live_orders = {r[0] for r in c.execute(text("SELECT order_id FROM orders WHERE org_id='org_demo_alpha'"))}
    print('ALPHA_FEE_DISTINCT_SHIPMENTS', sorted(fee_shipments))
    print('ALPHA_FEE_DISTINCT_ORDERS', sorted(fee_orders))
    print('ALPHA_SHIPMENTS_NOT_IN_FEE', sorted(live_shipments - fee_shipments))
    print('ALPHA_ORDERS_NOT_IN_FEE', sorted(live_orders - fee_orders))
    print('ALPHA_FEE_SHIPMENTS_NOT_LIVE', sorted(fee_shipments - live_shipments))
    print('ALPHA_FEE_ORDERS_NOT_LIVE', sorted(fee_orders - live_orders))
    print('LIVE_ALPHA_SHIPMENTS')
    for r in c.execute(text("SELECT shipment_id, org_id, created_at FROM shipments WHERE org_id='org_demo_alpha' ORDER BY shipment_id")): print(raw(r))
    print('LIVE_ALPHA_ORDERS')
    for r in c.execute(text("SELECT order_id, org_id, created_at FROM orders WHERE org_id='org_demo_alpha' ORDER BY order_id")): print(raw(r))
