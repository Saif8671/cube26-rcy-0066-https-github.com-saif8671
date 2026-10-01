import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatCurrency(
  value: string | number | null | undefined,
  currency: string = "USD"
): string {
  if (value === null || value === undefined || value === "") {
    return "—";
  }
  const numeric = typeof value === "number" ? value : parseFloat(value);
  if (isNaN(numeric)) {
    return "—";
  }
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: currency || "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(numeric);
}

export function formatDate(dateString: string | null | undefined): string {
  if (!dateString) return "—";
  try {
    const d = new Date(dateString);
    if (isNaN(d.getTime())) return dateString;
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    }).format(d);
  } catch {
    return dateString;
  }
}

export function getStatusBadgeVariant(status: string | null | undefined): {
  bg: string;
  text: string;
  border: string;
  label: string;
} {
  if (!status) {
    return {
      bg: "bg-slate-800/40",
      text: "text-slate-400",
      border: "border-slate-700/50",
      label: "—",
    };
  }

  const s = status.toUpperCase();

  switch (s) {
    case "READY_FOR_REVIEW":
      return {
        bg: "bg-emerald-500/10",
        text: "text-emerald-400",
        border: "border-emerald-500/30",
        label: "Ready for Review",
      };
    case "PROCESSED":
      return {
        bg: "bg-sky-500/10",
        text: "text-sky-400",
        border: "border-sky-500/30",
        label: "Processed",
      };
    case "PENDING":
      return {
        bg: "bg-amber-500/10",
        text: "text-amber-400",
        border: "border-amber-500/30",
        label: "Pending",
      };
    case "APPROVED":
      return {
        bg: "bg-emerald-500/10",
        text: "text-emerald-400",
        border: "border-emerald-500/30",
        label: "Approved",
      };
    case "REJECTED":
      return {
        bg: "bg-rose-500/10",
        text: "text-rose-400",
        border: "border-rose-500/30",
        label: "Rejected",
      };
    case "DUPLICATE":
      return {
        bg: "bg-purple-500/10",
        text: "text-purple-400",
        border: "border-purple-500/30",
        label: "Duplicate",
      };
    case "ALREADY_REIMBURSED":
      return {
        bg: "bg-indigo-500/10",
        text: "text-indigo-400",
        border: "border-indigo-500/30",
        label: "Already Reimbursed",
      };
    default:
      return {
        bg: "bg-slate-800/40",
        text: "text-slate-300",
        border: "border-slate-700/50",
        label: status,
      };
  }
}

export function getAssessmentBadgeVariant(assessment: string | null | undefined): {
  bg: string;
  text: string;
  border: string;
  label: string;
} {
  if (!assessment) {
    return {
      bg: "bg-slate-800/40",
      text: "text-slate-400",
      border: "border-slate-700/50",
      label: "—",
    };
  }

  const a = assessment.toUpperCase();

  switch (a) {
    case "CONTRADICTED":
      return {
        bg: "bg-emerald-500/10",
        text: "text-emerald-400",
        border: "border-emerald-500/30",
        label: "Contradicted (Dispute Eligible)",
      };
    case "SUPPORTED":
      return {
        bg: "bg-blue-500/10",
        text: "text-blue-400",
        border: "border-blue-500/30",
        label: "Supported (Fee Valid)",
      };
    case "UNCERTAIN":
      return {
        bg: "bg-amber-500/10",
        text: "text-amber-400",
        border: "border-amber-500/30",
        label: "Uncertain (Human Review)",
      };
    case "SILENT":
      return {
        bg: "bg-slate-800/40",
        text: "text-slate-400",
        border: "border-slate-700/50",
        label: "Silent (No Evidence)",
      };
    default:
      return {
        bg: "bg-slate-800/40",
        text: "text-slate-300",
        border: "border-slate-700/50",
        label: assessment,
      };
  }
}
