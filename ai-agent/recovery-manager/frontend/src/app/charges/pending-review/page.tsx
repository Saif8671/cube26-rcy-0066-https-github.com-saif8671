"use client";

import React, { useEffect, useState, useTransition } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Receipt,
  ArrowUpRight,
  RefreshCw,
  Info,
  Clock,
  ShieldAlert,
  HelpCircle,
} from "lucide-react";
import { api } from "@/lib/api";
import type { PendingReviewChargesResponse } from "@/types/api";
import { formatCurrency, formatDate } from "@/lib/utils";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { ErrorAlert } from "@/components/common/ErrorAlert";
import { OverrideModal } from "@/components/common/OverrideModal";
import type { ChargeSummary } from "@/types/api";

export default function PendingReviewPage() {
  const [data, setData] = useState<PendingReviewChargesResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();
  const [selectedChargeForOverride, setSelectedChargeForOverride] = useState<ChargeSummary | null>(null);

  const fetchPending = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.getPendingReviewCharges();
      setData(res);
    } catch (err: any) {
      setError(err?.message || "Failed to load pending review charges.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPending();
  }, []);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-[#E5E7EB]">
        <div>
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-amber-500/10 text-amber-600 flex items-center justify-center border border-amber-500/30">
              <AlertTriangle className="w-4 h-4" />
            </div>
            <h1 className="text-2xl font-bold text-[#131921] tracking-tight">
              Charges Pending Human Review
            </h1>
            {data && (
              <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-500/15 text-amber-700 border border-amber-400/40 font-mono">
                {data.total} {data.total === 1 ? "case" : "cases"}
              </span>
            )}
          </div>
          <p className="text-xs text-slate-500 mt-1">
            Charges with conflicting or ambiguous operational proof requiring supervisor inspection
          </p>
        </div>

        <button
          type="button"
          onClick={() => startTransition(fetchPending)}
          disabled={isPending}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-white hover:bg-slate-50 text-slate-700 border border-[#E5E7EB] hover:border-[#FF9900]/40 transition-all self-start sm:self-auto shadow-xs"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isPending ? "animate-spin" : ""}`} />
          Refresh Queue
        </button>
      </div>

      {/* Operational Notice Banner */}
      <div className="bg-amber-50 border border-amber-300 rounded-xl p-4 flex items-start gap-3">
        <ShieldAlert className="w-5 h-5 text-amber-600 shrink-0 mt-0.5" />
        <div className="text-xs space-y-1">
          <div className="font-bold text-amber-700 uppercase tracking-wider">
            Review Protocol & Read-Only Notice
          </div>
          <p className="text-amber-700/90 leading-relaxed">
            These charges received an <strong>UNCERTAIN</strong> evaluation during automated reasoning
            (for example, conflicting evidence between packing audits and dock arrival logs) and
            have no generated claim. Resolution and claim approval mutation endpoints are scheduled for future phases;
            this console provides complete read-only traceability for audit verification.
          </p>
        </div>
      </div>

      {loading && !data && <LoadingSpinner message="Checking pending review queue..." />}

      {error && <ErrorAlert message={error} onRetry={fetchPending} />}

      {data && (
        <div>
          {data.items.length === 0 ? (
            <div className="bg-white border border-[#E5E7EB] rounded-xl p-12 text-center shadow-xs">
              <div className="w-12 h-12 rounded-full bg-emerald-500/10 text-emerald-600 flex items-center justify-center mx-auto mb-3 border border-emerald-500/20">
                <ShieldAlert className="w-6 h-6" />
              </div>
              <h3 className="text-sm font-bold text-[#131921]">Review Queue Empty</h3>
              <p className="text-xs text-slate-500 max-w-md mx-auto mt-1">
                There are currently zero charges flagged with UNCERTAIN evaluations awaiting human supervisor resolution.
              </p>
            </div>
          ) : (
            <div className="grid grid-cols-1 gap-4">
              {data.items.map((item) => (
                <div
                  key={item.charge_id}
                  className="bg-white border-2 border-amber-300 hover:border-amber-400 rounded-xl p-5 shadow-sm transition-all"
                >
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-3 border-b border-[#E5E7EB]">
                    <div className="flex items-center gap-3">
                      <span className="font-mono font-black text-[#131921] text-base">
                        {item.charge_id}
                      </span>
                      <span className="px-2.5 py-0.5 rounded-full text-xs font-bold bg-amber-500/15 text-amber-700 border border-amber-400/40">
                        UNCERTAIN ASSESSMENT
                      </span>
                      <span className="px-2 py-0.5 rounded text-[11px] font-mono bg-slate-100 text-slate-700 border border-[#E5E7EB]">
                        Status: {item.status}
                      </span>
                    </div>

                    <div className="flex items-center gap-4">
                      <div className="text-right">
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider block">
                          Charge Amount
                        </span>
                        <span className="font-mono font-bold text-[#131921] text-base">
                          {formatCurrency(item.amount, item.currency)}
                        </span>
                      </div>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => setSelectedChargeForOverride(item)}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-bold bg-[#FF9900] hover:bg-[#E88A00] text-slate-950 shadow-sm transition-colors cursor-pointer"
                        >
                          <ShieldAlert className="w-3.5 h-3.5" /> Override
                        </button>
                        <Link
                          href={`/charges/${encodeURIComponent(item.charge_id)}`}
                          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-white hover:bg-slate-50 text-slate-700 border border-[#E5E7EB] transition-colors shadow-xs"
                        >
                          Inspect Full Audit <ArrowUpRight className="w-3.5 h-3.5" />
                        </Link>
                      </div>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 py-3 text-xs border-b border-[#E5E7EB]">
                    <div>
                      <span className="text-slate-500 block text-[11px]">Fee Type:</span>
                      <span className="font-medium text-[#131921]">{item.charge_type}</span>
                    </div>
                    <div>
                      <span className="text-slate-500 block text-[11px]">Shipment / Order:</span>
                      <span className="font-mono text-slate-700">
                        {item.shipment_id || "—"} {item.order_id ? `(${item.order_id})` : ""}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-500 block text-[11px]">SKU / ASIN:</span>
                      <span className="font-mono text-slate-700">
                        {item.sku || "—"} {item.asin ? `(${item.asin})` : ""}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-500 block text-[11px]">Charge Date:</span>
                      <span className="text-slate-600">{formatDate(item.charge_date)}</span>
                    </div>
                  </div>

                  <div className="pt-3 flex items-start gap-2 text-xs text-amber-700">
                    <Info className="w-4 h-4 text-amber-600 shrink-0 mt-0.5" />
                    <p className="leading-relaxed">
                      <strong>Human Review Context:</strong> Click <em>Override</em> to capture an operator verdict and create a claim or mark rejected, or <em>Inspect Full Audit</em> to examine the conflicting evidence findings.
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {selectedChargeForOverride && (
        <OverrideModal
          isOpen={!!selectedChargeForOverride}
          onClose={() => setSelectedChargeForOverride(null)}
          chargeId={selectedChargeForOverride.charge_id}
          claimId={selectedChargeForOverride.latest_claim_id}
          currentAssessment="UNCERTAIN"
          onSuccess={fetchPending}
        />
      )}
    </div>
  );
}
