import type { Metadata } from "next";
import type { ReactNode } from "react";
import { Nav } from "@/components/nav";
import { THEME_BOOTSTRAP } from "@/lib/theme-bootstrap";
import { Providers } from "./providers";
import "./globals.css";

export const metadata: Metadata = {
  title: "interview_helper",
  description: "Adaptive mock-interview trainer for SWE and quant-trading loops",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    // suppressHydrationWarning: the bootstrap script may set data-theme before React
    // hydrates, and that one attribute differing from the server's HTML is intended.
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP }} />
      </head>
      <body className="bg-page min-h-screen">
        <Providers>
          <Nav />
          <main className="mx-auto max-w-7xl px-4 py-6">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
