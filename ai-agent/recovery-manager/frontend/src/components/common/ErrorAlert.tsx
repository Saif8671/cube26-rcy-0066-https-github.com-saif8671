import React from "react";
import { AlertCircle, RefreshCw } from "lucide-react";

export function ErrorAlert({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="bg-rose-500/10 border border-rose-500/30 rounded-xl p-5 my-4">
      <div className="flex items-start gap-3">
        <AlertCircle className="w-5 h-5 text-rose-400 shrink-0 mt-0.5" />
        <div className="flex-1">
          <h4 className="text-sm font-semibold text-rose-300">Error Loading Data</h4>
          <p className="text-sm text-rose-400/90 mt-1 break-words">{message}</p>
          {onRetry && (
            <button
              onClick={onRetry}
              className="mt-3 inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-rose-500/20 hover:bg-rose-500/30 text-rose-200 border border-rose-500/30 transition-colors"
            >
              <RefreshCw className="w-3.5 h-3.5" />
              Retry Request
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
