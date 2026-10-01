"use client";

import React, { useEffect, useState, useTransition } from "react";
import {
  DollarSign,
  Receipt,
  FileCheck2,
  AlertCircle,
  HelpCircle,
  RefreshCw,
  TrendingUp,
  PieChart as PieIcon,
  BarChart3,
} from "lucide-react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Cell,
  PieChart,
  Pie,
  Legend,
} from "recharts";
import { api } from "@/lib/api";
import type { DashboardMetricsResponse } from "@/types/api";
import { formatCurrency } from "@/lib/utils";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { ErrorAlert } from "@/components/common/ErrorAlert";

const ASSESSMENT_COLORS: Record<string, string> = {
  CONTRADICTED: "#10b981", // Emerald
  SUPPORTED: "#3b82f6",    // Blue
  SILENT: "#64748b",       // Slate
  UNCERTAIN: "#f59e0b",    // Amber
};

const STATUS_COLORS: Record<string, string> = {
  READY_FOR_REVIEW: "#10b981",
  DUPLICATE: "#a855f7",
  ALREADY_REIMBURSED: "#6366f1",
  REJECTED: "#f43f5e",
  APPROVED: "#06b6d4",
};

export default function DashboardPage() {
  const [metrics, setMetrics] = useState<DashboardMetricsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const fetchMetrics = async () => {
    try {
      setLoading(true);
      setError(null);
      const data = await api.getDashboardMetrics();
      setMetrics(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load dashboard metrics from backend.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchMetrics();
  }, []);

  if (loading) {
    return <LoadingSpinner message="Querying live operational metrics from backend..." />;
  }

  if (error || !metrics) {
    return (
      <div>
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold text-[#131921] tracking-tight">Recovery Dashboard</h1>
            <p className="text-xs text-slate-500 mt-1">Real-time dispute pipeline aggregations</p>
          </div>
        </div>
        <ErrorAlert message={error || "Unknown metrics error"} onRetry={fetchMetrics} />
      </div>
    );
  }

  // Prepare chart data
  const assessmentData = Object.entries(metrics.claims_by_assessment).map(([key, value]) => ({
    name: key,
    count: value,
    color: ASSESSMENT_COLORS[key] || "#94a3b8",
  }));

  const statusData = Object.entries(metrics.claims_by_status).map(([key, value]) => ({
    name: key.replace(/_/g, " "),
    rawKey: key,
    count: value,
    color: STATUS_COLORS[key] || "#94a3b8",
  }));

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-[#E5E7EB]">
        <div>
          <h1 className="text-2xl font-bold text-[#131921] tracking-tight">Recovery Operations Dashboard</h1>
          <p className="text-xs text-slate-500 mt-1">
            Real-time financial metrics computed dynamically via database aggregation
          </p>
        </div>
        <button
          type="button"
          onClick={() => startTransition(fetchMetrics)}
          disabled={isPending}
          className="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-lg text-xs font-medium bg-white hover:bg-slate-50 text-slate-700 border border-[#E5E7EB] hover:border-[#FF9900]/60 shadow-xs transition-all self-start sm:self-auto"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isPending ? "animate-spin" : ""}`} />
          Refresh Metrics
        </button>
      </div>

      {/* Primary KPI Metrics */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* Total Charges */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-5 relative overflow-hidden shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Total Ingested Charges
            </span>
            <div className="w-8 h-8 rounded-lg bg-[#FF9900]/10 text-[#D97706] flex items-center justify-center border border-[#FF9900]/30">
              <Receipt className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-3xl font-extrabold text-[#131921] tracking-tight">
              {metrics.total_charges.toLocaleString()}
            </div>
            <p className="text-[11px] text-slate-500 mt-1">
              Marketplace fee transactions recorded
            </p>
          </div>
        </div>

        {/* Potential Recovery */}
        <div className="bg-white border border-emerald-200 rounded-xl p-5 relative overflow-hidden bg-gradient-to-br from-white via-white to-emerald-50/50 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-emerald-700 uppercase tracking-wider">
              Potential Recovery
            </span>
            <div className="w-8 h-8 rounded-lg bg-emerald-500/10 text-emerald-600 flex items-center justify-center border border-emerald-500/30">
              <DollarSign className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-3xl font-extrabold text-emerald-600 tracking-tight">
              {formatCurrency(metrics.total_potential_recovery)}
            </div>
            <p className="text-[11px] text-emerald-700/80 mt-1">
              CONTRADICTED claims in READY_FOR_REVIEW
            </p>
          </div>
        </div>

        {/* Total Claims */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-5 relative overflow-hidden shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-500 uppercase tracking-wider">
              Total Recovery Claims
            </span>
            <div className="w-8 h-8 rounded-lg bg-[#FF9900]/10 text-[#D97706] flex items-center justify-center border border-[#FF9900]/30">
              <FileCheck2 className="w-4 h-4" />
            </div>
          </div>
          <div className="mt-4">
            <div className="text-3xl font-extrabold text-[#131921] tracking-tight">
              {metrics.total_claims.toLocaleString()}
            </div>
            <p className="text-[11px] text-slate-500 mt-1">
              Persisted claim dispute records
            </p>
          </div>
        </div>
      </div>

      {/* Supporting Diagnostics Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Unprocessed charges */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-4 flex items-start gap-3 shadow-xs">
          <div className="w-8 h-8 rounded-lg bg-amber-50 text-[#D97706] flex items-center justify-center shrink-0 mt-0.5 border border-amber-200">
            <HelpCircle className="w-4 h-4" />
          </div>
          <div className="flex-1">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-[#131921]">
                Unprocessed Charges
              </span>
              <span className="text-base font-bold text-[#131921]">
                {metrics.unprocessed_charges_count}
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-1">
              Charges with no evaluation recorded in assessment log (never evaluated by the pipeline).
            </p>
          </div>
        </div>

        {/* Processed No-Claim */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-4 flex items-start gap-3 shadow-xs">
          <div className="w-8 h-8 rounded-lg bg-slate-100 text-slate-700 flex items-center justify-center shrink-0 mt-0.5 border border-[#E5E7EB]">
            <TrendingUp className="w-4 h-4" />
          </div>
          <div className="flex-1">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-[#131921]">
                Evaluated, No Claim Generated
              </span>
              <span className="text-base font-bold text-[#131921]">
                {metrics.processed_no_claim_charges_count}
              </span>
            </div>
            <p className="text-xs text-slate-500 mt-1">
              Charges evaluated through the pipeline resulting in SUPPORTED, SILENT, or UNCERTAIN outcomes without a claims row.
            </p>
          </div>
        </div>
      </div>

      {/* Persistence gap notice if any */}
      {metrics.persistence_gap_notice && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 flex items-center gap-3">
          <AlertCircle className="w-5 h-5 text-amber-600 shrink-0" />
          <p className="text-xs text-amber-800">{metrics.persistence_gap_notice}</p>
        </div>
      )}

      {/* Visual Charts Grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Assessment Breakdown Chart */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-5 shadow-xs">
          <div className="flex items-center justify-between mb-4 pb-2 border-b border-[#E5E7EB]">
            <div className="flex items-center gap-2">
              <PieIcon className="w-4 h-4 text-[#D97706]" />
              <h2 className="text-sm font-bold text-[#131921]">Assessment Breakdown</h2>
            </div>
            <span className="text-[11px] text-slate-500">assessment_log counts</span>
          </div>

          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={assessmentData} margin={{ top: 10, right: 10, left: -20, bottom: 20 }}>
                <XAxis
                  dataKey="name"
                  stroke="#64748b"
                  fontSize={11}
                  tickLine={false}
                  axisLine={{ stroke: "#E5E7EB" }}
                />
                <YAxis
                  stroke="#64748b"
                  fontSize={11}
                  allowDecimals={false}
                  tickLine={false}
                  axisLine={{ stroke: "#E5E7EB" }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#FFFFFF",
                    borderColor: "#E5E7EB",
                    borderRadius: "8px",
                    color: "#131921",
                    fontSize: "12px",
                    boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1)",
                  }}
                  cursor={{ fill: "rgba(229, 231, 235, 0.4)" }}
                />
                <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                  {assessmentData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Legend / Breakdown Details */}
          <div className="grid grid-cols-2 gap-2 mt-4 pt-4 border-t border-[#E5E7EB] text-xs">
            {assessmentData.map((item) => (
              <div key={item.name} className="flex items-center justify-between p-2 rounded bg-slate-50 border border-[#E5E7EB]">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                  <span className="text-slate-700 font-medium">{item.name}</span>
                </div>
                <span className="font-bold text-[#131921] font-mono">{item.count}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Claim Status Breakdown Chart */}
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-5 shadow-xs">
          <div className="flex items-center justify-between mb-4 pb-2 border-b border-[#E5E7EB]">
            <div className="flex items-center gap-2">
              <BarChart3 className="w-4 h-4 text-[#D97706]" />
              <h2 className="text-sm font-bold text-[#131921]">Claims by Lifecycle Status</h2>
            </div>
            <span className="text-[11px] text-slate-500">claims table counts</span>
          </div>

          <div className="h-64 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={statusData} layout="vertical" margin={{ top: 10, right: 20, left: 40, bottom: 10 }}>
                <XAxis
                  type="number"
                  stroke="#64748b"
                  fontSize={11}
                  allowDecimals={false}
                  tickLine={false}
                  axisLine={{ stroke: "#E5E7EB" }}
                />
                <YAxis
                  type="category"
                  dataKey="name"
                  stroke="#64748b"
                  fontSize={10}
                  tickLine={false}
                  axisLine={{ stroke: "#E5E7EB" }}
                  width={90}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "#FFFFFF",
                    borderColor: "#E5E7EB",
                    borderRadius: "8px",
                    color: "#131921",
                    fontSize: "12px",
                    boxShadow: "0 4px 6px -1px rgba(0, 0, 0, 0.1)",
                  }}
                  cursor={{ fill: "rgba(229, 231, 235, 0.4)" }}
                />
                <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                  {statusData.map((entry, index) => (
                    <Cell key={`status-cell-${index}`} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>

          {/* Status Breakdown Details */}
          <div className="grid grid-cols-2 gap-2 mt-4 pt-4 border-t border-[#E5E7EB] text-xs">
            {statusData.map((item) => (
              <div key={item.rawKey} className="flex items-center justify-between p-2 rounded bg-slate-50 border border-[#E5E7EB]">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: item.color }} />
                  <span className="text-slate-700 font-medium truncate max-w-[120px]">{item.name}</span>
                </div>
                <span className="font-bold text-[#131921] font-mono">{item.count}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
