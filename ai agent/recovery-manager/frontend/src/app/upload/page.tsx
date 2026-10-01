"use client";

import React, { useState } from "react";
import {
  UploadCloud,
  FileSpreadsheet,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Info,
  Layers,
  ArrowRight,
  Zap,
  Loader2,
  ShieldCheck,
  ShieldAlert,
  Clock,
} from "lucide-react";
import { api } from "@/lib/api";
import type { IngestionResponse, BatchProcessResponse } from "@/types/api";
import { ErrorAlert } from "@/components/common/ErrorAlert";

type IngestionType = "charges" | "reimbursements" | "evidence";
type UploadIngestionResponse = IngestionResponse & {
  total_rows: number;
  accepted: number;
  rejected: number;
  rejected_rows: Array<{ row: number; charge_id?: string | null; reason: string; reason_code: string }>;
};

const OUTCOME_STYLES: Record<string, { icon: React.ReactNode; color: string; bg: string }> = {
  CLAIM_CREATED: {
    icon: <ShieldCheck className="w-3.5 h-3.5" />,
    color: "text-emerald-400",
    bg: "bg-emerald-500/10 border-emerald-500/30",
  },
  NO_CLAIM: {
    icon: <ShieldAlert className="w-3.5 h-3.5" />,
    color: "text-slate-400",
    bg: "bg-slate-500/10 border-slate-500/30",
  },
  ALREADY_PROCESSED: {
    icon: <Clock className="w-3.5 h-3.5" />,
    color: "text-purple-400",
    bg: "bg-purple-500/10 border-purple-500/30",
  },
  HUMAN_REVIEW: {
    icon: <AlertCircle className="w-3.5 h-3.5" />,
    color: "text-amber-400",
    bg: "bg-amber-500/10 border-amber-500/30",
  },
  BLOCKED: {
    icon: <XCircle className="w-3.5 h-3.5" />,
    color: "text-rose-400",
    bg: "bg-rose-500/10 border-rose-500/30",
  },
  ERROR: {
    icon: <XCircle className="w-3.5 h-3.5" />,
    color: "text-rose-400",
    bg: "bg-rose-500/10 border-rose-500/30",
  },
  NOT_FOUND: {
    icon: <XCircle className="w-3.5 h-3.5" />,
    color: "text-rose-400",
    bg: "bg-rose-500/10 border-rose-500/30",
  },
  REJECTED_AT_CLAIM_ENGINE: {
    icon: <XCircle className="w-3.5 h-3.5" />,
    color: "text-orange-400",
    bg: "bg-orange-500/10 border-orange-500/30",
  },
};

function getOutcomeStyle(outcome: string) {
  return OUTCOME_STYLES[outcome] || OUTCOME_STYLES["ERROR"];
}

export default function UploadPage() {
  const [targetType, setTargetType] = useState<IngestionType>("charges");
  const [sourceReport, setSourceReport] = useState("");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);

  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<IngestionResponse | null>(null);

  // Pipeline batch processing state
  const [processing, setProcessing] = useState(false);
  const [batchResult, setBatchResult] = useState<BatchProcessResponse | null>(null);
  const [batchError, setBatchError] = useState<string | null>(null);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      setSelectedFile(e.target.files[0]);
      setError(null);
      setResult(null);
      setBatchResult(null);
      setBatchError(null);
    }
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedFile) {
      setError("Please select a CSV, XLSX, or JSON file to upload.");
      return;
    }

    try {
      setUploading(true);
      setError(null);
      setResult(null);
      setBatchResult(null);
      setBatchError(null);

      const res = await api.uploadFile(targetType, selectedFile, sourceReport.trim() || undefined);
      setResult(res as UploadIngestionResponse);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "File ingestion failed.");
    } finally {
      setUploading(false);
    }
  };

  const handleProcessBatch = async () => {
    if (!result || !result.inserted_ids || result.inserted_ids.length === 0) return;

    try {
      setProcessing(true);
      setBatchError(null);
      setBatchResult(null);

      const res = await api.processBatch(result.inserted_ids);
      setBatchResult(res);
    } catch (err: unknown) {
      setBatchError(err instanceof Error ? err.message : "Batch pipeline processing failed.");
    } finally {
      setProcessing(false);
    }
  };

  const showProcessButton =
    targetType === "charges" &&
    result &&
    result.inserted_ids &&
    result.inserted_ids.length > 0 &&
    !batchResult;

  const rejectedRows = result
    ? ((result as UploadIngestionResponse).rejected_rows || result.errors.map((item) => ({
        row: (item.row_index ?? -1) + 1,
        charge_id: item.charge_id || item.identifier,
        reason: item.reason,
        reason_code: item.reason_code,
      })))
    : [];

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="pb-2 border-b border-[#E5E7EB]">
        <h1 className="text-2xl font-bold text-[#131921] tracking-tight flex items-center gap-2.5">
          <UploadCloud className="w-6 h-6 text-[#FF9900]" />
          Data Ingestion & File Upload
        </h1>
        <p className="text-xs text-slate-500 mt-1">
          Ingest marketplace performance fee reports, carrier reimbursements, and operational evidence
        </p>
      </div>

      {/* Pipeline Scope Notice */}
      <div className="bg-[#F9FAFB] border border-[#E5E7EB] rounded-xl p-4 flex items-start gap-3">
        <Info className="w-5 h-5 text-[#FF9900] shrink-0 mt-0.5" />
        <div className="text-xs space-y-1">
          <div className="font-bold text-[#131921] uppercase tracking-wider">
            Pipeline Scope Notice
          </div>
          <p className="text-slate-600 leading-relaxed">
            Uploading files ingests and validates raw operational data into PostgreSQL.
            For <strong>charges</strong>, after successful ingestion you can immediately trigger
            the full recovery pipeline — evidence retrieval, AI reasoning, rule validation,
            and claim creation — using the <strong>&ldquo;Process Uploaded Charges&rdquo;</strong>{" "}
            button below. This calls <code>POST /pipeline/process-batch</code> with the
            newly inserted charge IDs. Each charge is processed sequentially with error
            isolation; failures on individual charges do not abort the batch.
          </p>
        </div>
      </div>

      {/* Upload Form */}
      <form onSubmit={handleSubmit} className="bg-white border border-[#E5E7EB] rounded-xl p-6 space-y-5 shadow-xs">
        {/* Endpoint Selector Tabs */}
        <div>
          <label className="block text-xs font-semibold text-[#131921] uppercase tracking-wider mb-2">
            Select Ingestion Target Endpoint
          </label>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {[
              { id: "charges", label: "Marketplace Charges", endpoint: "POST /ingestion/charges" },
              { id: "reimbursements", label: "Carrier Reimbursements", endpoint: "POST /ingestion/reimbursements" },
              { id: "evidence", label: "Operational Evidence", endpoint: "POST /ingestion/evidence" },
            ].map((tab) => (
              <button
                key={tab.id}
                type="button"
                onClick={() => {
                  setTargetType(tab.id as IngestionType);
                  setResult(null);
                  setError(null);
                  setBatchResult(null);
                  setBatchError(null);
                }}
                className={`p-3 rounded-lg border text-left transition-all cursor-pointer ${
                  targetType === tab.id
                    ? "bg-[#FF9900]/15 border-[#FF9900]/60 text-[#FF9900] shadow-sm font-semibold"
                    : "bg-[#F9FAFB] border-[#E5E7EB] text-slate-600 hover:border-[#FF9900]/30"
                }`}
              >
                <div className="text-xs font-bold text-[#131921]">{tab.label}</div>
                <div className="text-[10px] font-mono text-slate-500 mt-1">{tab.endpoint}</div>
              </button>
            ))}
          </div>
        </div>

        {/* Source Report Tag */}
        <div>
          <label className="block text-xs font-semibold text-[#131921] uppercase tracking-wider mb-1.5">
            Source Report Identifier (Optional)
          </label>
          <input
            type="text"
            placeholder="e.g. fba_inbound_performance_report_2026_03.csv"
            value={sourceReport}
            onChange={(e) => setSourceReport(e.target.value)}
            className="w-full bg-white border border-[#E5E7EB] rounded-lg px-3.5 py-2 text-xs text-[#131921] placeholder:text-slate-400 focus:outline-none focus:border-[#FF9900] font-mono"
          />
        </div>

        {/* File Dropzone */}
        <div>
          <label className="block text-xs font-semibold text-[#131921] uppercase tracking-wider mb-1.5">
            Report File (CSV, XLSX, or JSON)
          </label>
          <div className="border-2 border-dashed border-[#E5E7EB] hover:border-[#FF9900]/60 rounded-xl p-6 text-center bg-[#F9FAFB] transition-colors">
            <input
              type="file"
              id="file-upload"
              accept=".csv,.xlsx,.xls,.json"
              onChange={handleFileChange}
              className="hidden"
            />
            <label htmlFor="file-upload" className="cursor-pointer flex flex-col items-center">
              <FileSpreadsheet className="w-10 h-10 text-slate-400 mb-2" />
              {selectedFile ? (
                <div className="space-y-1">
                  <div className="text-sm font-bold text-[#131921] font-mono">{selectedFile.name}</div>
                  <div className="text-xs text-slate-500">
                    {(selectedFile.size / 1024).toFixed(1)} KB — Click to change file
                  </div>
                </div>
              ) : (
                <div className="space-y-1">
                  <div className="text-xs font-semibold text-[#FF9900]">Click to select file</div>
                  <div className="text-[11px] text-slate-500">Supports standard CSV, XLSX, and JSON arrays</div>
                </div>
              )}
            </label>
          </div>
        </div>

        {/* Submit Button */}
        <div className="flex items-center justify-end gap-3 pt-2">
          {selectedFile && (
            <button
              type="button"
              onClick={() => {
                setSelectedFile(null);
                setResult(null);
                setBatchResult(null);
                setBatchError(null);
              }}
              className="px-3 py-1.5 text-xs text-slate-500 hover:text-[#131921]"
            >
              Clear
            </button>
          )}

          <button
            type="submit"
            disabled={uploading || !selectedFile}
            className="px-5 py-2.5 rounded-lg text-xs font-bold bg-[#FF9900] hover:bg-[#E88A00] disabled:opacity-40 disabled:pointer-events-none text-slate-950 transition-all shadow-sm cursor-pointer"
          >
            {uploading ? "Ingesting Records..." : `Upload & Ingest to ${targetType}`}
          </button>
        </div>
      </form>

      {error && <ErrorAlert message={error} />}

      {/* Ingestion Results Display */}
      {result && (
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-6 space-y-4 shadow-xs">
          <div className="flex items-center justify-between pb-3 border-b border-[#E5E7EB]">
            <div className="flex items-center gap-2">
              {(result as UploadIngestionResponse).rejected === 0 || result.failed_count === 0 ? (
                <CheckCircle2 className="w-5 h-5 text-emerald-600" />
              ) : (
                <AlertCircle className="w-5 h-5 text-amber-600" />
              )}
              <h2 className="text-sm font-bold text-[#131921] uppercase tracking-wider">
                Ingestion Summary: {result.record_type}
              </h2>
            </div>
            <span className="text-xs font-mono text-slate-500">
              {(result as UploadIngestionResponse).accepted ?? result.inserted_count} of {(result as UploadIngestionResponse).total_rows ?? result.total_records} accepted
            </span>
          </div>

          {/* Counts Grid */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB] text-center">
              <span className="text-slate-500 block mb-1 text-[11px]">Total Records</span>
              <span className="text-lg font-bold text-[#131921] font-mono">{(result as UploadIngestionResponse).total_rows ?? result.total_records}</span>
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB] text-center">
              <span className="text-slate-500 block mb-1 text-[11px]">Accepted</span>
              <span className="text-lg font-bold text-emerald-700 font-mono">{(result as UploadIngestionResponse).accepted ?? result.accepted_count ?? result.inserted_count}</span>
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB] text-center">
              <span className="text-slate-500 block mb-1 text-[11px]">Duplicates</span>
              <span className="text-lg font-bold text-purple-700 font-mono">{result.duplicate_count}</span>
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB] text-center">
              <span className="text-slate-500 block mb-1 text-[11px]">Rejected</span>
              <span className="text-lg font-bold text-rose-600 font-mono">{(result as UploadIngestionResponse).rejected ?? result.rejected_count ?? result.failed_count}</span>
            </div>
          </div>

          {/* Inserted IDs list if any */}
          {result.inserted_ids && result.inserted_ids.length > 0 && (
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB] text-xs">
              <span className="font-semibold text-[#131921] block mb-1.5">
                Successfully Accepted Identifiers ({result.inserted_ids.length}):
              </span>
              <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
                {result.inserted_ids.map((id) => (
                  <span
                    key={id}
                    className="font-mono text-[11px] bg-white px-2 py-0.5 rounded border border-[#E5E7EB] text-[#131921]"
                  >
                    {id}
                  </span>
                ))}
              </div>
            </div>
          )}

          {/* Rejected Errors List if any */}
          {rejectedRows.length > 0 && (
            <div className="p-4 bg-rose-50 border border-rose-300 rounded-lg text-xs space-y-2">
              <div className="font-bold text-rose-700 flex items-center gap-1.5">
                <XCircle className="w-4 h-4 text-rose-500" />
                Rejected Rows & Reasons ({rejectedRows.length}):
              </div>
              <div className="space-y-1.5 max-h-48 overflow-y-auto">
                {rejectedRows.map((err, idx) => (
                  <div
                    key={idx}
                    className="p-2 bg-white rounded border border-rose-200 flex flex-col sm:flex-row sm:items-center justify-between gap-1 text-[11px]"
                  >
                    <div className="font-mono text-slate-700">
                      {err.row !== undefined && (
                        <span className="text-slate-500 mr-2">Row #{err.row}</span>
                      )}
                      {err.charge_id && (
                        <strong className="text-rose-600 mr-2">{err.charge_id}</strong>
                      )}
                    </div>
                    <div className="text-rose-600 font-medium text-right">
                      <span className="block font-mono text-[10px] uppercase tracking-wide">{err.reason_code}</span>
                      <span>{err.reason}</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* === PROCESS UPLOADED CHARGES BUTTON === */}
          {showProcessButton && (
            <div className="pt-2 border-t border-[#E5E7EB]">
              <div className="flex items-center justify-between">
                <div className="text-xs text-slate-500">
                  <Zap className="w-3.5 h-3.5 inline mr-1 text-[#FF9900]" />
                  {result.inserted_ids.length} charge{result.inserted_ids.length !== 1 ? "s" : ""} ready
                  for pipeline processing
                </div>
                <button
                  type="button"
                  onClick={handleProcessBatch}
                  disabled={processing}
                  className="px-5 py-2.5 rounded-lg text-xs font-bold bg-[#FF9900] hover:bg-[#E88A00] disabled:opacity-50 disabled:pointer-events-none text-slate-950 transition-all shadow-sm flex items-center gap-2 cursor-pointer"
                >
                  {processing ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin text-slate-950" />
                      Processing Pipeline...
                    </>
                  ) : (
                    <>
                      <Zap className="w-4 h-4 text-slate-950 fill-slate-950" />
                      Process Uploaded Charges
                      <ArrowRight className="w-3.5 h-3.5" />
                    </>
                  )}
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {batchError && <ErrorAlert message={batchError} />}

      {/* === BATCH PIPELINE RESULTS === */}
      {batchResult && (
        <div className="bg-white border border-[#E5E7EB] rounded-xl p-6 space-y-4 shadow-xs">
          <div className="flex items-center justify-between pb-3 border-b border-[#E5E7EB]">
            <div className="flex items-center gap-2">
              <Layers className="w-5 h-5 text-[#FF9900]" />
              <h2 className="text-sm font-bold text-[#131921] uppercase tracking-wider">
                Pipeline Batch Results
              </h2>
            </div>
            <span className="text-xs font-mono text-slate-500">
              {batchResult.total} charge{batchResult.total !== 1 ? "s" : ""} processed
            </span>
          </div>

          {/* Summary Counts */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs">
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-[#E5E7EB] text-center">
              <span className="text-slate-500 block mb-1 text-[11px]">Total</span>
              <span className="text-lg font-bold text-[#131921] font-mono">{batchResult.total}</span>
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-emerald-300 text-center">
              <span className="text-emerald-700 block mb-1 text-[11px]">Succeeded</span>
              <span className="text-lg font-bold text-emerald-700 font-mono">{batchResult.succeeded}</span>
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-rose-300 text-center">
              <span className="text-rose-600 block mb-1 text-[11px]">Failed</span>
              <span className="text-lg font-bold text-rose-600 font-mono">{batchResult.failed}</span>
            </div>
            <div className="p-3 bg-[#F9FAFB] rounded-lg border border-purple-300 text-center">
              <span className="text-purple-700 block mb-1 text-[11px]">Already Processed</span>
              <span className="text-lg font-bold text-purple-700 font-mono">{batchResult.already_processed}</span>
            </div>
          </div>

          {/* Per-Charge Results */}
          {batchResult.results && batchResult.results.length > 0 && (
            <div className="space-y-2">
              <div className="text-xs font-semibold text-[#131921] uppercase tracking-wider">
                Per-Charge Results
              </div>
              <div className="space-y-1.5 max-h-80 overflow-y-auto">
                {batchResult.results.map((r, idx) => {
                  const style = getOutcomeStyle(r.outcome);
                  return (
                    <div
                      key={idx}
                      className={`p-3 rounded-lg border ${style.bg} flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs`}
                    >
                      <div className="flex items-center gap-2">
                        <span className={style.color}>{style.icon}</span>
                        <span className="font-mono font-bold text-[#131921]">{r.charge_id}</span>
                        <span className={`font-bold uppercase text-[10px] ${style.color}`}>
                          {r.outcome}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 text-[11px] text-slate-500">
                        {r.claim_id && (
                          <span className="font-mono text-emerald-700">{r.claim_id}</span>
                        )}
                        {r.assessment && (
                          <span className="text-slate-500">{r.assessment}</span>
                        )}
                        {r.claim_amount && (
                          <span className="font-mono text-[#131921]">${Number(r.claim_amount).toFixed(2)}</span>
                        )}
                        {r.evidence_count > 0 && (
                          <span className="text-slate-500">{r.evidence_count} evidence</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
