-- ==============================================================================
-- Script: scripts/demo_verify.sql
-- Product: Recovery Manager
-- Purpose: Verify dataset integrity, table counts, charge distributions,
--          tenant isolation, and pipeline outcome metrics for tenant org_demo_alpha.
-- ==============================================================================

-- 1. Table Counts (Total vs org_demo_alpha vs org_demo_bravo)
SELECT 
    'assessment_log' AS table_name,
    COUNT(*) AS total_rows,
    COUNT(*) FILTER (WHERE org_id = 'org_demo_alpha') AS alpha_rows,
    COUNT(*) FILTER (WHERE org_id = 'org_demo_bravo') AS bravo_rows
FROM assessment_log
UNION ALL
SELECT 'charges', COUNT(*), COUNT(*) FILTER (WHERE org_id = 'org_demo_alpha'), COUNT(*) FILTER (WHERE org_id = 'org_demo_bravo') FROM charges
UNION ALL
SELECT 'claim_evidence', COUNT(*), COUNT(*) FILTER (WHERE org_id = 'org_demo_alpha'), COUNT(*) FILTER (WHERE org_id = 'org_demo_bravo') FROM claim_evidence
UNION ALL
SELECT 'claims', COUNT(*), COUNT(*) FILTER (WHERE org_id = 'org_demo_alpha'), COUNT(*) FILTER (WHERE org_id = 'org_demo_bravo') FROM claims
UNION ALL
SELECT 'evidence', COUNT(*), COUNT(*) FILTER (WHERE org_id = 'org_demo_alpha'), COUNT(*) FILTER (WHERE org_id = 'org_demo_bravo') FROM evidence
UNION ALL
SELECT 'orders', COUNT(*), COUNT(*) FILTER (WHERE org_id = 'org_demo_alpha'), COUNT(*) FILTER (WHERE org_id = 'org_demo_bravo') FROM orders
UNION ALL
SELECT 'overrides', COUNT(*), COUNT(*) FILTER (WHERE org_id = 'org_demo_alpha'), COUNT(*) FILTER (WHERE org_id = 'org_demo_bravo') FROM overrides
UNION ALL
SELECT 'pipeline_errors', COUNT(*), COUNT(*) FILTER (WHERE org_id = 'org_demo_alpha'), COUNT(*) FILTER (WHERE org_id = 'org_demo_bravo') FROM pipeline_errors
UNION ALL
SELECT 'reimbursements', COUNT(*), COUNT(*) FILTER (WHERE org_id = 'org_demo_alpha'), COUNT(*) FILTER (WHERE org_id = 'org_demo_bravo') FROM reimbursements
UNION ALL
SELECT 'shipments', COUNT(*), COUNT(*) FILTER (WHERE org_id = 'org_demo_alpha'), COUNT(*) FILTER (WHERE org_id = 'org_demo_bravo') FROM shipments
ORDER BY table_name;

-- 2. Charges Breakdown by Charge Type
SELECT 
    charge_type,
    COUNT(*) AS total_charges,
    COUNT(*) FILTER (WHERE org_id = 'org_demo_alpha') AS alpha_charges,
    COUNT(*) FILTER (WHERE org_id = 'org_demo_bravo') AS bravo_charges,
    COALESCE(SUM(amount) FILTER (WHERE org_id = 'org_demo_alpha'), 0.00) AS alpha_total_usd
FROM charges
GROUP BY charge_type
ORDER BY charge_type;

-- 3. Counts by org_id (Tenant Isolation Confirmation)
SELECT 
    ch_org.org_id,
    COUNT(DISTINCT c.id) AS charges_count,
    (SELECT COUNT(*) FROM evidence e WHERE e.org_id = ch_org.org_id) AS evidence_count,
    (SELECT COUNT(*) FROM claims cl WHERE cl.org_id = ch_org.org_id) AS claims_count,
    (SELECT COUNT(*) FROM assessment_log al WHERE al.org_id = ch_org.org_id) AS assessment_count
FROM (SELECT DISTINCT org_id FROM charges) ch_org
LEFT JOIN charges c ON c.org_id = ch_org.org_id
GROUP BY ch_org.org_id
ORDER BY ch_org.org_id;

-- 4. Claims Verification for org_demo_alpha
SELECT 
    cl.claim_id,
    ch.charge_id,
    ch.charge_type,
    cl.assessment,
    cl.status,
    cl.claim_amount,
    cl.confidence,
    (SELECT COUNT(*) FROM claim_evidence ce WHERE ce.claim_id = cl.id) AS attached_evidence_count
FROM claims cl
JOIN charges ch ON cl.charge_id = ch.id
WHERE cl.org_id = 'org_demo_alpha'
ORDER BY cl.created_at;

-- 5. Assessment Log Outcome Summary (org_demo_alpha)
SELECT 
    assessment,
    claim_supported,
    COUNT(*) AS count_assessments,
    COALESCE(SUM(claim_amount), 0.00) AS total_claimed_amount
FROM assessment_log
WHERE org_id = 'org_demo_alpha'
GROUP BY assessment, claim_supported
ORDER BY assessment;

-- 6. Demo Synthetic Charge Scenario Verification
SELECT 
    ch.charge_id,
    ch.charge_type,
    ch.amount AS fee_amount,
    al.assessment,
    cl.claim_id,
    cl.claim_amount,
    cl.status AS claim_status
FROM charges ch
LEFT JOIN assessment_log al ON al.charge_id = ch.id
LEFT JOIN claims cl ON cl.charge_id = ch.id
WHERE ch.charge_id LIKE 'DEMO-CHG-' || '%'
ORDER BY ch.charge_id;
