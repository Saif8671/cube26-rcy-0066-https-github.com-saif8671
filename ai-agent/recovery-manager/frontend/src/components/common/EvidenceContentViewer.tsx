"use client";

import React, { useState } from "react";
import { Code, CheckCircle2, XCircle, ChevronDown, ChevronRight } from "lucide-react";

interface EvidenceContentViewerProps {
  content: Record<string, any>;
  title?: string;
}

function formatKey(key: string): string {
  return key
    .replace(/_lb$/, " (lb)")
    .replace(/_url$/, " URL")
    .replace(/_id$/, " ID")
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function EvidenceContentViewer({
  content,
  title = "Evidence Findings",
}: EvidenceContentViewerProps) {
  const [showRawJson, setShowRawJson] = useState(false);

  if (!content || typeof content !== "object" || Object.keys(content).length === 0) {
    return <span className="text-xs text-slate-500 italic">No structured evidence payload</span>;
  }

  const entries = Object.entries(content);

  return (
    <div className="bg-slate-50/70 border border-[#E5E7EB] rounded-lg p-3 text-xs">
      <div className="flex items-center justify-between pb-2 mb-2 border-b border-[#E5E7EB]">
        <span className="font-semibold text-slate-700 uppercase tracking-wider text-[11px]">
          {title} ({entries.length} fields)
        </span>
        <button
          type="button"
          onClick={() => setShowRawJson(!showRawJson)}
          className="inline-flex items-center gap-1 text-[11px] text-slate-500 hover:text-[#131921] transition-colors"
        >
          <Code className="w-3 h-3" />
          {showRawJson ? "Formatted View" : "Raw JSON"}
        </button>
      </div>

      {showRawJson ? (
        <pre className="p-2.5 bg-slate-50 rounded font-mono text-[11px] text-[#131921] overflow-x-auto border border-[#E5E7EB] max-h-56">
          {JSON.stringify(content, null, 2)}
        </pre>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
          {entries.map(([key, value]) => {
            let renderedValue: React.ReactNode;

            if (typeof value === "boolean") {
              renderedValue = value ? (
                <span className="inline-flex items-center gap-1 text-emerald-600 font-medium">
                  <CheckCircle2 className="w-3.5 h-3.5" /> Yes / Passed
                </span>
              ) : (
                <span className="inline-flex items-center gap-1 text-rose-600 font-medium">
                  <XCircle className="w-3.5 h-3.5" /> No / Failed
                </span>
              );
            } else if (value === null || value === undefined) {
              renderedValue = <span className="text-slate-400 italic">null</span>;
            } else if (typeof value === "object") {
              renderedValue = (
                <span className="font-mono text-slate-700">{JSON.stringify(value)}</span>
              );
            } else if (typeof value === "string" && (value.startsWith("http") || value.startsWith("s3://"))) {
              renderedValue = (
                <span className="font-mono text-blue-600 truncate max-w-[200px]" title={value}>
                  {value}
                </span>
              );
            } else {
              renderedValue = (
                <span className="font-medium text-[#131921]">
                  {typeof value === "number" ? value.toLocaleString() : String(value)}
                </span>
              );
            }

            return (
              <div
                key={key}
                className="flex items-start justify-between gap-2 p-2 rounded bg-white border border-[#E5E7EB]"
              >
                <span className="text-slate-500 font-medium">{formatKey(key)}:</span>
                <span className="text-right">{renderedValue}</span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
