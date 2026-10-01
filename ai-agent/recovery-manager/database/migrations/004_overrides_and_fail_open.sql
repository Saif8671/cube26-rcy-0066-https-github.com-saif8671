-- ==============================================================================
-- Migration: 004_overrides_and_fail_open.sql
-- Product: Recovery Manager - Overrides and Fail-Open Auditing
-- Purpose:
--   1. Create `overrides` table: append-only, capturing human operator overrides
--      disagreeing with automated agents.
--   2. Enforce strict immutability (append-only) on `overrides` via trigger.
--   3. Create `pipeline_errors` table: durable persistence of pipeline execution errors
--      (model errors, timeouts, etc.) to ensure failed records are marked pending
--      and retrievable rather than disappearing silently.
--   4. Enable and FORCE Row Level Security (RLS) on both tables scoped to org_id.
-- ==============================================================================

-- 1. OVERRIDES TABLE
CREATE TABLE IF NOT EXISTS overrides (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    charge_id UUID NOT NULL REFERENCES charges(id) ON DELETE CASCADE,
    claim_id UUID REFERENCES claims(id) ON DELETE SET NULL,
    org_id TEXT NOT NULL DEFAULT 'org_demo_alpha',
    original_assessment TEXT,
    original_status TEXT,
    new_verdict TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (length(trim(reason)) > 0),
    reviewer_id TEXT NOT NULL DEFAULT 'operator',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_overrides_charge_id ON overrides(charge_id);
CREATE INDEX IF NOT EXISTS idx_overrides_claim_id ON overrides(claim_id);
CREATE INDEX IF NOT EXISTS idx_overrides_org_id ON overrides(org_id);

-- Enforce append-only on overrides (NO updates, NO deletes)
CREATE OR REPLACE FUNCTION prevent_overrides_mutation()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Overrides are immutable audit records and cannot be updated or deleted.';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_prevent_overrides_mutation ON overrides;
CREATE TRIGGER trg_prevent_overrides_mutation
BEFORE UPDATE OR DELETE ON overrides
FOR EACH ROW EXECUTE FUNCTION prevent_overrides_mutation();

-- Enable & force RLS on overrides
ALTER TABLE overrides ENABLE ROW LEVEL SECURITY;
ALTER TABLE overrides FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_policy ON overrides;
CREATE POLICY org_isolation_policy ON overrides
    FOR ALL
    USING (org_id = current_setting('app.current_org', true))
    WITH CHECK (org_id = current_setting('app.current_org', true));


-- 2. PIPELINE_ERRORS TABLE (Fail-Open)
CREATE TABLE IF NOT EXISTS pipeline_errors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    charge_id UUID NOT NULL REFERENCES charges(id) ON DELETE CASCADE,
    org_id TEXT NOT NULL DEFAULT 'org_demo_alpha',
    stage TEXT NOT NULL,
    error_reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'resolved', 'ignored')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pipeline_errors_charge_id ON pipeline_errors(charge_id);
CREATE INDEX IF NOT EXISTS idx_pipeline_errors_status ON pipeline_errors(status);
CREATE INDEX IF NOT EXISTS idx_pipeline_errors_org_id ON pipeline_errors(org_id);

-- Enable & force RLS on pipeline_errors
ALTER TABLE pipeline_errors ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_errors FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS org_isolation_policy ON pipeline_errors;
CREATE POLICY org_isolation_policy ON pipeline_errors
    FOR ALL
    USING (org_id = current_setting('app.current_org', true))
    WITH CHECK (org_id = current_setting('app.current_org', true));

-- 3. PERMISSIONS
GRANT ALL ON TABLE overrides TO authenticated;
GRANT ALL ON TABLE pipeline_errors TO authenticated;
