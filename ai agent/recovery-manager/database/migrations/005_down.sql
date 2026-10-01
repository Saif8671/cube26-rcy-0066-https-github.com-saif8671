-- Migration 005 rollback. Refuses to restore global uniqueness after a cross-org collision.
BEGIN;
SET LOCAL lock_timeout = '5s';

DO $migration$
BEGIN
    IF EXISTS (SELECT 1 FROM shipments GROUP BY shipment_id HAVING count(*) > 1)
       OR EXISTS (SELECT 1 FROM orders GROUP BY order_id HAVING count(*) > 1)
       OR EXISTS (SELECT 1 FROM charges GROUP BY charge_id HAVING count(*) > 1)
       OR EXISTS (SELECT 1 FROM evidence GROUP BY evidence_id HAVING count(*) > 1)
       OR EXISTS (SELECT 1 FROM reimbursements GROUP BY reimbursement_id HAVING count(*) > 1)
       OR EXISTS (SELECT 1 FROM claims GROUP BY claim_id HAVING count(*) > 1) THEN
        RAISE EXCEPTION '005 down aborted: cross-organization duplicate text identifiers exist';
    END IF;
END
$migration$;

ALTER TABLE shipments ADD CONSTRAINT shipments_shipment_id_key UNIQUE (shipment_id);
ALTER TABLE orders ADD CONSTRAINT orders_order_id_key UNIQUE (order_id);
ALTER TABLE charges ADD CONSTRAINT charges_charge_id_key UNIQUE (charge_id);
ALTER TABLE evidence ADD CONSTRAINT evidence_evidence_id_key UNIQUE (evidence_id);
ALTER TABLE reimbursements ADD CONSTRAINT reimbursements_reimbursement_id_key UNIQUE (reimbursement_id);
ALTER TABLE claims ADD CONSTRAINT claims_claim_id_key UNIQUE (claim_id);

ALTER TABLE shipments DROP CONSTRAINT shipments_org_shipment_id_key;
ALTER TABLE orders DROP CONSTRAINT orders_org_order_id_key;
ALTER TABLE charges DROP CONSTRAINT charges_org_charge_id_key;
ALTER TABLE evidence DROP CONSTRAINT evidence_org_evidence_id_key;
ALTER TABLE reimbursements DROP CONSTRAINT reimbursements_org_reimbursement_id_key;
ALTER TABLE claims DROP CONSTRAINT claims_org_claim_id_key;

ALTER TABLE charges DROP COLUMN IF EXISTS data_origin;
ALTER TABLE evidence DROP COLUMN IF EXISTS data_origin;
ALTER TABLE reimbursements DROP COLUMN IF EXISTS data_origin;
ALTER TABLE claims DROP COLUMN IF EXISTS data_origin;
COMMIT;
