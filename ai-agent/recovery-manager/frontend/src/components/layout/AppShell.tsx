"use client";

import React from "react";
import { usePathname } from "next/navigation";
import { Sidebar } from "@/components/layout/Sidebar";

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const isLandingPage = pathname === "/";

  if (isLandingPage) {
    return (
      <div className="min-h-screen w-full bg-white text-[#131921] flex flex-col font-sans selection:bg-[#FF9900]/30 selection:text-amber-900">
        {children}
      </div>
    );
  }

  return (
    <div className="h-full flex overflow-hidden font-sans bg-white text-[#131921] selection:bg-[#FF9900]/30 selection:text-amber-900">
      <Sidebar />
      <main className="flex-1 flex flex-col min-w-0 overflow-y-auto bg-[#F9FAFB]">
        <div className="flex-1 p-6 md:p-8 max-w-7xl mx-auto w-full">
          {children}
        </div>
      </main>
    </div>
  );
}
