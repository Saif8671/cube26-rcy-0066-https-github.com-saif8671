-- ==============================================================================
-- Migration: 003_official_contract_alignment.sql
-- Product: Recovery Manager - Official Evidence Contract Alignment
-- Purpose:
--   1. Align join keys to unit_id and fnsku across charges and evidence.
--   2. Multi-tenancy: add org_id to all 8 operational tables.
--   3. Row-Level Security (RLS): Enable and FORCE RLS on all 8 tables scoped to org_id.
--   4. Standardize charge_type to official 5-value enum constraint.
--   5. Add report_type column to charges (fee_report, inventory_adjustment, reimbursement_report).
--   6. Grant appropriate table and sequence permissions to authenticated role for RLS isolation.
-- ==============================================================================

-- 1. ADD unit_id, fnsku, report_type, org_id to charges
ALTER TABLE charges
    ADD COLUMN IF NOT EXISTS unit_id TEXT,
    ADD COLUMN IF NOT EXISTS fnsku TEXT,
    ADD COLUMN IF NOT EXISTS report_type TEXT NOT NULL DEFAULT 'fee_report',
    ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'org_demo_alpha';

-- 2. ADD unit_id, fnsku, org_id to evidence
ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS unit_id TEXT,
    ADD COLUMN IF NOT EXISTS fnsku TEXT,
    ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'org_demo_alpha';

-- 3. ADD org_id to remaining tables
ALTER TABLE reimbursements
    ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'org_demo_alpha';

ALTER TABLE claims
    ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'org_demo_alpha';

ALTER TABLE claim_evidence
    ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'org_demo_alpha';

ALTER TABLE assessment_log
    ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'org_demo_alpha';

ALTER TABLE shipments
    ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'org_demo_alpha';

ALTER TABLE orders
    ADD COLUMN IF NOT EXISTS org_id TEXT NOT NULL DEFAULT 'org_demo_alpha';

-- 4. MIGRATE LEGACY CHARGE_TYPES
UPDATE charges
SET charge_type = 'inbound_defect_fee'
WHERE charge_type IN (
    'Unplanned prep - Barcode relabeling',
    'Packaging defect - Missing suffocation warning',
    'Taping defect fee',
    'Fee',
    'Packaging defect'
);

UPDATE charges
SET charge_type = 'fulfilment_fee_weight_tier'
WHERE charge_type IN (
    'Weight discrepancy surcharge',
    'Weight discrepancy'
);

UPDATE charges
SET charge_type = 'inbound_defect_fee'
WHERE charge_type NOT IN (
    'inbound_defect_fee',
    'lost_inbound',
    'damaged_in_warehouse',
    'fulfilment_fee_weight_tier',
    'refund_issued_item_not_returned'
);

-- 5. CONSTRAINTS FOR charge_type AND report_type
ALTER TABLE charges
    DROP CONSTRAINT IF EXISTS chk_charges_charge_type;

ALTER TABLE charges
    ADD CONSTRAINT chk_charges_charge_type
    CHECK (charge_type IN (
        'inbound_defect_fee',
        'lost_inbound',
        'damaged_in_warehouse',
        'fulfilment_fee_weight_tier',
        'refund_issued_item_not_returned'
    ));

ALTER TABLE charges
    DROP CONSTRAINT IF EXISTS chk_charges_report_type;

ALTER TABLE charges
    ADD CONSTRAINT chk_charges_report_type
    CHECK (report_type IN (
        'fee_report',
        'inventory_adjustment',
        'reimbursement_report'
    ));

-- 6. INDEXES FOR PERFORMANCE & JOIN EFFICIENCY
CREATE INDEX IF NOT EXISTS idx_charges_unit_id ON charges(unit_id);
CREATE INDEX IF NOT EXISTS idx_charges_fnsku ON charges(fnsku);
CREATE INDEX IF NOT EXISTS idx_charges_org_id ON charges(org_id);
CREATE INDEX IF NOT EXISTS idx_charges_report_type ON charges(report_type);

CREATE INDEX IF NOT EXISTS idx_evidence_unit_id ON evidence(unit_id);
CREATE INDEX IF NOT EXISTS idx_evidence_fnsku ON evidence(fnsku);
CREATE INDEX IF NOT EXISTS idx_evidence_org_id ON evidence(org_id);

CREATE INDEX IF NOT EXISTS idx_reimbursements_org_id ON reimbursements(org_id);
CREATE INDEX IF NOT EXISTS idx_claims_org_id ON claims(org_id);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_org_id ON claim_evidence(org_id);
CREATE INDEX IF NOT EXISTS idx_assessment_log_org_id ON assessment_log(org_id);
CREATE INDEX IF NOT EXISTS idx_shipments_org_id ON shipments(org_id);
CREATE INDEX IF NOT EXISTS idx_orders_org_id ON orders(org_id);

-- 7. ENABLE AND FORCE ROW LEVEL SECURITY (RLS) ON ALL 8 TABLES
-- Table 1: charges
ALTER TABLE charges ENABLE ROW LEVEL SECURITY;
ALTER TABLE charges FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_policy ON charges;
CREATE POLICY org_isolation_policy ON charges
    FOR ALL
    USING (org_id = current_setting('app.current_org', true))
    WITH CHECK (org_id = current_setting('app.current_org', true));

-- Table 2: evidence
ALTER TABLE evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_policy ON evidence;
CREATE POLICY org_isolation_policy ON evidence
    FOR ALL
    USING (org_id = current_setting('app.current_org', true))
    WITH CHECK (org_id = current_setting('app.current_org', true));

-- Table 3: reimbursements
ALTER TABLE reimbursements ENABLE ROW LEVEL SECURITY;
ALTER TABLE reimbursements FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_policy ON reimbursements;
CREATE POLICY org_isolation_policy ON reimbursements
    FOR ALL
    USING (org_id = current_setting('app.current_org', true))
    WITH CHECK (org_id = current_setting('app.current_org', true));

-- Table 4: claims
ALTER TABLE claims ENABLE ROW LEVEL SECURITY;
ALTER TABLE claims FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_policy ON claims;
CREATE POLICY org_isolation_policy ON claims
    FOR ALL
    USING (org_id = current_setting('app.current_org', true))
    WITH CHECK (org_id = current_setting('app.current_org', true));

-- Table 5: claim_evidence
ALTER TABLE claim_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE claim_evidence FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_policy ON claim_evidence;
CREATE POLICY org_isolation_policy ON claim_evidence
    FOR ALL
    USING (org_id = current_setting('app.current_org', true))
    WITH CHECK (org_id = current_setting('app.current_org', true));

-- Table 6: assessment_log
ALTER TABLE assessment_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE assessment_log FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_policy ON assessment_log;
CREATE POLICY org_isolation_policy ON assessment_log
    FOR ALL
    USING (org_id = current_setting('app.current_org', true))
    WITH CHECK (org_id = current_setting('app.current_org', true));

-- Table 7: shipments
ALTER TABLE shipments ENABLE ROW LEVEL SECURITY;
ALTER TABLE shipments FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_policy ON shipments;
CREATE POLICY org_isolation_policy ON shipments
    FOR ALL
    USING (org_id = current_setting('app.current_org', true))
    WITH CHECK (org_id = current_setting('app.current_org', true));

-- Table 8: orders
ALTER TABLE orders ENABLE ROW LEVEL SECURITY;
ALTER TABLE orders FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_policy ON orders;
CREATE POLICY org_isolation_policy ON orders
    FOR ALL
    USING (org_id = current_setting('app.current_org', true))
    WITH CHECK (org_id = current_setting('app.current_org', true));

-- 8. GRANT ROLE PERMISSIONS
GRANT ALL ON ALL TABLES IN SCHEMA public TO authenticated;
GRANT ALL ON ALL SEQUENCES IN SCHEMA public TO authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO authenticated;
