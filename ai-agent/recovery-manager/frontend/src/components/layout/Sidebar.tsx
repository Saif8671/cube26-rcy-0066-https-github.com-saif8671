"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  Receipt,
  AlertTriangle,
  FileCheck2,
  Database,
  UploadCloud,
  Settings,
  ShieldCheck,
  Server,
} from "lucide-react";
import { api } from "@/lib/api";

export function Sidebar() {
  const pathname = usePathname();
  const [pendingCount, setPendingCount] = useState<number | null>(null);
  const [backendStatus, setBackendStatus] = useState<"ok" | "degraded" | "offline">("ok");

  useEffect(() => {
    let isMounted = true;

    async function fetchNavMeta() {
      try {
        const [pendingResp, healthResp] = await Promise.allSettled([
          api.getPendingReviewCharges(),
          api.getHealth(),
        ]);

        if (isMounted) {
          if (pendingResp.status === "fulfilled") {
            setPendingCount(pendingResp.value.total);
          }
          if (healthResp.status === "fulfilled") {
            setBackendStatus(healthResp.value.status === "ok" ? "ok" : "degraded");
          } else {
            setBackendStatus("offline");
          }
        }
      } catch {
        if (isMounted) {
          setBackendStatus("offline");
        }
      }
    }

    fetchNavMeta();
    // Refresh badge periodically every 30s
    const timer = setInterval(fetchNavMeta, 30000);
    return () => {
      isMounted = false;
      clearInterval(timer);
    };
  }, [pathname]);

  const navItems = [
    {
      label: "Dashboard",
      href: "/dashboard",
      icon: LayoutDashboard,
      isActive: pathname === "/dashboard",
    },
    {
      label: "Marketplace Charges",
      href: "/charges",
      icon: Receipt,
      isActive: pathname === "/charges" || (pathname.startsWith("/charges/") && pathname !== "/charges/pending-review"),
    },
    {
      label: "Pending Review",
      href: "/charges/pending-review",
      icon: AlertTriangle,
      badge: pendingCount !== null && pendingCount > 0 ? pendingCount : null,
      badgeColor: "bg-amber-500/20 text-amber-300 border-amber-500/40",
      isActive: pathname === "/charges/pending-review",
    },
    {
      label: "Recovery Claims",
      href: "/claims",
      icon: FileCheck2,
      isActive: pathname.startsWith("/claims"),
    },
    {
      label: "Operational Evidence",
      href: "/evidence",
      icon: Database,
      isActive: pathname.startsWith("/evidence"),
    },
    {
      label: "Ingestion & Upload",
      href: "/upload",
      icon: UploadCloud,
      isActive: pathname.startsWith("/upload"),
    },
    {
      label: "System Settings",
      href: "/settings",
      icon: Settings,
      isActive: pathname.startsWith("/settings"),
    },
  ];

  return (
    <aside className="w-64 bg-white border-r border-[#E5E7EB] flex flex-col shrink-0 min-h-screen text-slate-700 select-none">
      {/* Brand Header */}
      <div className="p-5 border-b border-[#E5E7EB]">
        <Link href="/dashboard" className="flex items-center gap-3 group">
          <div className="w-10 h-10 rounded-xl bg-white border border-slate-200 flex items-center justify-center p-1.5 shadow-sm group-hover:scale-105 transition-transform overflow-hidden shrink-0">
            <Image
              src="/logo-transparent.png"
              alt="Recovery Manager Logo"
              width={36}
              height={36}
              className="w-full h-full object-contain"
              priority
            />
          </div>
          <div>
            <div className="text-sm font-bold text-[#131921] tracking-tight flex items-center gap-1.5">
              Recovery Manager
            </div>
            <div className="text-[11px] text-[#D97706] font-mono font-medium">Evidence-First Ops</div>
          </div>
        </Link>
      </div>

      {/* Nav List */}
      <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
        <div className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wider text-slate-400">
          Navigation
        </div>
        {navItems.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center justify-between px-3 py-2.5 rounded-lg text-xs font-medium transition-all ${
                item.isActive
                  ? "bg-[#FF9900]/10 text-[#D97706] border border-[#FF9900]/40 shadow-xs font-semibold"
                  : "text-slate-600 hover:text-[#131921] hover:bg-slate-100 border border-transparent"
              }`}
            >
              <div className="flex items-center gap-3">
                <Icon className={`w-4 h-4 ${item.isActive ? "text-[#D97706]" : "text-slate-400"}`} />
                <span>{item.label}</span>
              </div>
              {item.badge !== undefined && item.badge !== null && (
                <span
                  className={`text-[11px] font-semibold px-2 py-0.5 rounded-full border ${item.badgeColor}`}
                >
                  {item.badge}
                </span>
              )}
            </Link>
          );
        })}
      </nav>

      {/* System Status Footer */}
      <div className="p-3 border-t border-[#E5E7EB] bg-slate-50/80">
        <div className="p-2.5 rounded-lg bg-white border border-[#E5E7EB] flex items-center justify-between shadow-xs">
          <div className="flex items-center gap-2">
            <Server className="w-3.5 h-3.5 text-slate-500" />
            <span className="text-[11px] text-slate-500 font-medium">Backend API</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span
              className={`w-2 h-2 rounded-full ${
                backendStatus === "ok"
                  ? "bg-emerald-500 animate-pulse"
                  : backendStatus === "degraded"
                  ? "bg-amber-500"
                  : "bg-rose-500"
              }`}
            />
            <span className="text-[11px] font-mono capitalize text-slate-700 font-medium">
              {backendStatus}
            </span>
          </div>
        </div>
      </div>
    </aside>
  );
}
