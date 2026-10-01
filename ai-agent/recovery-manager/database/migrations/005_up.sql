-- Migration 005: scope external text identifiers by organization.
-- Append/drop-constraint only; it never changes existing rows.
BEGIN;
SET LOCAL lock_timeout = '5s';

ALTER TABLE shipments ADD CONSTRAINT shipments_org_shipment_id_key UNIQUE (org_id, shipment_id);
ALTER TABLE orders ADD CONSTRAINT orders_org_order_id_key UNIQUE (org_id, order_id);
ALTER TABLE charges ADD CONSTRAINT charges_org_charge_id_key UNIQUE (org_id, charge_id);
ALTER TABLE evidence ADD CONSTRAINT evidence_org_evidence_id_key UNIQUE (org_id, evidence_id);
ALTER TABLE reimbursements ADD CONSTRAINT reimbursements_org_reimbursement_id_key UNIQUE (org_id, reimbursement_id);
ALTER TABLE claims ADD CONSTRAINT claims_org_claim_id_key UNIQUE (org_id, claim_id);

ALTER TABLE shipments DROP CONSTRAINT shipments_shipment_id_key;
ALTER TABLE orders DROP CONSTRAINT orders_order_id_key;
ALTER TABLE charges DROP CONSTRAINT charges_charge_id_key;
ALTER TABLE evidence DROP CONSTRAINT evidence_evidence_id_key;
ALTER TABLE reimbursements DROP CONSTRAINT reimbursements_reimbursement_id_key;
ALTER TABLE claims DROP CONSTRAINT claims_claim_id_key;

ALTER TABLE charges ADD COLUMN IF NOT EXISTS data_origin TEXT NOT NULL DEFAULT 'judge_data';
ALTER TABLE evidence ADD COLUMN IF NOT EXISTS data_origin TEXT NOT NULL DEFAULT 'judge_data';
ALTER TABLE reimbursements ADD COLUMN IF NOT EXISTS data_origin TEXT NOT NULL DEFAULT 'judge_data';
ALTER TABLE claims ADD COLUMN IF NOT EXISTS data_origin TEXT NOT NULL DEFAULT 'judge_data';
COMMIT;
