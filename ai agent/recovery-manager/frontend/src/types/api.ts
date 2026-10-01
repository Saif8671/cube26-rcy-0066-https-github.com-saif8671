/**
 * TypeScript API types matching Phase 8a Read API schemas and live backend responses.
 * Sourced directly from backend/app/schemas/*.py
 */

export interface HealthResponse {
  status: "ok" | "degraded" | string;
  database: "connected" | "disconnected" | string;
  version: string;
  environment: string;
}

export interface DashboardMetricsResponse {
  total_charges: number;
  total_potential_recovery: string | number;
  total_claims: number;
  claims_by_assessment: {
    SUPPORTED: number;
    CONTRADICTED: number;
    SILENT: number;
    UNCERTAIN: number;
    [key: string]: number;
  };
  claims_by_status: {
    READY_FOR_REVIEW: number;
    DUPLICATE: number;
    ALREADY_REIMBURSED: number;
    REJECTED: number;
    APPROVED: number;
    [key: string]: number;
  };
  unprocessed_charges_count: number;
  processed_no_claim_charges_count: number;
  persistence_gap_notice: string | null;
}

export interface ChargeSummary {
  charge_id: string;
  shipment_id: string | null;
  order_id: string | null;
  sku: string | null;
  asin: string | null;
  charge_type: string;
  amount: string | number;
  currency: string;
  charge_date: string;
  source_report: string | null;
  status: string;
  latest_claim_status: string | null;
  latest_claim_id: string | null;
}

export interface ChargeListResponse {
  total: number;
  limit: number;
  offset: number;
  items: ChargeSummary[];
}

export interface PendingReviewChargesResponse {
  total: number;
  items: ChargeSummary[];
  persistence_gap_notice: string | null;
}

export interface ChargeClaimEvidenceItem {
  evidence_id: string;
  source_manager: string;
  evidence_type: string;
  evidence_timestamp: string;
  evidence_content: Record<string, any>;
}

export interface ChargeClaimDetail {
  claim_id: string;
  assessment: string;
  claim_amount: string | number | null;
  confidence: string | number | null;
  explanation: string | null;
  status: string;
  source_manager: string | null;
  created_at: string;
  evidence: ChargeClaimEvidenceItem[];
}

export interface ChargeDetailResponse {
  charge_id: string;
  shipment_id: string | null;
  order_id: string | null;
  sku: string | null;
  asin: string | null;
  charge_type: string;
  amount: string | number;
  currency: string;
  charge_date: string;
  source_report: string | null;
  raw_data: Record<string, any>;
  status: string;
  created_at: string;
  claim: ChargeClaimDetail | null;
  claim_status_explanation: string;
  evidence_retrieval_persisted: boolean;
  persistence_notes: string | null;
}

export interface ClaimSummary {
  claim_id: string;
  charge_id: string;
  assessment: string;
  claim_amount: string | number | null;
  status: string;
  confidence: string | number | null;
  source_manager: string | null;
  created_at: string;
}

export interface ClaimListResponse {
  total: number;
  limit: number;
  offset: number;
  items: ClaimSummary[];
}

export interface TraceableEvidenceItem {
  evidence_id: string;
  source_manager: string;
  evidence_type: string;
  evidence_timestamp: string;
  evidence_content: Record<string, any>;
}

export interface ClaimTraceabilityResponse {
  claim_id: string;
  assessment: string;
  claim_amount: string | number | null;
  confidence: string | number | null;
  explanation: string | null;
  status: string;
  source_manager: string | null;
  created_at: string;

  charge_id: string;
  charge_type: string;
  charge_amount: string | number;
  charge_currency: string;
  charge_date: string;
  charge_status: string;
  sku: string | null;
  asin: string | null;
  shipment_id: string | null;
  order_id: string | null;

  evidence: TraceableEvidenceItem[];
}

export interface EvidenceRecord {
  evidence_id: string;
  source_manager: string;
  shipment_id: string | null;
  order_id: string | null;
  sku: string | null;
  asin: string | null;
  evidence_type: string;
  evidence_content: Record<string, any>;
  evidence_timestamp: string;
  created_at: string;
}

export interface EvidenceListResponse {
  total: number;
  limit: number;
  offset: number;
  items: EvidenceRecord[];
}

export interface IngestionErrorDetail {
  row_index?: number | null;
  identifier?: string | null;
  charge_id?: string | null;
  error_code: string;
  reason: string;
  reason_code: string;
}

export interface IngestionResponse {
  record_type: string;
  total_records: number;
  inserted_count: number;
  failed_count: number;
  accepted_count?: number;
  rejected_count?: number;
  duplicate_count: number;
  inserted_ids: string[];
  errors: IngestionErrorDetail[];
  total_rows?: number;
  accepted?: number;
  rejected?: number;
  rejected_rows?: Array<{ row: number; charge_id?: string | null; reason: string; reason_code: string }>;
  by_reason_code?: Record<string, number>;
}

export interface PipelineResult {
  outcome:
    | "CLAIM_CREATED"
    | "ALREADY_PROCESSED"
    | "NO_CLAIM"
    | "HUMAN_REVIEW"
    | "BLOCKED"
    | "REJECTED_AT_CLAIM_ENGINE"
    | "NOT_FOUND"
    | "ERROR";
  charge_id: string;
  claim_id: string | null;
  status: string | null;
  assessment: string | null;
  claim_amount: string | number | null;
  confidence: number | null;
  reason: string;
  rule_code: string | null;
  decision: string | null;
  evidence_count: number;
  evidence_ids: string[];
}

export interface BatchProcessResponse {
  results: PipelineResult[];
  succeeded: number;
  failed: number;
  already_processed: number;
  total: number;
}

export interface ChargeOverrideRequest {
  new_verdict: string;
  reason: string;
  reviewer_id?: string;
}

export interface ChargeOverrideResponse {
  id: string;
  charge_id: string;
  claim_id: string | null;
  org_id: string;
  original_assessment: string | null;
  original_status: string | null;
  new_verdict: string;
  reason: string;
  reviewer_id: string;
  created_at: string;
  action_taken: string;
}

export interface FailedPendingChargeItem {
  id: string;
  charge_id: string;
  unit_id: string | null;
  fnsku: string | null;
  charge_type: string | null;
  amount: number | null;
  currency: string | null;
  stage: string;
  error_reason: string;
  status: string;
  created_at: string;
}

export interface FailedPendingChargesResponse {
  total: number;
  items: FailedPendingChargeItem[];
}

