import type {
  HealthResponse,
  DashboardMetricsResponse,
  ChargeListResponse,
  PendingReviewChargesResponse,
  ChargeDetailResponse,
  ClaimListResponse,
  ClaimTraceabilityResponse,
  EvidenceListResponse,
  IngestionResponse,
  PipelineResult,
  BatchProcessResponse,
} from "@/types/api";

function getBaseUrl(): string {
  if (typeof window !== "undefined") {
    // Client-side calls route through Next.js proxy rewrite at /api/backend to avoid CORS
    return "/api/backend";
  }
  // Server-side calls use direct backend URL from environment
  return process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";
}

async function handleResponse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let errorDetail = `Request failed with status ${res.status}`;
    try {
      const errJson = await res.json();
      if (errJson && errJson.detail) {
        errorDetail = typeof errJson.detail === "string" ? errJson.detail : JSON.stringify(errJson.detail);
      }
    } catch {
      const text = await res.text().catch(() => "");
      if (text) errorDetail = text;
    }
    throw new Error(errorDetail);
  }
  return res.json() as Promise<T>;
}

export const DEFAULT_ORG_ID = "org_demo_alpha";

function getHeaders(customHeaders: Record<string, string> = {}): Record<string, string> {
  return {
    "X-Org-Id": DEFAULT_ORG_ID,
    ...customHeaders,
  };
}

export const api = {
  async getHealth(): Promise<HealthResponse> {
    const res = await fetch(`${getBaseUrl()}/health`, { cache: "no-store" });
    return handleResponse<HealthResponse>(res);
  },

  async getDashboardMetrics(orgId: string = DEFAULT_ORG_ID): Promise<DashboardMetricsResponse> {
    const res = await fetch(`${getBaseUrl()}/dashboard/metrics`, {
      cache: "no-store",
      headers: { "X-Org-Id": orgId },
    });
    return handleResponse<DashboardMetricsResponse>(res);
  },

  async getCharges(params?: {
    limit?: number;
    offset?: number;
    status?: string;
  }): Promise<ChargeListResponse> {
    const query = new URLSearchParams();
    if (params?.limit !== undefined) query.set("limit", params.limit.toString());
    if (params?.offset !== undefined) query.set("offset", params.offset.toString());
    if (params?.status) query.set("status", params.status);

    const qs = query.toString();
    const url = `${getBaseUrl()}/charges${qs ? `?${qs}` : ""}`;
    const res = await fetch(url, {
      cache: "no-store",
      headers: getHeaders(),
    });
    return handleResponse<ChargeListResponse>(res);
  },

  async getPendingReviewCharges(): Promise<PendingReviewChargesResponse> {
    const res = await fetch(`${getBaseUrl()}/charges/pending-review`, {
      cache: "no-store",
      headers: getHeaders(),
    });
    return handleResponse<PendingReviewChargesResponse>(res);
  },

  async getChargeDetail(chargeId: string): Promise<ChargeDetailResponse> {
    const res = await fetch(`${getBaseUrl()}/charges/${encodeURIComponent(chargeId)}`, {
      cache: "no-store",
      headers: getHeaders(),
    });
    return handleResponse<ChargeDetailResponse>(res);
  },

  async getClaims(params?: {
    limit?: number;
    offset?: number;
    status?: string;
  }): Promise<ClaimListResponse> {
    const query = new URLSearchParams();
    if (params?.limit !== undefined) query.set("limit", params.limit.toString());
    if (params?.offset !== undefined) query.set("offset", params.offset.toString());
    if (params?.status) query.set("status", params.status);

    const qs = query.toString();
    const url = `${getBaseUrl()}/claims${qs ? `?${qs}` : ""}`;
    const res = await fetch(url, {
      cache: "no-store",
      headers: getHeaders(),
    });
    return handleResponse<ClaimListResponse>(res);
  },

  async getClaimTraceability(claimId: string): Promise<ClaimTraceabilityResponse> {
    const res = await fetch(`${getBaseUrl()}/claims/${encodeURIComponent(claimId)}`, {
      cache: "no-store",
      headers: getHeaders(),
    });
    return handleResponse<ClaimTraceabilityResponse>(res);
  },

  async getEvidence(params?: {
    limit?: number;
    offset?: number;
    source_manager?: string;
    shipment_id?: string;
    order_id?: string;
  }): Promise<EvidenceListResponse> {
    const query = new URLSearchParams();
    if (params?.limit !== undefined) query.set("limit", params.limit.toString());
    if (params?.offset !== undefined) query.set("offset", params.offset.toString());
    if (params?.source_manager) query.set("source_manager", params.source_manager);
    if (params?.shipment_id) query.set("shipment_id", params.shipment_id);
    if (params?.order_id) query.set("order_id", params.order_id);

    const qs = query.toString();
    const url = `${getBaseUrl()}/evidence${qs ? `?${qs}` : ""}`;
    const res = await fetch(url, {
      cache: "no-store",
      headers: getHeaders(),
    });
    return handleResponse<EvidenceListResponse>(res);
  },

  async uploadFile(
    endpoint: "charges" | "reimbursements" | "evidence",
    file: File,
    sourceReport?: string
  ): Promise<IngestionResponse> {
    const formData = new FormData();
    formData.append("file", file);

    const query = new URLSearchParams();
    if (sourceReport) query.set("source_report", sourceReport);
    const qs = query.toString();

    const url = `${getBaseUrl()}/ingestion/${endpoint}${qs ? `?${qs}` : ""}`;
    const res = await fetch(url, {
      method: "POST",
      body: formData,
      headers: {
        "X-Org-Id": DEFAULT_ORG_ID,
      },
    });
    return handleResponse<IngestionResponse>(res);
  },

  async processCharge(chargeId: string): Promise<PipelineResult> {
    const res = await fetch(`${getBaseUrl()}/charges/${encodeURIComponent(chargeId)}/process`, {
      method: "POST",
      headers: getHeaders({
        "Content-Type": "application/json",
      }),
    });
    return handleResponse<PipelineResult>(res);
  },

  async processBatch(chargeIds?: string[]): Promise<BatchProcessResponse> {
    const body: Record<string, any> = {};
    if (chargeIds && chargeIds.length > 0) {
      body.charge_ids = chargeIds;
    }
    const res = await fetch(`${getBaseUrl()}/pipeline/process-batch`, {
      method: "POST",
      headers: getHeaders({
        "Content-Type": "application/json",
      }),
      body: JSON.stringify(body),
    });
    return handleResponse<BatchProcessResponse>(res);
  },

  async overrideCharge(
    chargeId: string,
    payload: { new_verdict: string; reason: string; reviewer_id?: string }
  ): Promise<any> {
    const res = await fetch(`${getBaseUrl()}/charges/${encodeURIComponent(chargeId)}/override`, {
      method: "POST",
      headers: getHeaders({
        "Content-Type": "application/json",
      }),
      body: JSON.stringify(payload),
    });
    return handleResponse<any>(res);
  },

  async getFailedPendingCharges(): Promise<any> {
    const res = await fetch(`${getBaseUrl()}/charges/failed-pending`, {
      cache: "no-store",
      headers: getHeaders(),
    });
    return handleResponse<any>(res);
  },
};

