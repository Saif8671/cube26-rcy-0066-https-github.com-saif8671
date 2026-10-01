import React from "react";
import { getAssessmentBadgeVariant } from "@/lib/utils";

export function AssessmentBadge({ assessment }: { assessment: string | null | undefined }) {
  const variant = getAssessmentBadgeVariant(assessment);
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${variant.bg} ${variant.text} ${variant.border}`}
    >
      {variant.label}
    </span>
  );
}
