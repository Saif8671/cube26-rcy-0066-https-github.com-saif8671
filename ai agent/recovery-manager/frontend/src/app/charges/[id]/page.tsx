"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  Receipt,
  ArrowLeft,
  Calendar,
  Package,
  Layers,
  FileCheck2,
  AlertCircle,
  ExternalLink,
  ShieldAlert,
  Info,
  Clock,
  Building2,
  FileText,
  Zap,
  RefreshCw,
  CheckCircle2,
} from "lucide-react";
import { api } from "@/lib/api";
import type { ChargeDetailResponse, PipelineResult } from "@/types/api";
import { formatCurrency, formatDate } from "@/lib/utils";
import { StatusBadge } from "@/components/common/StatusBadge";
import { AssessmentBadge } from "@/components/common/AssessmentBadge";
import { EvidenceContentViewer } from "@/components/common/EvidenceContentViewer";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { ErrorAlert } from "@/components/common/ErrorAlert";

export default function ChargeDetailPage() {
  const params = useParams();
  const rawId = params?.id;
  const chargeId = Array.isArray(rawId) ? rawId[0] : (rawId as string);

  const [charge, setCharge] = useState<ChargeDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [isProcessing, setIsProcessing] = useState(false);
  const [pipelineResult, setPipelineResult] = useState<PipelineResult | null>(null);
  const [pipelineError, setPipelineError] = useState<string | null>(null);

  const fetchDetail = async () => {
    if (!chargeId) return;
    try {
      setLoading(true);
      setError(null);
      const res = await api.getChargeDetail(chargeId);
      setCharge(res);
    } catch (err: any) {
      setError(err?.message || `Failed to retrieve charge ${chargeId}`);
    } finally {
      setLoading(false);
    }
  };

  const handleRunPipeline = async () => {
    if (!chargeId || isProcessing) return;
    try {
      setIsProcessing(true);
      setPipelineError(null);
      setPipelineResult(null);
      const res = await api.processCharge(chargeId);
      setPipelineResult(res);
      // Refresh charge details so newly created claim and status appear immediately
      const refreshed = await api.getChargeDetail(chargeId);
      setCharge(refreshed);
    } catch (err: any) {
      setPipelineError(err?.message || "Failed to execute recovery pipeline.");
    } finally {
      setIsProcessing(false);
    }
  };

  useEffect(() => {
    fetchDetail();
  }, [chargeId]);

  if (loading) {
    return <LoadingSpinner message={`Loading charge details for ${chargeId}...`} />;
  }

  if (error || !charge) {
    return (
      <div className="space-y-4">
        <Link
          href="/charges"
          className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-[#131921] transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Back to Charges
        </Link>
        <ErrorAlert message={error || "Charge not found"} onRetry={fetchDetail} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Top Navigation & Status */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-[#E5E7EB]">
        <div className="flex items-center gap-3">
          <Link
            href="/charges"
            className="p-2 rounded-lg bg-white border border-[#E5E7EB] text-slate-600 hover:text-[#131921] hover:bg-slate-50 transition-colors shadow-xs"
            title="Back to Charges"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-[#131921] font-mono">{charge.charge_id}</h1>
              <StatusBadge status={charge.status} />
              {charge.claim && <StatusBadge status={charge.claim.status} />}
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              Marketplace Fee Detail & Recovery Evaluation
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={handleRunPipeline}
            disabled={isProcessing}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold bg-[#FF9900] hover:bg-[#E88A00] disabled:opacity-50 text-slate-950 shadow-sm transition-all border border-[#FF9900]/60 cursor-pointer"
          >
            {isProcessing ? (
              <>
                <RefreshCw className="w-3.5 h-3.5 animate-spin text-slate-950" />
                Evaluating...
              </>
            ) : (
              <>
                <Zap className="w-3.5 h-3.5 text-slate-950 fill-slate-950" />
                Run Recovery Pipeline
              </>
            )}
          </button>

          <div className="text-right">
            <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Fee Amount</div>
            <div className="text-2xl font-black text-[#131921] font-mono">
              {formatCurrency(charge.amount, charge.currency)}
            </div>
          </div>
        </div>
      </div>

      {/* Pipeline Execution Result Alert */}
      {pipelineResult && (
        <div
          className={`p-4 rounded-xl border flex items-start gap-3 shadow-sm ${
            pipelineResult.outcome === "CLAIM_CREATED"
              ? "bg-emerald-50 border-emerald-300 text-emerald-800"
              : pipelineResult.outcome === "ALREADY_PROCESSED"
              ? "bg-blue-50 border-blue-300 text-blue-800"
              : pipelineResult.outcome === "HUMAN_REVIEW"
              ? "bg-amber-50 border-amber-300 text-amber-800"
              : pipelineResult.outcome === "BLOCKED"
              ? "bg-purple-50 border-purple-300 text-purple-800"
              : "bg-slate-50 border-slate-300 text-slate-700"
          }`}
        >
          {pipelineResult.outcome === "CLAIM_CREATED" ? (
            <CheckCircle2 className="w-5 h-5 text-emerald-400 shrink-0 mt-0.5" />
          ) : pipelineResult.outcome === "HUMAN_REVIEW" ? (
            <ShieldAlert className="w-5 h-5 text-amber-400 shrink-0 mt-0.5" />
          ) : (
            <Zap className="w-5 h-5 text-blue-400 shrink-0 mt-0.5" />
          )}
          <div className="flex-1 space-y-1 text-xs">
            <div className="flex items-center gap-2 font-bold uppercase tracking-wider">
              <span>Pipeline Outcome: {pipelineResult.outcome}</span>
              {pipelineResult.claim_id && (
                <span className="font-mono text-[#131921] bg-white px-2 py-0.5 rounded border border-[#E5E7EB]">
                  {pipelineResult.claim_id}
                </span>
              )}
              {pipelineResult.assessment && (
                <span className="font-mono">{pipelineResult.assessment}</span>
              )}
              {pipelineResult.claim_amount && (
                <span className="font-mono text-emerald-700 font-bold">
                  {formatCurrency(pipelineResult.claim_amount)}
                </span>
              )}
            </div>
            <p className="leading-relaxed opacity-80">{pipelineResult.reason}</p>
            {pipelineResult.evidence_count > 0 && (
              <p className="text-[11px] opacity-70 font-mono">
                Evaluated {pipelineResult.evidence_count} operational evidence record(s):{" "}
                {pipelineResult.evidence_ids.join(", ")}
              </p>
            )}
          </div>
        </div>
      )}

      {/* Pipeline Error Alert */}
      {pipelineError && (
        <ErrorAlert
          message={`Pipeline execution failed: ${pipelineError}`}
          onRetry={handleRunPipeline}
        />
      )}


      {/* Charge Metadata Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Shipment / Order */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-4 shadow-xs">
          <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider block mb-2">
            Containers & Orders
          </span>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-slate-500">Shipment ID:</span>
              {charge.shipment_id ? (
                <Link
                  href={`/evidence?shipment_id=${encodeURIComponent(charge.shipment_id)}`}
                  className="font-mono font-medium text-[#FF9900] hover:underline inline-flex items-center gap-1"
                >
                  {charge.shipment_id}
                  <ExternalLink className="w-3 h-3" />
                </Link>
              ) : (
                <span className="text-slate-400 font-mono">—</span>
              )}
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Order ID:</span>
              {charge.order_id ? (
                <Link
                  href={`/evidence?order_id=${encodeURIComponent(charge.order_id)}`}
                  className="font-mono font-medium text-[#FF9900] hover:underline inline-flex items-center gap-1"
                >
                  {charge.order_id}
                  <ExternalLink className="w-3 h-3" />
                </Link>
              ) : (
                <span className="text-slate-400 font-mono">—</span>
              )}
            </div>
          </div>
        </div>

        {/* Product Identifiers */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-4 shadow-xs">
          <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider block mb-2">
            Catalog Identifiers
          </span>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-slate-500">SKU:</span>
              <span className="font-mono font-medium text-[#131921]">{charge.sku || "—"}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">ASIN:</span>
              <span className="font-mono text-[#131921]">{charge.asin || "—"}</span>
            </div>
          </div>
        </div>

        {/* Temporal Record */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-4 shadow-xs">
          <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider block mb-2">
            Timestamps
          </span>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-slate-500">Charge Date:</span>
              <span className="text-[#131921]">{formatDate(charge.charge_date)}</span>
            </div>
            <div className="flex justify-between">
              <span className="text-slate-500">Ingested At:</span>
              <span className="text-slate-500">{formatDate(charge.created_at)}</span>
            </div>
          </div>
        </div>

        {/* Source & Fee Type */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-4 shadow-xs">
          <span className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider block mb-2">
            Source & Classification
          </span>
          <div className="space-y-1 text-xs">
            <div className="flex justify-between">
              <span className="text-slate-500">Source Report:</span>
              <span className="font-mono text-[11px] text-slate-700 truncate max-w-[140px]" title={charge.source_report || "Direct"}>
                {charge.source_report || "Direct"}
              </span>
            </div>
            <div className="text-[#131921] font-medium truncate" title={charge.charge_type}>
              {charge.charge_type}
            </div>
          </div>
        </div>
      </div>

      {/* Claim & Recovery Status Evaluation */}
      <div className="bg-white border border-[#E5E7EB] rounded-xl p-5 space-y-4 shadow-xs">
        <div className="flex items-center justify-between pb-3 border-b border-[#E5E7EB]">
          <div className="flex items-center gap-2">
            <FileCheck2 className="w-5 h-5 text-[#FF9900]" />
            <h2 className="text-sm font-bold text-[#131921] uppercase tracking-wider">
              Dispute Pipeline & Claim Lifecycle
            </h2>
          </div>
          {charge.claim && (
            <Link
              href={`/claims/${encodeURIComponent(charge.claim.claim_id)}`}
              className="inline-flex items-center gap-1.5 text-xs text-[#FF9900] hover:text-[#E88A00] font-medium hover:underline"
            >
              Full Traceability Chain <ExternalLink className="w-3.5 h-3.5" />
            </Link>
          )}
        </div>

        {/* Plain-English Claim Status Explanation (derived from real DB state) */}
        <div className={`p-4 rounded-xl border flex items-start gap-3 ${
          charge.claim
            ? "bg-emerald-50 border-emerald-200 text-emerald-800"
            : "bg-slate-50 border-[#E5E7EB] text-slate-700"
        }`}>
          <Info className={`w-5 h-5 shrink-0 mt-0.5 ${charge.claim ? "text-emerald-400" : "text-blue-400"}`} />
          <div className="flex-1">
            <h4 className="text-xs font-bold uppercase tracking-wider mb-1">
              System Assessment Explanation
            </h4>
            <p className="text-xs leading-relaxed font-sans">{charge.claim_status_explanation}</p>
          </div>
        </div>

        {/* Case 1: Claim Exists */}
        {charge.claim ? (
          <div className="space-y-4 mt-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
              <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
                <span className="text-slate-500 block mb-1">Claim Identifier:</span>
                <span className="font-mono font-bold text-[#131921] text-sm">
                  {charge.claim.claim_id}
                </span>
              </div>
              <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
                <span className="text-slate-500 block mb-1">Assessment:</span>
                <AssessmentBadge assessment={charge.claim.assessment} />
              </div>
              <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
                <span className="text-slate-500 block mb-1">Claim Amount:</span>
                <span className="font-mono font-bold text-emerald-700 text-sm">
                  {formatCurrency(charge.claim.claim_amount)}
                </span>
              </div>
              <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
                <span className="text-slate-500 block mb-1">Confidence Score:</span>
                <span className="font-mono font-bold text-[#131921] text-sm">
                  {charge.claim.confidence ? `${(Number(charge.claim.confidence) * 100).toFixed(0)}%` : "—"}
                </span>
              </div>
            </div>

            {charge.claim.explanation && (
              <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB] text-xs">
                <span className="text-slate-500 font-semibold uppercase tracking-wider text-[11px] block mb-1">
                  Dispute Rationale:
                </span>
                <p className="text-slate-700 italic leading-relaxed">
                  &ldquo;{charge.claim.explanation}&rdquo;
                </p>
              </div>
            )}

            {/* Linked Evidence Section */}
            <div className="pt-2">
              <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider mb-3 flex items-center gap-2">
                <Layers className="w-4 h-4 text-blue-500" />
                Operational Evidence Provenance ({charge.claim.evidence.length} items)
              </h3>

              {charge.claim.evidence.length === 0 ? (
                <p className="text-xs text-slate-500 italic">
                  No evidence junction rows linked to this claim.
                </p>
              ) : (
                <div className="space-y-3">
                  {charge.claim.evidence.map((ev) => (
                    <div
                      key={ev.evidence_id}
                      className="bg-[#F9FAFB] border border-[#E5E7EB] rounded-xl p-4 space-y-3"
                    >
                      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2 border-b border-[#E5E7EB] text-xs">
                        <div className="flex items-center gap-2">
                          <span className="font-mono font-bold text-[#131921]">
                            {ev.evidence_id}
                          </span>
                          <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-blue-500/10 text-blue-600 border border-blue-500/30">
                            {ev.evidence_type}
                          </span>
                        </div>
                        <div className="flex items-center gap-3 text-slate-500 text-[11px]">
                          <span className="flex items-center gap-1">
                            <Building2 className="w-3.5 h-3.5" />
                            Manager: <strong className="text-slate-700">{ev.source_manager}</strong>
                          </span>
                          <span className="flex items-center gap-1">
                            <Clock className="w-3.5 h-3.5" />
                            {formatDate(ev.evidence_timestamp)}
                          </span>
                        </div>
                      </div>

                      {/* Structured Findings */}
                      <EvidenceContentViewer
                        content={ev.evidence_content}
                        title={`${ev.source_manager} Department Findings`}
                      />
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : (
          /* Case 2: No Claim Exists */
          <div className="space-y-3 pt-2">
            {charge.status === "PENDING" && (
              <div className="p-4 bg-blue-50 border border-blue-200 rounded-xl flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
                <div>
                  <h4 className="font-bold text-blue-700 uppercase tracking-wider mb-1 flex items-center gap-1.5">
                    <Zap className="w-4 h-4 text-blue-600" />
                    Pending Recovery Evaluation
                  </h4>
                  <p className="text-slate-700 leading-relaxed">
                    This charge is in PENDING status. Trigger the synchronous 4-phase pipeline (Evidence → AI Reasoning → Rule Validation → Claim Engine) to evaluate dispute eligibility.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={handleRunPipeline}
                  disabled={isProcessing}
                  className="inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold bg-blue-600 hover:bg-blue-500 disabled:bg-blue-900/60 disabled:text-slate-400 text-white shrink-0 shadow-sm transition-all"
                >
                  {isProcessing ? (
                    <>
                      <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                      Evaluating...
                    </>
                  ) : (
                    <>
                      <Zap className="w-3.5 h-3.5 text-amber-300" />
                      Evaluate Charge
                    </>
                  )}
                </button>
              </div>
            )}

            {charge.persistence_notes && (
              <div className="p-3 bg-slate-50 rounded-lg border border-[#E5E7EB] text-xs text-slate-600 flex items-start gap-2">
                <Info className="w-4 h-4 text-slate-400 shrink-0 mt-0.5" />
                <p>{charge.persistence_notes}</p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* Raw Report Ingestion Data */}
      {charge.raw_data && Object.keys(charge.raw_data).length > 0 && (
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-5 shadow-xs">
          <div className="flex items-center gap-2 pb-2 mb-3 border-b border-[#E5E7EB]">
            <FileText className="w-4 h-4 text-slate-500" />
            <h3 className="text-xs font-bold text-slate-700 uppercase tracking-wider">
              Ingested Report Raw Payload
            </h3>
          </div>
          <EvidenceContentViewer content={charge.raw_data} title="Raw Marketplace Attributes" />
        </div>
      )}
    </div>
  );
}
