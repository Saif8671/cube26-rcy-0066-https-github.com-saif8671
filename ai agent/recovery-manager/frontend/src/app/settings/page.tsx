"use client";

import React, { useEffect, useState } from "react";
import { Settings, Server, Database, ShieldCheck, RefreshCw, CheckCircle2, AlertCircle } from "lucide-react";
import { api } from "@/lib/api";
import type { HealthResponse } from "@/types/api";
import { LoadingSpinner } from "@/components/common/LoadingSpinner";
import { ErrorAlert } from "@/components/common/ErrorAlert";

export default function SettingsPage() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchHealth = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await api.getHealth();
      setHealth(res);
    } catch (err: any) {
      setError(err?.message || "Failed to reach backend health endpoint.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchHealth();
  }, []);

  const backendUrl = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between pb-2 border-b border-[#E5E7EB]">
        <div>
          <h1 className="text-2xl font-bold text-[#131921] tracking-tight flex items-center gap-2.5">
            <Settings className="w-6 h-6 text-[#FF9900]" />
            System & Environment Settings
          </h1>
          <p className="text-xs text-slate-500 mt-1">
            Read-only configuration parameters and live backend service status
          </p>
        </div>

        <button
          type="button"
          onClick={fetchHealth}
          className="inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-white hover:bg-slate-50 text-slate-700 border border-[#E5E7EB] hover:border-[#FF9900]/40 transition-all cursor-pointer shadow-xs"
        >
          <RefreshCw className="w-3.5 h-3.5" />
          Test Connectivity
        </button>
      </div>

      {loading && !health && <LoadingSpinner message="Checking backend system health..." />}

      {error && <ErrorAlert message={error} onRetry={fetchHealth} />}

      {/* Backend Service Status Card */}
      <div className="bg-white border border-[#E5E7EB] rounded-xl p-5 space-y-4 shadow-xs">
        <div className="flex items-center justify-between pb-3 border-b border-[#E5E7EB]">
          <div className="flex items-center gap-2">
            <Server className="w-4 h-4 text-[#FF9900]" />
            <h2 className="text-sm font-bold text-[#131921] uppercase tracking-wider">
              Backend Service Health
            </h2>
          </div>
          {health && (
            <span
              className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${
                health.status === "ok"
                  ? "bg-emerald-500/10 text-emerald-700 border-emerald-500/30"
                  : "bg-rose-500/10 text-rose-600 border-rose-500/30"
              }`}
            >
              {health.status === "ok" ? (
                <>
                  <CheckCircle2 className="w-3 h-3" /> Service Healthy
                </>
              ) : (
                <>
                  <AlertCircle className="w-3 h-3" /> Degraded
                </>
              )}
            </span>
          )}
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-4 gap-3 text-xs">
          <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
            <span className="text-slate-500 block mb-1 text-[11px]">System Status:</span>
            <span className="font-mono font-bold text-[#131921] text-sm uppercase">
              {health?.status || "Unknown"}
            </span>
          </div>
          <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
            <span className="text-slate-500 block mb-1 text-[11px]">Database Connection:</span>
            <span
              className={`font-mono font-bold text-sm capitalize ${
                health?.database === "connected" ? "text-emerald-700" : "text-rose-600"
              }`}
            >
              {health?.database || "Unknown"}
            </span>
          </div>
          <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
            <span className="text-slate-500 block mb-1 text-[11px]">Backend Version:</span>
            <span className="font-mono font-bold text-[#131921] text-sm">
              v{health?.version || "—"}
            </span>
          </div>
          <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB]">
            <span className="text-slate-500 block mb-1 text-[11px]">Environment:</span>
            <span className="font-mono font-bold text-[#FF9900] text-sm capitalize">
              {health?.environment || "—"}
            </span>
          </div>
        </div>
      </div>

      {/* Network & API Configuration */}
      <div className="bg-white border border-[#E5E7EB] rounded-xl p-5 space-y-4 shadow-xs">
        <div className="flex items-center gap-2 pb-3 border-b border-[#E5E7EB]">
          <Database className="w-4 h-4 text-[#FF9900]" />
          <h2 className="text-sm font-bold text-[#131921] uppercase tracking-wider">
            Network & Base URL Configuration
          </h2>
        </div>

        <div className="space-y-3 text-xs">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB] font-mono">
            <span className="text-slate-500 font-sans">Target Backend Base URL:</span>
            <span className="text-[#FF9900] font-bold">{backendUrl}</span>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB] font-mono">
            <span className="text-slate-500 font-sans">Client-Side Proxy Rewrite:</span>
            <span className="text-[#131921]">/api/backend/* &rarr; {backendUrl}/*</span>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB] font-mono">
            <span className="text-slate-500 font-sans">Environment Variable Source:</span>
            <span className="text-[#131921]">NEXT_PUBLIC_API_URL in .env.local</span>
          </div>
        </div>
      </div>

      {/* Architecture Traceability Notice */}
      <div className="bg-[#F9FAFB] border border-[#E5E7EB] rounded-xl p-5 flex items-start gap-3">
        <ShieldCheck className="w-5 h-5 text-emerald-600 shrink-0 mt-0.5" />
        <div className="text-xs space-y-1">
          <div className="font-bold text-[#131921] uppercase tracking-wider">
            Phase 8b Architectural Scope
          </div>
          <p className="text-slate-600 leading-relaxed">
            The frontend UI strictly operates in read-only mode against Phase 8a Read API endpoints
            (and multipart ingestion in Phase 3). Zero mock data or simulated pipeline mutations are permitted.
          </p>
        </div>
      </div>
    </div>
  );
}
