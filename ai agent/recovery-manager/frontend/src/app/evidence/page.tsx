"use client";

import React, { useEffect, useState, useTransition } from "react";
import { Database, Filter, RefreshCw, Building2, Search, X } from "lucide-react";
import { api } from "@/lib/api";
import type { EvidenceListResponse, EvidenceRecord } from "@/types/api";
import { formatDate } from "@/lib/utils";
import { EvidenceContentViewer } from "@/components/common/EvidenceContentViewer";
import { Pagination } from "@/components/common/Pagination";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { ErrorAlert } from "@/components/common/ErrorAlert";

export default function EvidencePage() {
  const [data, setData] = useState<EvidenceListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [limit, setLimit] = useState(10);
  const [offset, setOffset] = useState(0);

  // Filters
  const [sourceManagerFilter, setSourceManagerFilter] = useState("");
  const [shipmentFilter, setShipmentFilter] = useState("");
  const [orderFilter, setOrderFilter] = useState("");
  const [isPending, startTransition] = useTransition();

  const fetchEvidence = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.getEvidence({
        limit,
        offset,
        source_manager: sourceManagerFilter.trim() || undefined,
        shipment_id: shipmentFilter.trim() || undefined,
        order_id: orderFilter.trim() || undefined,
      });
      setData(res);
    } catch (err: any) {
      setError(err?.message || "Failed to load operational evidence records.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchEvidence();
  }, [limit, offset, sourceManagerFilter, shipmentFilter, orderFilter]);

  const resetFilters = () => {
    setSourceManagerFilter("");
    setShipmentFilter("");
    setOrderFilter("");
    setOffset(0);
  };

  const hasActiveFilters = Boolean(sourceManagerFilter || shipmentFilter || orderFilter);

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-[#E5E7EB]">
        <div>
          <h1 className="text-2xl font-bold text-[#131921] tracking-tight flex items-center gap-2.5">
            <Database className="w-6 h-6 text-[#FF9900]" />
            Operational Evidence Registry
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Browse and filter deterministic warehouse audit findings, packaging checks, and dock receipts
          </p>
        </div>

        <button
          type="button"
          onClick={() => startTransition(fetchEvidence)}
          disabled={isPending}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-white hover:bg-slate-50 text-slate-700 border border-[#E5E7EB] hover:border-[#FF9900]/40 transition-all self-start sm:self-auto shadow-xs"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isPending ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Filter Toolbar */}
      <div className="bg-white border border-[#E5E7EB] rounded-xl p-4 shadow-xs">
        <div className="flex items-center justify-between mb-3 text-xs">
          <div className="flex items-center gap-2 font-semibold text-slate-700">
            <Filter className="w-3.5 h-3.5 text-[#FF9900]" />
            Filter Evidence Records
          </div>
          {hasActiveFilters && (
            <button
              type="button"
              onClick={resetFilters}
              className="inline-flex items-center gap-1 text-[11px] text-slate-500 hover:text-[#131921] transition-colors cursor-pointer"
            >
              <X className="w-3 h-3" /> Clear Filters
            </button>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
          {/* Source Manager */}
          <div>
            <label className="block text-[11px] text-slate-500 mb-1 font-medium">Department Manager</label>
            <select
              value={sourceManagerFilter}
              onChange={(e) => {
                setSourceManagerFilter(e.target.value);
                setOffset(0);
              }}
              className="w-full bg-white border border-[#E5E7EB] rounded-lg px-3 py-1.5 text-[#131921] focus:outline-none focus:border-[#FF9900]"
            >
              <option value="">All Managers</option>
              <option value="Receiving">Receiving</option>
              <option value="Prep">Prep</option>
              <option value="Pack">Pack</option>
            </select>
          </div>

          {/* Shipment ID */}
          <div>
            <label className="block text-[11px] text-slate-500 mb-1 font-medium">Shipment ID</label>
            <div className="relative">
              <input
                type="text"
                placeholder="e.g. FBA17Z88Y12"
                value={shipmentFilter}
                onChange={(e) => {
                  setShipmentFilter(e.target.value);
                  setOffset(0);
                }}
                className="w-full bg-white border border-[#E5E7EB] rounded-lg px-3 py-1.5 text-[#131921] placeholder:text-slate-400 focus:outline-none focus:border-[#FF9900] font-mono"
              />
              {shipmentFilter && (
                <button
                  type="button"
                  onClick={() => setShipmentFilter("")}
                  className="absolute right-2 top-2 text-slate-400 hover:text-slate-700"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>

          {/* Order ID */}
          <div>
            <label className="block text-[11px] text-slate-500 mb-1 font-medium">Order ID</label>
            <div className="relative">
              <input
                type="text"
                placeholder="e.g. 111-2000001-0000001"
                value={orderFilter}
                onChange={(e) => {
                  setOrderFilter(e.target.value);
                  setOffset(0);
                }}
                className="w-full bg-white border border-[#E5E7EB] rounded-lg px-3 py-1.5 text-[#131921] placeholder:text-slate-400 focus:outline-none focus:border-[#FF9900] font-mono"
              />
              {orderFilter && (
                <button
                  type="button"
                  onClick={() => setOrderFilter("")}
                  className="absolute right-2 top-2 text-slate-400 hover:text-slate-700"
                >
                  <X className="w-3 h-3" />
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {loading && !data && <LoadingSpinner message="Querying evidence records..." />}

      {error && <ErrorAlert message={error} onRetry={fetchEvidence} />}

      {data && (
        <div className="space-y-4">
          <div className="bg-white border border-[#E5E7EB] rounded-xl overflow-hidden shadow-xs">
            <div className="divide-y divide-[#E5E7EB]">
              {data.items.length === 0 ? (
                <div className="py-16 text-center text-slate-500 text-xs">
                  No evidence records match the current filter criteria.
                </div>
              ) : (
                data.items.map((ev) => (
                  <div key={ev.evidence_id} className="p-4 hover:bg-slate-50/80 transition-colors space-y-3">
                    <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2 border-b border-[#E5E7EB] text-xs">
                      <div className="flex items-center gap-3">
                        <span className="font-mono font-bold text-[#131921] text-sm">
                          {ev.evidence_id}
                        </span>
                        <span className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-500/10 text-blue-600 border border-blue-500/30">
                          {ev.evidence_type}
                        </span>
                        <span className="inline-flex items-center gap-1 text-slate-600 bg-slate-100 px-2 py-0.5 rounded text-[11px] border border-slate-200">
                          <Building2 className="w-3 h-3 text-slate-400" />
                          {ev.source_manager}
                        </span>
                      </div>

                      <div className="text-slate-500 text-[11px] font-mono">
                        Proof Timestamp: <strong className="text-slate-700">{formatDate(ev.evidence_timestamp)}</strong>
                      </div>
                    </div>

                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs py-1">
                      <div>
                        <span className="text-slate-400 block text-[10px]">Shipment:</span>
                        <span className="font-mono text-[#131921]">{ev.shipment_id || "—"}</span>
                      </div>
                      <div>
                        <span className="text-slate-400 block text-[10px]">Order:</span>
                        <span className="font-mono text-[#131921]">{ev.order_id || "—"}</span>
                      </div>
                      <div>
                        <span className="text-slate-400 block text-[10px]">SKU:</span>
                        <span className="font-mono text-[#131921]">{ev.sku || "—"}</span>
                      </div>
                      <div>
                        <span className="text-slate-400 block text-[10px]">ASIN:</span>
                        <span className="font-mono text-[#131921]">{ev.asin || "—"}</span>
                      </div>
                    </div>

                    {/* Structured Findings Viewer */}
                    <EvidenceContentViewer
                      content={ev.evidence_content}
                      title={`${ev.source_manager} Recorded Findings`}
                    />
                  </div>
                ))
              )}
            </div>

            <Pagination
              total={data.total}
              limit={limit}
              offset={offset}
              onPageChange={(newOffset) => setOffset(newOffset)}
              onLimitChange={(newLimit) => {
                setLimit(newLimit);
                setOffset(0);
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
