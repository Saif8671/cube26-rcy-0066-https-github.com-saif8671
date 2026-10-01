import type { Metadata } from "next";
import "./globals.css";
import { AppShell } from "@/components/layout/AppShell";

export const metadata: Metadata = {
  title: "Recovery Manager | Evidence-First Recovery Ops",
  description: "Internal operations console for marketplace fee dispute recovery and deterministic evidence traceability.",
  icons: {
    icon: "/logo-transparent.png",
    shortcut: "/favicon.ico",
    apple: "/logo-transparent.png",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="h-full" suppressHydrationWarning>
      <body
        className="h-full bg-[#F9FAFB] text-[#131921] antialiased"
        suppressHydrationWarning
      >
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}

