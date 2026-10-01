-- ==============================================================================
-- Migration: 005_evidence_events.sql
-- Product: Recovery Manager - Multi-file Evidence Events & Operational Records
-- Purpose:
--   1. Create evidence_events table for operational evidence (receiving, prep, pack, return, status).
--   2. Index shipment_id for fast temporal matching against financial charges.
--   3. Add unique constraint / idempotency key for safe and idempotent re-uploads.
--   4. Enable and force RLS scoped to org_id.
-- ==============================================================================

CREATE TABLE IF NOT EXISTS evidence_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shipment_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL CHECK (evidence_type IN ('receiving', 'prep', 'pack', 'return', 'status')),
    timestamp TIMESTAMPTZ NOT NULL,
    status TEXT,
    source_file TEXT NOT NULL DEFAULT '',
    raw_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    idempotency_key TEXT UNIQUE,
    org_id TEXT NOT NULL DEFAULT 'org_demo_alpha',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for matching & query performance
CREATE INDEX IF NOT EXISTS idx_evidence_events_shipment_id ON evidence_events(shipment_id);
CREATE INDEX IF NOT EXISTS idx_evidence_events_evidence_type ON evidence_events(evidence_type);
CREATE INDEX IF NOT EXISTS idx_evidence_events_timestamp ON evidence_events(timestamp);
CREATE INDEX IF NOT EXISTS idx_evidence_events_org_id ON evidence_events(org_id);

-- Enable and force Row Level Security (RLS)
ALTER TABLE evidence_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS org_isolation_policy ON evidence_events;
CREATE POLICY org_isolation_policy ON evidence_events
    FOR ALL
    USING (org_id = current_setting('app.current_org', true))
    WITH CHECK (org_id = current_setting('app.current_org', true));

-- Grant permissions to authenticated role
GRANT ALL ON TABLE evidence_events TO authenticated;
