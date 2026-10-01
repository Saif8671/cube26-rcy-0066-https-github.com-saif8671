import React from "react";
import { getStatusBadgeVariant } from "@/lib/utils";

export function StatusBadge({ status }: { status: string | null | undefined }) {
  const variant = getStatusBadgeVariant(status);
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${variant.bg} ${variant.text} ${variant.border}`}
    >
      {variant.label}
    </span>
  );
}
