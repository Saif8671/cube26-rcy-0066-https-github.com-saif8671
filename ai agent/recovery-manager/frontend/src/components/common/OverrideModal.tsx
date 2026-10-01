"use client";

import React, { useState } from "react";
import { AlertTriangle, CheckCircle2, ShieldCheck, X } from "lucide-react";
import { api } from "@/lib/api";

interface OverrideModalProps {
  isOpen: boolean;
  onClose: () => void;
  chargeId: string;
  claimId?: string | null;
  currentAssessment?: string | null;
  onSuccess: () => void;
}

export function OverrideModal({
  isOpen,
  onClose,
  chargeId,
  claimId,
  currentAssessment,
  onSuccess,
}: OverrideModalProps) {
  const [verdict, setVerdict] = useState<string>("APPROVED");
  const [reason, setReason] = useState<string>("");
  const [reviewerId, setReviewerId] = useState<string>("operator_supervisor");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [successMsg, setSuccessMsg] = useState<string | null>(null);

  if (!isOpen) return null;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!reason.trim()) {
      setError("Please provide a non-empty operational reason for this override.");
      return;
    }

    try {
      setIsSubmitting(true);
      setError(null);
      setSuccessMsg(null);

      const res = await api.overrideCharge(chargeId, {
        new_verdict: verdict,
        reason: reason.trim(),
        reviewer_id: reviewerId.trim() || "operator",
      });

      setSuccessMsg(res.action_taken || "Override successfully captured and applied.");
      setTimeout(() => {
        onSuccess();
        onClose();
      }, 1200);
    } catch (err: any) {
      setError(err?.message || "Failed to submit operator override.");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="relative w-full max-w-lg bg-white border border-[#E5E7EB] rounded-xl shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#E5E7EB] bg-[#F9FAFB]">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-[#FF9900]/10 text-[#FF9900] flex items-center justify-center border border-[#FF9900]/30">
              <ShieldCheck className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-base font-bold text-[#131921] tracking-tight">
                Operator Verdict Override
              </h3>
              <p className="text-xs text-slate-500">
                Honesty Rule: captured as immutable audit record
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg text-slate-400 hover:text-[#131921] hover:bg-slate-100 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Content */}
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div className="bg-[#F9FAFB] rounded-lg p-3 border border-[#E5E7EB] text-xs space-y-1">
            <div className="flex justify-between">
              <span className="text-slate-500">Charge ID:</span>
              <span className="font-mono font-medium text-[#131921]">{chargeId}</span>
            </div>
            {claimId && (
              <div className="flex justify-between">
                <span className="text-slate-500">Associated Claim:</span>
                <span className="font-mono font-medium text-[#131921]">{claimId}</span>
              </div>
            )}
            <div className="flex justify-between">
              <span className="text-slate-500">Current Assessment:</span>
              <span className="font-semibold text-amber-600">
                {currentAssessment || "UNCERTAIN / UNCLAIMED"}
              </span>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-[#131921] uppercase tracking-wider mb-1.5">
              New Verdict <span className="text-rose-500">*</span>
            </label>
            <select
              value={verdict}
              onChange={(e) => setVerdict(e.target.value)}
              className="w-full px-3 py-2 bg-white border border-[#E5E7EB] rounded-lg text-sm text-[#131921] focus:outline-none focus:border-[#FF9900] font-medium"
            >
              <option value="APPROVED">APPROVED (Approve recovery claim)</option>
              <option value="REJECTED">REJECTED (Reject claim / Defect valid)</option>
              <option value="CLAIM_ELIGIBLE">CLAIM_ELIGIBLE (Mark eligible for dispute)</option>
              <option value="NOT_ELIGIBLE">NOT_ELIGIBLE (Mark non-recoverable)</option>
            </select>
          </div>

          <div>
            <label className="block text-xs font-semibold text-[#131921] uppercase tracking-wider mb-1.5">
              Reviewer / Operator ID
            </label>
            <input
              type="text"
              value={reviewerId}
              onChange={(e) => setReviewerId(e.target.value)}
              placeholder="e.g. operator_supervisor"
              className="w-full px-3 py-2 bg-white border border-[#E5E7EB] rounded-lg text-sm text-[#131921] focus:outline-none focus:border-[#FF9900] font-mono"
            />
          </div>

          <div>
            <label className="block text-xs font-semibold text-[#131921] uppercase tracking-wider mb-1.5">
              Override Justification Reason <span className="text-rose-500">*</span>
            </label>
            <textarea
              required
              rows={3}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="Detail specific physical or visual evidence why the automated AI agent verdict was overridden..."
              className="w-full px-3 py-2 bg-white border border-[#E5E7EB] rounded-lg text-xs text-[#131921] placeholder-slate-400 focus:outline-none focus:border-[#FF9900]"
            />
          </div>

          {error && (
            <div className="p-3 bg-rose-50 border border-rose-300 rounded-lg text-xs text-rose-700 flex items-center gap-2">
              <AlertTriangle className="w-4 h-4 shrink-0 text-rose-500" />
              <span>{error}</span>
            </div>
          )}

          {successMsg && (
            <div className="p-3 bg-emerald-50 border border-emerald-300 rounded-lg text-xs text-emerald-700 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600" />
              <span>{successMsg}</span>
            </div>
          )}

          {/* Footer Actions */}
          <div className="flex items-center justify-end gap-3 pt-3 border-t border-[#E5E7EB]">
            <button
              type="button"
              onClick={onClose}
              disabled={isSubmitting}
              className="px-4 py-2 text-xs font-medium text-slate-500 hover:text-[#131921] rounded-lg transition-colors cursor-pointer"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={isSubmitting}
              className="px-5 py-2 text-xs font-bold text-slate-950 bg-[#FF9900] hover:bg-[#E88A00] rounded-lg shadow-sm transition-all flex items-center gap-2 disabled:opacity-50 cursor-pointer"
            >
              {isSubmitting ? "Persisting Override..." : "Submit Override"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}


