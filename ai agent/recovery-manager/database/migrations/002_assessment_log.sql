-- ==============================================================================
-- Migration: 002_assessment_log.sql
-- Product: Recovery Manager - Evidence-First Financial Recovery
-- Target: PostgreSQL 14+ / Supabase
-- Core Principle: Single complete audit trail of "every charge that was ever
-- evaluated and what the system concluded," independent of whether a claims
-- row also exists.
-- ==============================================================================

CREATE TABLE IF NOT EXISTS assessment_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    charge_id UUID NOT NULL REFERENCES charges(id) ON DELETE CASCADE,
    assessment TEXT NOT NULL CHECK (assessment IN ('CONTRADICTED', 'SUPPORTED', 'SILENT', 'UNCERTAIN')),
    claim_supported BOOLEAN NOT NULL DEFAULT false,
    claim_amount NUMERIC(12, 2),
    confidence NUMERIC(5, 4) CHECK (confidence IS NULL OR (confidence >= 0 AND confidence <= 1)),
    reason TEXT,
    evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Query and performance indexes
CREATE INDEX IF NOT EXISTS idx_assessment_log_charge_id ON assessment_log(charge_id);
CREATE INDEX IF NOT EXISTS idx_assessment_log_assessment ON assessment_log(assessment);
