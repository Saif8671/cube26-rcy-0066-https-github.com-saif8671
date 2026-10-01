"use client";

import React, { useEffect, useState, useTransition } from "react";
import Link from "next/link";
import { Receipt, Filter, ArrowUpRight, RefreshCw, AlertCircle, Zap } from "lucide-react";
import { api } from "@/lib/api";
import type { ChargeListResponse, ChargeSummary } from "@/types/api";
import { formatCurrency, formatDate } from "@/lib/utils";
import { StatusBadge } from "@/components/common/StatusBadge";
import { Pagination } from "@/components/common/Pagination";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { ErrorAlert } from "@/components/common/ErrorAlert";

export default function ChargesPage() {
  const [data, setData] = useState<ChargeListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [limit, setLimit] = useState(10);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [isPending, startTransition] = useTransition();
  const [processingId, setProcessingId] = useState<string | null>(null);

  const handleProcessCharge = async (chargeId: string) => {
    try {
      setProcessingId(chargeId);
      await api.processCharge(chargeId);
      await fetchCharges();
    } catch (err: any) {
      setError(err?.message || `Failed to process charge ${chargeId}`);
    } finally {
      setProcessingId(null);
    }
  };

  const fetchCharges = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.getCharges({
        limit,
        offset,
        status: statusFilter || undefined,
      });
      setData(res);
    } catch (err: any) {
      setError(err?.message || "Failed to load marketplace charges.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCharges();
  }, [limit, offset, statusFilter]);

  const handleFilterChange = (newStatus: string) => {
    setStatusFilter(newStatus);
    setOffset(0); // Reset to page 1 on filter change
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-[#E5E7EB]">
        <div>
          <h1 className="text-2xl font-bold text-[#131921] tracking-tight flex items-center gap-2.5">
            <Receipt className="w-6 h-6 text-[#FF9900]" />
            Marketplace Charges
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Browse and audit inbound marketplace fees, fee categories, and associated dispute claim lifecycles
          </p>
        </div>

        <div className="flex items-center gap-3">
          {/* Status Filter */}
          <div className="flex items-center gap-2 bg-white border border-[#E5E7EB] rounded-lg px-3 py-1.5 text-xs text-slate-700 shadow-xs">
            <Filter className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-slate-400">Status:</span>
            <select
              value={statusFilter}
              onChange={(e) => handleFilterChange(e.target.value)}
              className="bg-transparent text-[#131921] font-medium focus:outline-none cursor-pointer"
            >
              <option value="" className="bg-white text-slate-800">All Charges</option>
              <option value="PROCESSED" className="bg-white text-slate-800">PROCESSED</option>
              <option value="PENDING" className="bg-white text-slate-800">PENDING</option>
            </select>
          </div>

          <button
            type="button"
            onClick={() => startTransition(fetchCharges)}
            disabled={isPending}
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-white hover:bg-slate-50 text-slate-700 border border-[#E5E7EB] hover:border-[#FF9900]/40 transition-all shadow-xs"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isPending ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {loading && !data && <LoadingSpinner message="Fetching charges from database..." />}

      {error && <ErrorAlert message={error} onRetry={fetchCharges} />}

      {data && (
        <div className="bg-white border border-[#E5E7EB] rounded-xl overflow-hidden shadow-xs">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#F9FAFB] border-b border-[#E5E7EB] text-slate-500 font-semibold uppercase tracking-wider text-[11px]">
                <tr>
                  <th className="py-3 px-4">Charge ID</th>
                  <th className="py-3 px-4">Shipment / Order</th>
                  <th className="py-3 px-4">SKU / ASIN</th>
                  <th className="py-3 px-4">Charge Type</th>
                  <th className="py-3 px-4 text-right">Fee Amount</th>
                  <th className="py-3 px-4">Charge Date</th>
                  <th className="py-3 px-4 text-center">Status</th>
                  <th className="py-3 px-4 text-center">Claim Status</th>
                  <th className="py-3 px-4 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E5E7EB] text-slate-700">
                {data.items.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-12 text-center text-slate-500">
                      No charges found matching the current filters.
                    </td>
                  </tr>
                ) : (
                  data.items.map((item) => (
                    <tr
                      key={item.charge_id}
                      className="hover:bg-slate-50/80 transition-colors group"
                    >
                      {/* Charge ID */}
                      <td className="py-3.5 px-4 font-mono font-bold text-[#131921]">
                        <Link
                          href={`/charges/${encodeURIComponent(item.charge_id)}`}
                          className="hover:text-[#FF9900] hover:underline inline-flex items-center gap-1 text-[#131921]"
                        >
                          {item.charge_id}
                        </Link>
                      </td>

                      {/* Shipment / Order */}
                      <td className="py-3.5 px-4">
                        <div className="font-mono text-slate-800 font-medium">
                          {item.shipment_id || "—"}
                        </div>
                        {item.order_id && (
                          <div className="font-mono text-[10px] text-slate-500 mt-0.5">
                            {item.order_id}
                          </div>
                        )}
                      </td>

                      {/* SKU / ASIN */}
                      <td className="py-3.5 px-4">
                        <div className="font-mono font-medium text-slate-800">
                          {item.sku || "—"}
                        </div>
                        {item.asin && (
                          <div className="font-mono text-[10px] text-slate-500">
                            {item.asin}
                          </div>
                        )}
                      </td>

                      {/* Charge Type */}
                      <td className="py-3.5 px-4 max-w-xs">
                        <div className="font-medium text-slate-800 line-clamp-2">
                          {item.charge_type}
                        </div>
                      </td>

                      {/* Amount */}
                      <td className="py-3.5 px-4 text-right font-mono font-bold text-[#131921]">
                        {formatCurrency(item.amount, item.currency)}
                      </td>

                      {/* Date */}
                      <td className="py-3.5 px-4 text-slate-500 whitespace-nowrap">
                        {formatDate(item.charge_date)}
                      </td>

                      {/* Processing Status */}
                      <td className="py-3.5 px-4 text-center whitespace-nowrap">
                        <StatusBadge status={item.status} />
                      </td>

                      {/* Latest Claim Status */}
                      <td className="py-3.5 px-4 text-center whitespace-nowrap">
                        {item.latest_claim_status ? (
                          <div className="flex flex-col items-center gap-1">
                            <StatusBadge status={item.latest_claim_status} />
                            {item.latest_claim_id && (
                              <span className="font-mono text-[10px] text-[#FF9900]">
                                {item.latest_claim_id}
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="text-slate-500 font-mono">—</span>
                        )}
                      </td>

                      {/* Action */}
                      <td className="py-3.5 px-4 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {item.status === "PENDING" && (
                            <button
                              type="button"
                              onClick={() => handleProcessCharge(item.charge_id)}
                              disabled={processingId === item.charge_id}
                              className="inline-flex items-center gap-1 text-[11px] font-bold px-2.5 py-1 rounded-md bg-[#FF9900] hover:bg-[#E88A00] disabled:opacity-50 text-slate-950 transition-all shadow-xs"
                              title="Run synchronous recovery pipeline"
                            >
                              {processingId === item.charge_id ? (
                                <RefreshCw className="w-3 h-3 animate-spin text-slate-950" />
                              ) : (
                                <Zap className="w-3 h-3 text-slate-950 fill-slate-950" />
                              )}
                              Process
                            </button>
                          )}
                          <Link
                            href={`/charges/${encodeURIComponent(item.charge_id)}`}
                            className="inline-flex items-center gap-1 text-xs text-[#FF9900] hover:text-[#E88A00] font-medium hover:underline"
                          >
                            View <ArrowUpRight className="w-3.5 h-3.5" />
                          </Link>
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
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
      )}
    </div>
  );
}
