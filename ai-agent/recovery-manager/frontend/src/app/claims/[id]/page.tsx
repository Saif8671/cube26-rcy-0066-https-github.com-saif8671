"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  FileCheck2,
  ArrowLeft,
  Receipt,
  Layers,
  Building2,
  Clock,
  ArrowDown,
  ExternalLink,
  ShieldCheck,
  CheckCircle2,
  Info,
  Calendar,
  Package,
} from "lucide-react";
import { api } from "@/lib/api";
import type { ClaimTraceabilityResponse } from "@/types/api";
import { formatCurrency, formatDate } from "@/lib/utils";
import { StatusBadge } from "@/components/common/StatusBadge";
import { AssessmentBadge } from "@/components/common/AssessmentBadge";
import { EvidenceContentViewer } from "@/components/common/EvidenceContentViewer";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { ErrorAlert } from "@/components/common/ErrorAlert";
import { OverrideModal } from "@/components/common/OverrideModal";

export default function ClaimTraceabilityPage() {
  const params = useParams();
  const rawId = params?.id;
  const claimId = Array.isArray(rawId) ? rawId[0] : (rawId as string);

  const [trace, setTrace] = useState<ClaimTraceabilityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showOverrideModal, setShowOverrideModal] = useState(false);

  const fetchTraceability = async () => {
    if (!claimId) return;
    try {
      setLoading(true);
      setError(null);
      const res = await api.getClaimTraceability(claimId);
      setTrace(res);
    } catch (err: any) {
      setError(err?.message || `Failed to retrieve claim traceability for ${claimId}`);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTraceability();
  }, [claimId]);

  if (loading) {
    return <LoadingSpinner message={`Loading end-to-end traceability chain for ${claimId}...`} />;
  }

  if (error || !trace) {
    return (
      <div className="space-y-4">
        <Link
          href="/claims"
          className="inline-flex items-center gap-1.5 text-xs text-slate-500 hover:text-[#131921] transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" /> Back to Claims
        </Link>
        <ErrorAlert message={error || "Claim not found"} onRetry={fetchTraceability} />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Top Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-[#E5E7EB]">
        <div className="flex items-center gap-3">
          <Link
            href="/claims"
            className="p-2 rounded-lg bg-white border border-[#E5E7EB] text-slate-600 hover:text-[#131921] hover:bg-slate-50 transition-colors shadow-xs"
            title="Back to Claims"
          >
            <ArrowLeft className="w-4 h-4" />
          </Link>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold text-[#131921] font-mono">{trace.claim_id}</h1>
              <AssessmentBadge assessment={trace.assessment} />
              <StatusBadge status={trace.status} />
            </div>
            <p className="text-xs text-slate-500 mt-0.5">
              End-to-End Operational Traceability Chain (Rule 5 Audit Trail)
            </p>
          </div>
        </div>

        <div className="flex items-center gap-4">
          <button
            type="button"
            onClick={() => setShowOverrideModal(true)}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-[#FF9900] hover:bg-[#E88A00] text-slate-950 shadow-sm transition-colors cursor-pointer"
          >
            <ShieldCheck className="w-3.5 h-3.5" /> Override Verdict
          </button>
          <div className="text-right">
            <div className="text-xs text-slate-500 uppercase tracking-wider font-semibold">Claim Amount</div>
            <div className="text-2xl font-black text-emerald-700 font-mono">
              {formatCurrency(trace.claim_amount)}
            </div>
          </div>
        </div>
      </div>

      {/* Visual Traceability Banner */}
      <div className="bg-gradient-to-r from-[#F9FAFB] via-white to-[#F9FAFB] border border-[#E5E7EB] rounded-xl p-4 flex items-center justify-between shadow-xs">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-lg bg-[#FF9900]/10 text-[#FF9900] flex items-center justify-center border border-[#FF9900]/30">
            <ShieldCheck className="w-4 h-4" />
          </div>
          <div>
            <div className="text-xs font-bold text-[#131921] uppercase tracking-wider">
              Human Reviewer Provenance Guarantee
            </div>
            <p className="text-xs text-slate-500">
              Deterministic link: Claim → Imposed Charge → Shipment/Order/SKU → Warehouse Proof Findings
            </p>
          </div>
        </div>
      </div>

      {/* Traceability Chain: Step 1 (Claim Level) */}
      <div className="relative">
        <div className="bg-white border border-[#FF9900]/40 rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between pb-3 border-b border-[#E5E7EB]">
            <div className="flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-[#FF9900]/20 text-[#FF9900] font-bold text-xs flex items-center justify-center border border-[#FF9900]/40">
                1
              </span>
              <h2 className="text-sm font-bold text-[#131921] uppercase tracking-wider">
                Dispute Claim Record
              </h2>
            </div>
            <span className="text-xs text-slate-500 font-mono">Created {formatDate(trace.created_at)}</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 my-4 text-xs">
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
              <span className="text-slate-500 block mb-1">Lifecycle Status:</span>
              <StatusBadge status={trace.status} />
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
              <span className="text-slate-500 block mb-1">Decision Assessment:</span>
              <AssessmentBadge assessment={trace.assessment} />
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
              <span className="text-slate-500 block mb-1">Algorithm Confidence:</span>
              <span className="text-[#131921] font-mono font-bold text-sm">
                {trace.confidence ? `${(Number(trace.confidence) * 100).toFixed(0)}%` : "—"}
              </span>
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
              <span className="text-slate-500 block mb-1">Source Department:</span>
              <span className="text-[#131921] font-semibold text-sm">
                {trace.source_manager || "Operations"}
              </span>
            </div>
          </div>

          {trace.explanation && (
            <div className="p-3.5 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB] text-xs text-slate-700 leading-relaxed italic">
              <strong className="not-italic text-slate-500 uppercase tracking-wider text-[11px] block mb-1">
                Dispute Explanation:
              </strong>
              &ldquo;{trace.explanation}&rdquo;
            </div>
          )}
        </div>

        {/* Chain Connector Arrow */}
        <div className="flex justify-center my-3">
          <div className="w-8 h-8 rounded-full bg-white border border-[#E5E7EB] flex items-center justify-center text-[#FF9900] shadow-xs">
            <ArrowDown className="w-4 h-4" />
          </div>
        </div>

        {/* Traceability Chain: Step 2 (Charge Level) */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between pb-3 border-b border-[#E5E7EB]">
            <div className="flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-[#FF9900]/20 text-[#FF9900] font-bold text-xs flex items-center justify-center border border-[#FF9900]/40">
                2
              </span>
              <h2 className="text-sm font-bold text-[#131921] uppercase tracking-wider">
                Underlying Marketplace Fee Charge
              </h2>
            </div>
            <Link
              href={`/charges/${encodeURIComponent(trace.charge_id)}`}
              className="inline-flex items-center gap-1 text-xs text-[#FF9900] hover:text-[#E88A00] font-medium hover:underline"
            >
              Open Charge Detail <ExternalLink className="w-3.5 h-3.5" />
            </Link>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 my-4 text-xs">
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
              <span className="text-slate-500 block mb-1">External Charge ID:</span>
              <span className="font-mono font-bold text-[#131921]">{trace.charge_id}</span>
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
              <span className="text-slate-500 block mb-1">Imposed Fee:</span>
              <span className="font-mono font-bold text-[#131921]">
                {formatCurrency(trace.charge_amount, trace.charge_currency)}
              </span>
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
              <span className="text-slate-500 block mb-1">Charge Date:</span>
              <span className="text-[#131921]">{formatDate(trace.charge_date)}</span>
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
              <span className="text-slate-500 block mb-1">Charge Status:</span>
              <StatusBadge status={trace.charge_status} />
            </div>
          </div>

          <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB] text-xs">
            <span className="text-slate-500 font-medium">Charge Reason / Defect:</span>
            <div className="text-[#131921] font-semibold mt-0.5">{trace.charge_type}</div>
          </div>
        </div>

        {/* Chain Connector Arrow */}
        <div className="flex justify-center my-3">
          <div className="w-8 h-8 rounded-full bg-white border border-[#E5E7EB] flex items-center justify-center text-[#FF9900] shadow-xs">
            <ArrowDown className="w-4 h-4" />
          </div>
        </div>

        {/* Traceability Chain: Step 3 (Shipment & Order Context) */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between pb-3 border-b border-[#E5E7EB]">
            <div className="flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-[#FF9900]/20 text-[#FF9900] font-bold text-xs flex items-center justify-center border border-[#FF9900]/40">
                3
              </span>
              <h2 className="text-sm font-bold text-[#131921] uppercase tracking-wider">
                Shipment, Order & Catalog Context
              </h2>
            </div>
            <span className="text-xs text-slate-500">Deterministic Match Context</span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-4 mt-4 text-xs">
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
              <span className="text-slate-500 block mb-1">Shipment ID:</span>
              {trace.shipment_id ? (
                <Link
                  href={`/evidence?shipment_id=${encodeURIComponent(trace.shipment_id)}`}
                  className="font-mono font-bold text-[#FF9900] hover:underline"
                >
                  {trace.shipment_id}
                </Link>
              ) : (
                <span className="text-slate-400 font-mono">—</span>
              )}
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
              <span className="text-slate-500 block mb-1">Order ID:</span>
              {trace.order_id ? (
                <Link
                  href={`/evidence?order_id=${encodeURIComponent(trace.order_id)}`}
                  className="font-mono font-bold text-[#FF9900] hover:underline"
                >
                  {trace.order_id}
                </Link>
              ) : (
                <span className="text-slate-400 font-mono">—</span>
              )}
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
              <span className="text-slate-500 block mb-1">SKU:</span>
              <span className="font-mono font-bold text-[#131921]">{trace.sku || "—"}</span>
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
              <span className="text-slate-500 block mb-1">ASIN:</span>
              <span className="font-mono font-bold text-[#131921]">{trace.asin || "—"}</span>
            </div>
          </div>
        </div>

        {/* Chain Connector Arrow */}
        <div className="flex justify-center my-3">
          <div className="w-8 h-8 rounded-full bg-white border border-[#E5E7EB] flex items-center justify-center text-[#FF9900] shadow-xs">
            <ArrowDown className="w-4 h-4" />
          </div>
        </div>

        {/* Traceability Chain: Step 4 (Operational Evidence Records) */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-5 shadow-sm">
          <div className="flex items-center justify-between pb-3 border-b border-[#E5E7EB]">
            <div className="flex items-center gap-2">
              <span className="w-6 h-6 rounded-full bg-emerald-500/15 text-emerald-600 font-bold text-xs flex items-center justify-center border border-emerald-500/30">
                4
              </span>
              <h2 className="text-sm font-bold text-[#131921] uppercase tracking-wider">
                Operational Evidence Provenance ({trace.evidence.length} linked records)
              </h2>
            </div>
            <span className="text-xs text-emerald-700 font-medium">Junction: claim_evidence</span>
          </div>

          {trace.evidence.length === 0 ? (
            <p className="text-xs text-slate-500 py-6 text-center italic">
              No linked operational evidence records found.
            </p>
          ) : (
            <div className="space-y-4 mt-4">
              {trace.evidence.map((ev, index) => (
                <div
                  key={ev.evidence_id}
                  className="bg-[#F9FAFB] border border-[#E5E7EB] rounded-xl p-4 space-y-3"
                >
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2 border-b border-[#E5E7EB] text-xs">
                    <div className="flex items-center gap-2">
                      <span className="w-5 h-5 rounded-full bg-slate-200 text-slate-700 font-mono text-[10px] flex items-center justify-center">
                        {index + 1}
                      </span>
                      <span className="font-mono font-bold text-[#131921] text-sm">
                        {ev.evidence_id}
                      </span>
                      <span className="px-2 py-0.5 rounded text-[11px] font-medium bg-blue-500/10 text-blue-600 border border-blue-500/30">
                        {ev.evidence_type}
                      </span>
                    </div>

                    <div className="flex items-center gap-3 text-slate-500 text-xs">
                      <span className="flex items-center gap-1">
                        <Building2 className="w-3.5 h-3.5 text-slate-400" />
                        Manager: <strong className="text-slate-700">{ev.source_manager}</strong>
                      </span>
                      <span className="flex items-center gap-1">
                        <Clock className="w-3.5 h-3.5 text-slate-400" />
                        {formatDate(ev.evidence_timestamp)}
                      </span>
                    </div>
                  </div>

                  {/* Render evidence_content as readable key-value list (never raw dump) */}
                  <EvidenceContentViewer
                    content={ev.evidence_content}
                    title={`${ev.source_manager} Department Audit Findings`}
                  />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {showOverrideModal && (
        <OverrideModal
          isOpen={showOverrideModal}
          onClose={() => setShowOverrideModal(false)}
          chargeId={trace.charge_id}
          claimId={trace.claim_id}
          currentAssessment={trace.assessment}
          onSuccess={fetchTraceability}
        />
      )}
    </div>
  );
}
