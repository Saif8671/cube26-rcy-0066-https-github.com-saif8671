-- ==============================================================================
-- Migration: 001_initial_schema.sql
-- Product: Recovery Manager - Evidence-First Financial Recovery
-- Target: PostgreSQL 14+ / Supabase
-- Core Principle: "Evidence first, claim second." Every claim must be traceable
-- to a charge, a shipment/order/SKU, specific evidence records, the evidence's
-- source manager, and a timestamp.
-- ==============================================================================

-- Ensure pgcrypto extension is available for UUID generation in Supabase / PostgreSQL
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ------------------------------------------------------------------------------
-- 1. SHIPMENTS
-- External fulfillment or inbound shipment entities.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS shipments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shipment_id TEXT NOT NULL UNIQUE,
    order_id TEXT, -- Nullable external reference (orders may not always be modeled as a full row initially)
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------------------
-- 2. ORDERS
-- External marketplace customer or transfer orders.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orders (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------------------
-- 3. CHARGES
-- Discrepancy charges and fees imposed by marketplace/carrier (e.g. FBA defect fees).
-- Foreign keys use ON DELETE SET NULL to preserve charge audit history even if
-- a parent container is pruned.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS charges (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    charge_id TEXT NOT NULL UNIQUE,
    shipment_id UUID REFERENCES shipments(id) ON DELETE SET NULL,
    order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
    sku TEXT,
    asin TEXT,
    charge_type TEXT NOT NULL, -- e.g. "Packaging defect", "Weight discrepancy", "Missing barcode"
    amount NUMERIC(12, 2) NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    charge_date TIMESTAMPTZ NOT NULL,
    source_report TEXT, -- Source fee/reimbursement report filename or batch ID
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb, -- Original row for traceability/debugging
    status TEXT NOT NULL DEFAULT 'PENDING', -- e.g. PENDING, PROCESSED, DISPUTED
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------------------
-- 4. EVIDENCE
-- Verifiable operational proof (prep scans, scale logs, pack photos, warehouse audits).
-- Foreign keys use ON DELETE SET NULL to guarantee operational evidence is NEVER
-- cascade deleted.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    evidence_id TEXT NOT NULL UNIQUE, -- External identifier, e.g. "PREP-8821"
    source_manager TEXT NOT NULL, -- Operational source, e.g. "Receiving", "Prep", "Pack", "Returns"
    shipment_id UUID REFERENCES shipments(id) ON DELETE SET NULL,
    order_id UUID REFERENCES orders(id) ON DELETE SET NULL,
    sku TEXT,
    asin TEXT,
    evidence_type TEXT NOT NULL, -- e.g. "packaging_check", "receiving_count", "scale_audit"
    evidence_content JSONB NOT NULL, -- Structured result, e.g. {"packaging_check": "PASS", "polybag_thickness_mil": 1.5}
    evidence_timestamp TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------------------
-- 5. REIMBURSEMENTS
-- Known marketplace payouts / credits. References charges when matched.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS reimbursements (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reimbursement_id TEXT NOT NULL UNIQUE,
    charge_id UUID REFERENCES charges(id) ON DELETE SET NULL,
    amount NUMERIC(12, 2) NOT NULL,
    reimbursement_date TIMESTAMPTZ NOT NULL,
    raw_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------------------
-- 6. CLAIMS
-- Recovery decisions evaluating a charge against operational evidence.
-- Assessment is strictly constrained to 4 valid outcomes:
--   - SUPPORTED: Operational evidence confirms the charge is erroneous/disputable.
--   - CONTRADICTED: Operational evidence proves the charge is valid (seller fault).
--   - SILENT: No operational evidence exists for this event (valid state, not an error).
--   - UNCERTAIN: Conflicting or ambiguous evidence records (valid state, not an error).
-- 
-- Integrity Rules:
--   - charge_id ON DELETE RESTRICT: A charge linked to a claim cannot be deleted.
--   - claim_amount: Nullable; should be NULL when no claim is supported (e.g. SILENT, CONTRADICTED).
--   - App-level validation note: claim_amount must satisfy (claim_amount <= charges.amount).
--     Enforced at application layer or via trigger to keep table DDL decoupled.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS claims (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id TEXT NOT NULL UNIQUE, -- External/display identifier, e.g. "CLM-10091"
    charge_id UUID NOT NULL REFERENCES charges(id) ON DELETE RESTRICT,
    assessment TEXT NOT NULL CHECK (assessment IN ('CONTRADICTED', 'SUPPORTED', 'SILENT', 'UNCERTAIN')),
    claim_amount NUMERIC(12, 2), -- NULL when assessment is SILENT, CONTRADICTED, or UNCERTAIN
    confidence NUMERIC(5, 4) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    explanation TEXT,
    status TEXT NOT NULL DEFAULT 'READY_FOR_REVIEW', -- e.g. READY_FOR_REVIEW, DUPLICATE, ALREADY_REIMBURSED, REJECTED, APPROVED
    source_manager TEXT, -- Primary operational evidence source manager
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------------------------
-- 7. CLAIM_EVIDENCE (Join Table)
-- Provides indisputable, many-to-many traceability between claims and specific
-- evidence items. Both foreign keys use ON DELETE RESTRICT to preserve audit trail.
-- ------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS claim_evidence (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    claim_id UUID NOT NULL REFERENCES claims(id) ON DELETE RESTRICT,
    evidence_id UUID NOT NULL REFERENCES evidence(id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_claim_evidence UNIQUE (claim_id, evidence_id)
);

-- ------------------------------------------------------------------------------
-- PERFORMANCE & QUERY INDEXES
-- Optimized for Phase 4 evidence-matching and recovery reasoning queries.
-- ------------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_charges_shipment_id ON charges(shipment_id);
CREATE INDEX IF NOT EXISTS idx_charges_order_id ON charges(order_id);
CREATE INDEX IF NOT EXISTS idx_charges_sku ON charges(sku);

CREATE INDEX IF NOT EXISTS idx_evidence_shipment_id ON evidence(shipment_id);
CREATE INDEX IF NOT EXISTS idx_evidence_order_id ON evidence(order_id);
CREATE INDEX IF NOT EXISTS idx_evidence_sku ON evidence(sku);
CREATE INDEX IF NOT EXISTS idx_evidence_asin ON evidence(asin);

CREATE INDEX IF NOT EXISTS idx_claims_charge_id ON claims(charge_id);

CREATE INDEX IF NOT EXISTS idx_claim_evidence_claim_id ON claim_evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_evidence_id ON claim_evidence(evidence_id);
