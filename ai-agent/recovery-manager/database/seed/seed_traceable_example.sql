-- ==============================================================================
-- Seed Script: seed_traceable_example.sql
-- Purpose: Verify schema integrity and provide a clean end-to-end traceable
--          demonstration of charges, operational evidence, claims, reimbursements,
--          and the immutable assessment_log audit trail.
--
-- Invariant Rules:
--   - Exactly ONE claims row (CONTRADICTED/ELIGIBLE example: CLM-10092).
--   - Non-claim outcomes (SUPPORTED, SILENT) and human review (UNCERTAIN)
--     do NOT create claims rows; they are captured in assessment_log.
--   - assessment_log contains rows for all four assessment outcomes:
--     CONTRADICTED, SUPPORTED, SILENT, UNCERTAIN.
-- ==============================================================================

-- Clean up existing seed data if re-running (respecting RESTRICT constraints)
DELETE FROM claim_evidence;
DELETE FROM claims;
DELETE FROM assessment_log;
DELETE FROM reimbursements;
DELETE FROM evidence;
DELETE FROM charges;
DELETE FROM orders;
DELETE FROM shipments;

-- ------------------------------------------------------------------------------
-- 1. SHIPMENTS (3 rows)
-- ------------------------------------------------------------------------------
INSERT INTO shipments (id, shipment_id, order_id, created_at) VALUES
('a0000000-0000-0000-0000-000000000001', 'FBA17Z88Y12', '111-2000001-0000001', '2026-03-01 08:30:00+00'),
('a0000000-0000-0000-0000-000000000002', 'FBA17Z88Y13', '111-2000001-0000002', '2026-03-02 10:15:00+00'),
('a0000000-0000-0000-0000-000000000003', 'FBA17Z88Y14', NULL,                  '2026-03-03 14:00:00+00');

-- ------------------------------------------------------------------------------
-- 2. ORDERS (3 rows)
-- ------------------------------------------------------------------------------
INSERT INTO orders (id, order_id, created_at) VALUES
('b0000000-0000-0000-0000-000000000001', '111-2000001-0000001', '2026-03-01 08:00:00+00'),
('b0000000-0000-0000-0000-000000000002', '111-2000001-0000002', '2026-03-02 09:45:00+00'),
('b0000000-0000-0000-0000-000000000003', '111-2000001-0000003', '2026-03-03 11:30:00+00');

-- ------------------------------------------------------------------------------
-- 3. CHARGES (4 rows)
-- ------------------------------------------------------------------------------
INSERT INTO charges (id, charge_id, shipment_id, order_id, sku, asin, charge_type, amount, currency, charge_date, source_report, raw_data, status, created_at) VALUES
(
    'c0000000-0000-0000-0000-000000000001',
    'CHG-FBA-8901',
    'a0000000-0000-0000-0000-000000000001',
    'b0000000-0000-0000-0000-000000000001',
    'TECH-CABLE-01',
    'B08N5WRWNW',
    'inbound_defect_fee',
    125.00,
    'USD',
    '2026-03-05 12:00:00+00',
    'fba_inbound_performance_report_2026_03.csv',
    '{"defect_type": "NO_SUFFOCATION_WARNING", "units_affected": 25, "fee_per_unit": 5.00}',
    'PROCESSED',
    '2026-03-05 12:05:00+00'
),
(
    'c0000000-0000-0000-0000-000000000002',
    'CHG-FBA-8902',
    'a0000000-0000-0000-0000-000000000002',
    'b0000000-0000-0000-0000-000000000002',
    'TECH-STAND-02',
    'B07XJ8C8F5',
    'fulfilment_fee_weight_tier',
    45.50,
    'USD',
    '2026-03-06 14:30:00+00',
    'fba_inbound_performance_report_2026_03.csv',
    '{"billed_weight_lb": 4.2, "expected_weight_lb": 2.1, "rate_diff": 45.50}',
    'PROCESSED',
    '2026-03-06 14:35:00+00'
),
(
    'c0000000-0000-0000-0000-000000000003',
    'CHG-FBA-8903',
    'a0000000-0000-0000-0000-000000000003',
    NULL,
    'TECH-HUB-03',
    'B09V3K4M2L',
    'inbound_defect_fee',
    30.00,
    'USD',
    '2026-03-07 09:15:00+00',
    'fba_inbound_performance_report_2026_03.csv',
    '{"units": 15, "unit_fee": 2.00, "reason": "UNREADABLE_BARCODE"}',
    'PENDING',
    '2026-03-07 09:20:00+00'
),
(
    'c0000000-0000-0000-0000-000000000004',
    'CHG-FBA-8904',
    'a0000000-0000-0000-0000-000000000001',
    'b0000000-0000-0000-0000-000000000001',
    'TECH-ADAPT-04',
    'B091J89C2Q',
    'inbound_defect_fee',
    60.00,
    'USD',
    '2026-03-08 16:00:00+00',
    'fba_inbound_performance_report_2026_03.csv',
    '{"units": 30, "unit_fee": 2.00, "reason": "BOX_NOT_PROPERLY_TAPED"}',
    'PENDING',
    '2026-03-08 16:05:00+00'
);

-- ------------------------------------------------------------------------------
-- 4. EVIDENCE (4 rows)
-- Operational logs and inspection scans
-- ------------------------------------------------------------------------------
INSERT INTO evidence (id, evidence_id, source_manager, shipment_id, order_id, sku, asin, evidence_type, evidence_content, evidence_timestamp, created_at) VALUES
(
    'd0000000-0000-0000-0000-000000000001',
    'EVD-PREP-8821',
    'Prep',
    'a0000000-0000-0000-0000-000000000001',
    'b0000000-0000-0000-0000-000000000001',
    'TECH-CABLE-01',
    'B08N5WRWNW',
    'packaging_check',
    '{"packaging_check": "PASS", "warning_label_present": true, "polybag_thickness_mil": 1.7, "photo_url": "s3://evidence/prep/2026/03/EVD-PREP-8821.jpg", "operator_id": "OP-44"}',
    '2026-03-01 11:20:00+00',
    '2026-03-01 11:21:00+00'
),
(
    'd0000000-0000-0000-0000-000000000002',
    'EVD-SCALE-4412',
    'Receiving',
    'a0000000-0000-0000-0000-000000000002',
    'b0000000-0000-0000-0000-000000000002',
    'TECH-STAND-02',
    'B07XJ8C8F5',
    'scale_audit',
    '{"calibrated_scale_id": "SCALE-02", "actual_weight_lb": 4.19, "tare_lb": 0.10, "net_weight_lb": 4.09, "verification": "CONFIRMED_HEAVY"}',
    '2026-03-02 12:45:00+00',
    '2026-03-02 12:46:00+00'
),
(
    'd0000000-0000-0000-0000-000000000003',
    'EVD-PACK-9102',
    'Pack',
    'a0000000-0000-0000-0000-000000000001',
    'b0000000-0000-0000-0000-000000000001',
    'TECH-ADAPT-04',
    'B091J89C2Q',
    'carton_seal_audit',
    '{"tape_type": "H-TAPE_WATER_ACTIVATED", "status": "VERIFIED_SEALED", "inspector": "QA-12"}',
    '2026-03-01 15:30:00+00',
    '2026-03-01 15:31:00+00'
),
(
    'd0000000-0000-0000-0000-000000000004',
    'EVD-RECV-3301',
    'Receiving',
    'a0000000-0000-0000-0000-000000000001',
    'b0000000-0000-0000-0000-000000000001',
    'TECH-ADAPT-04',
    'B091J89C2Q',
    'receiving_anomaly_flag',
    '{"carton_intact": false, "tape_compromised": true, "notes": "Top flap unsealed upon dock arrival"}',
    '2026-03-04 09:10:00+00',
    '2026-03-04 09:12:00+00'
);

-- ------------------------------------------------------------------------------
-- 5. REIMBURSEMENTS (3 rows)
-- ------------------------------------------------------------------------------
INSERT INTO reimbursements (id, reimbursement_id, charge_id, amount, reimbursement_date, raw_data, created_at) VALUES
(
    'e0000000-0000-0000-0000-000000000001',
    'RMB-AMZ-7711',
    'c0000000-0000-0000-0000-000000000002',
    45.50,
    '2026-03-10 18:00:00+00',
    '{"settlement_id": "SETTLE-9901", "reimbursement_reason": "CUSTOMER_CONCESSION_ADJUSTMENT"}',
    '2026-03-10 18:05:00+00'
),
(
    'e0000000-0000-0000-0000-000000000002',
    'RMB-AMZ-7712',
    NULL,
    25.00,
    '2026-03-11 11:30:00+00',
    '{"settlement_id": "SETTLE-9902", "reimbursement_reason": "INVENTORY_LOST_WAREHOUSE", "sku": "TECH-CABLE-01"}',
    '2026-03-11 11:35:00+00'
),
(
    'e0000000-0000-0000-0000-000000000003',
    'RMB-AMZ-7713',
    NULL,
    10.00,
    '2026-03-12 09:00:00+00',
    '{"settlement_id": "SETTLE-9903", "reimbursement_reason": "GENERAL_ADJUSTMENT"}',
    '2026-03-12 09:05:00+00'
);

-- ------------------------------------------------------------------------------
-- 6. CLAIMS (Exactly 1 demonstration row: the CONTRADICTED/ELIGIBLE case)
-- Core Principle: "Evidence first, claim second"
-- Per Phase 6 & 7 invariants:
--   - CONTRADICTED is the only outcome that produces an actionable recovery claim.
--   - SUPPORTED and SILENT are NON_CLAIM outcomes (zero claims rows).
--   - UNCERTAIN is a HUMAN_REVIEW outcome (zero claims rows).
-- ------------------------------------------------------------------------------
INSERT INTO claims (id, claim_id, charge_id, assessment, claim_amount, confidence, explanation, status, source_manager, created_at) VALUES
(
    -- 1. CONTRADICTED: Operational proof contradicts marketplace weight surcharge; recovery claimed
    'f0000000-0000-0000-0000-000000000002',
    'CLM-10092',
    'c0000000-0000-0000-0000-000000000002',
    'CONTRADICTED',
    45.50,
    0.9200,
    'Internal scale audit EVD-SCALE-4412 recorded net weight 4.09 lb, refuting carrier billed weight of 4.2 lb. Operational evidence contradicts carrier surcharge; recovery claim eligible.',
    'READY_FOR_REVIEW',
    'Receiving',
    '2026-03-07 11:00:00+00'
);

-- ------------------------------------------------------------------------------
-- 7. CLAIM_EVIDENCE (1 row linking the CONTRADICTED claim to its verified evidence)
-- ------------------------------------------------------------------------------
INSERT INTO claim_evidence (id, claim_id, evidence_id, created_at) VALUES
('10000000-0000-0000-0000-000000000002', 'f0000000-0000-0000-0000-000000000002', 'd0000000-0000-0000-0000-000000000002', '2026-03-07 11:01:00+00');

-- ------------------------------------------------------------------------------
-- 8. ASSESSMENT_LOG (4 rows demonstrating all 4 valid assessment outcomes)
-- Complete immutable audit trail of every charge evaluated by the recovery system.
-- ------------------------------------------------------------------------------
INSERT INTO assessment_log (id, charge_id, assessment, claim_supported, claim_amount, confidence, reason, evidence_ids, created_at) VALUES
(
    -- 1. SUPPORTED (evaluated charge CHG-FBA-8901; fee confirmed valid; no claim generated)
    '80000000-0000-0000-0000-000000000001',
    'c0000000-0000-0000-0000-000000000001',
    'SUPPORTED',
    false,
    NULL,
    0.9850,
    'Operational inspection confirms packaging defect fee was properly applied under warehouse safety policy. Fee supported by operational findings; no claim generated.',
    '["EVD-PREP-8821"]'::jsonb,
    '2026-03-06 10:00:00+00'
),
(
    -- 2. CONTRADICTED (evaluated charge CHG-FBA-8902; operational evidence refutes fee; recovery claim eligible)
    '80000000-0000-0000-0000-000000000002',
    'c0000000-0000-0000-0000-000000000002',
    'CONTRADICTED',
    true,
    45.50,
    0.9200,
    'Internal scale audit EVD-SCALE-4412 recorded net weight 4.09 lb, refuting carrier billed weight of 4.2 lb. Operational evidence contradicts carrier surcharge; recovery claim eligible.',
    '["EVD-SCALE-4412"]'::jsonb,
    '2026-03-07 11:00:00+00'
),
(
    -- 3. SILENT (evaluated charge CHG-FBA-8903; no operational evidence found; system remains silent)
    '80000000-0000-0000-0000-000000000003',
    'c0000000-0000-0000-0000-000000000003',
    'SILENT',
    false,
    NULL,
    0.0000,
    'No station prep logs or barcode scanning logs recorded for SKU TECH-HUB-03 on shipment FBA17Z88Y14. System remains silent due to absence of proof.',
    '[]'::jsonb,
    '2026-03-08 14:00:00+00'
),
(
    -- 4. UNCERTAIN (evaluated charge CHG-FBA-8904; conflicting operational evidence; flagged for human review)
    '80000000-0000-0000-0000-000000000004',
    'c0000000-0000-0000-0000-000000000004',
    'UNCERTAIN',
    false,
    NULL,
    0.4500,
    'Pack station log EVD-PACK-9102 logged verified carton H-taping, but receiving dock anomaly log EVD-RECV-3301 recorded compromised seal upon transit arrival. Requires supervisor resolution.',
    '["EVD-PACK-9102", "EVD-RECV-3301"]'::jsonb,
    '2026-03-09 16:30:00+00'
);
