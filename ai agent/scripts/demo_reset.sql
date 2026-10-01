-- ==============================================================================
-- Script: scripts/demo_reset.sql
-- Product: Recovery Manager
-- Purpose: Safely and idempotently reset all pipeline outputs, derived records,
--          uploads, and manual test data for tenant org_demo_alpha before a demo run.
--
-- Safety Guarantees:
--   - Does NOT drop schema or database.
--   - Does NOT recreate tables.
--   - Does NOT disable RLS policies (preserves security rules).
--   - Strictly preserves other tenant data (org_demo_bravo).
--   - Honors foreign key dependency order (claim_evidence -> claims/evidence -> charges -> containers).
--   - Temporarily disables immutability trigger on overrides to allow clean reset, then re-enables.
--   - Fully idempotent: can be executed multiple times safely.
-- ==============================================================================

BEGIN;

-- 1. Set tenant session context to ensure RLS compliance
SET LOCAL app.current_org = 'org_demo_alpha';

-- 2. Remove Claim Evidence Linkages for org_demo_alpha
DELETE FROM claim_evidence
WHERE org_id = 'org_demo_alpha'
   OR claim_id IN (SELECT id FROM claims WHERE org_id = 'org_demo_alpha');

-- 3. Remove Overrides (Handle append-only trigger safely)
ALTER TABLE overrides DISABLE TRIGGER trg_prevent_overrides_mutation;
DELETE FROM overrides
WHERE org_id = 'org_demo_alpha'
   OR charge_id IN (SELECT id FROM charges WHERE org_id = 'org_demo_alpha');
ALTER TABLE overrides ENABLE TRIGGER trg_prevent_overrides_mutation;

-- 4. Remove Claims for org_demo_alpha
DELETE FROM claims
WHERE org_id = 'org_demo_alpha'
   OR charge_id IN (SELECT id FROM charges WHERE org_id = 'org_demo_alpha');

-- 5. Remove Assessment Audit Logs for org_demo_alpha
DELETE FROM assessment_log
WHERE org_id = 'org_demo_alpha'
   OR charge_id IN (SELECT id FROM charges WHERE org_id = 'org_demo_alpha');

-- 6. Remove Pipeline Execution Errors for org_demo_alpha
DELETE FROM pipeline_errors
WHERE org_id = 'org_demo_alpha'
   OR charge_id IN (SELECT id FROM charges WHERE org_id = 'org_demo_alpha');

-- 7. Remove Reimbursements for org_demo_alpha
DELETE FROM reimbursements
WHERE org_id = 'org_demo_alpha'
   OR charge_id IN (SELECT id FROM charges WHERE org_id = 'org_demo_alpha');

-- 8. Remove Charges for org_demo_alpha
DELETE FROM charges
WHERE org_id = 'org_demo_alpha';

-- 9. Remove Evidence Records for org_demo_alpha
DELETE FROM evidence
WHERE org_id = 'org_demo_alpha';

-- 10. Remove Container Records (Shipments and Orders) created for org_demo_alpha
-- (charges and evidence hold ON DELETE SET NULL references to shipments/orders)
DELETE FROM shipments
WHERE org_id = 'org_demo_alpha';

DELETE FROM orders
WHERE org_id = 'org_demo_alpha';

COMMIT;
