import React from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";

interface PaginationProps {
  total: number;
  limit: number;
  offset: number;
  onPageChange: (newOffset: number) => void;
  onLimitChange?: (newLimit: number) => void;
}

export function Pagination({
  total,
  limit,
  offset,
  onPageChange,
  onLimitChange,
}: PaginationProps) {
  const currentPage = Math.floor(offset / limit) + 1;
  const totalPages = Math.max(1, Math.ceil(total / limit));
  const startItem = total === 0 ? 0 : offset + 1;
  const endItem = Math.min(offset + limit, total);

  const hasPrev = offset > 0;
  const hasNext = offset + limit < total;

  return (
    <div className="flex flex-col sm:flex-row items-center justify-between gap-4 py-4 px-4 border-t border-[#E5E7EB] text-xs text-slate-500 bg-white">
      <div className="flex items-center gap-3">
        <span>
          Showing <strong className="text-[#131921] font-semibold">{startItem}</strong> to{" "}
          <strong className="text-[#131921] font-semibold">{endItem}</strong> of{" "}
          <strong className="text-[#131921] font-semibold">{total}</strong> records
        </span>

        {onLimitChange && (
          <div className="flex items-center gap-1.5 ml-2">
            <span>Per page:</span>
            <select
              value={limit}
              onChange={(e) => onLimitChange(Number(e.target.value))}
              className="bg-white border border-[#E5E7EB] text-[#131921] rounded px-2 py-1 text-xs focus:outline-none focus:border-[#FF9900]"
            >
              <option value={10}>10</option>
              <option value={25}>25</option>
              <option value={50}>50</option>
              <option value={100}>100</option>
            </select>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2">
        <span className="mr-2">
          Page <strong className="text-[#131921] font-semibold">{currentPage}</strong> of{" "}
          <strong className="text-[#131921] font-semibold">{totalPages}</strong>
        </span>

        <button
          type="button"
          disabled={!hasPrev}
          onClick={() => onPageChange(Math.max(0, offset - limit))}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-[#E5E7EB] bg-white text-[#131921] hover:bg-slate-50 disabled:opacity-40 disabled:pointer-events-none transition-colors shadow-xs"
        >
          <ChevronLeft className="w-3.5 h-3.5" /> Previous
        </button>

        <button
          type="button"
          disabled={!hasNext}
          onClick={() => onPageChange(offset + limit)}
          className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-[#E5E7EB] bg-white text-[#131921] hover:bg-slate-50 disabled:opacity-40 disabled:pointer-events-none transition-colors shadow-xs"
        >
          Next <ChevronRight className="w-3.5 h-3.5" />
        </button>
      </div>
    </div>
  );
}
