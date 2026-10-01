"use client";

import React, { useEffect, useState, useTransition } from "react";
import Link from "next/link";
import { FileCheck2, Filter, ArrowUpRight, RefreshCw } from "lucide-react";
import { api } from "@/lib/api";
import type { ClaimListResponse } from "@/types/api";
import { formatCurrency, formatDate } from "@/lib/utils";
import { StatusBadge } from "@/components/common/StatusBadge";
import { AssessmentBadge } from "@/components/common/AssessmentBadge";
import { Pagination } from "@/components/common/Pagination";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { ErrorAlert } from "@/components/common/ErrorAlert";

export default function ClaimsPage() {
  const [data, setData] = useState<ClaimListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [limit, setLimit] = useState(10);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState<string>("");
  const [isPending, startTransition] = useTransition();

  const fetchClaims = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.getClaims({
        limit,
        offset,
        status: statusFilter || undefined,
      });
      setData(res);
    } catch (err: any) {
      setError(err?.message || "Failed to load recovery claims.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchClaims();
  }, [limit, offset, statusFilter]);

  const handleFilterChange = (newStatus: string) => {
    setStatusFilter(newStatus);
    setOffset(0);
  };

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-[#E5E7EB]">
        <div>
          <h1 className="text-2xl font-bold text-[#131921] tracking-tight flex items-center gap-2.5">
            <FileCheck2 className="w-6 h-6 text-[#FF9900]" />
            Recovery Claims
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Persisted recovery dispute claims, AI assessment outcomes, and human review readiness
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
              <option value="" className="bg-white text-slate-800">All Statuses</option>
              <option value="READY_FOR_REVIEW" className="bg-white text-slate-800">READY_FOR_REVIEW</option>
              <option value="DUPLICATE" className="bg-white text-slate-800">DUPLICATE</option>
              <option value="ALREADY_REIMBURSED" className="bg-white text-slate-800">ALREADY_REIMBURSED</option>
              <option value="REJECTED" className="bg-white text-slate-800">REJECTED</option>
              <option value="APPROVED" className="bg-white text-slate-800">APPROVED</option>
            </select>
          </div>

          <button
            type="button"
            onClick={() => startTransition(fetchClaims)}
            disabled={isPending}
            className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-white hover:bg-slate-50 text-slate-700 border border-[#E5E7EB] hover:border-[#FF9900]/40 transition-all shadow-xs"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isPending ? "animate-spin" : ""}`} />
            Refresh
          </button>
        </div>
      </div>

      {loading && !data && <LoadingSpinner message="Fetching recovery claims from database..." />}

      {error && <ErrorAlert message={error} onRetry={fetchClaims} />}

      {data && (
        <div className="bg-white border border-[#E5E7EB] rounded-xl overflow-hidden shadow-xs">
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-[#F9FAFB] border-b border-[#E5E7EB] text-slate-500 font-semibold uppercase tracking-wider text-[11px]">
                <tr>
                  <th className="py-3 px-4">Claim ID</th>
                  <th className="py-3 px-4">Underlying Charge</th>
                  <th className="py-3 px-4">Assessment</th>
                  <th className="py-3 px-4 text-right">Claim Amount</th>
                  <th className="py-3 px-4 text-center">Status</th>
                  <th className="py-3 px-4 text-center">Confidence</th>
                  <th className="py-3 px-4">Source Manager</th>
                  <th className="py-3 px-4">Created Date</th>
                  <th className="py-3 px-4 text-right">Traceability</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#E5E7EB] text-slate-700">
                {data.items.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-12 text-center text-slate-500">
                      No claims found matching the current filters.
                    </td>
                  </tr>
                ) : (
                  data.items.map((item) => (
                    <tr
                      key={item.claim_id}
                      className="hover:bg-slate-50/80 transition-colors group"
                    >
                      {/* Claim ID */}
                      <td className="py-3.5 px-4 font-mono font-bold text-[#131921]">
                        <Link
                          href={`/claims/${encodeURIComponent(item.claim_id)}`}
                          className="hover:text-[#FF9900] hover:underline inline-flex items-center gap-1 text-[#131921]"
                        >
                          {item.claim_id}
                        </Link>
                      </td>

                      {/* Charge ID */}
                      <td className="py-3.5 px-4 font-mono">
                        <Link
                          href={`/charges/${encodeURIComponent(item.charge_id)}`}
                          className="hover:text-[#E88A00] hover:underline text-[#FF9900]"
                        >
                          {item.charge_id}
                        </Link>
                      </td>

                      {/* Assessment */}
                      <td className="py-3.5 px-4">
                        <AssessmentBadge assessment={item.assessment} />
                      </td>

                      {/* Claim Amount */}
                      <td className="py-3.5 px-4 text-right font-mono font-bold text-emerald-700">
                        {formatCurrency(item.claim_amount)}
                      </td>

                      {/* Status */}
                      <td className="py-3.5 px-4 text-center whitespace-nowrap">
                        <StatusBadge status={item.status} />
                      </td>

                      {/* Confidence */}
                      <td className="py-3.5 px-4 text-center font-mono">
                        {item.confidence ? (
                          <span className="text-[#131921] font-semibold">
                            {(Number(item.confidence) * 100).toFixed(0)}%
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>

                      {/* Source Manager */}
                      <td className="py-3.5 px-4 text-slate-700">
                        {item.source_manager || "—"}
                      </td>

                      {/* Created At */}
                      <td className="py-3.5 px-4 text-slate-500 whitespace-nowrap">
                        {formatDate(item.created_at)}
                      </td>

                      {/* Action */}
                      <td className="py-3.5 px-4 text-right">
                        <Link
                          href={`/claims/${encodeURIComponent(item.claim_id)}`}
                          className="inline-flex items-center gap-1 text-xs text-[#FF9900] hover:text-[#E88A00] font-medium hover:underline"
                        >
                          Trace <ArrowUpRight className="w-3.5 h-3.5" />
                        </Link>
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
