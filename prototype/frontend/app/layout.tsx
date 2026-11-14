import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "JourneyRelay",
  description: "Cathay Hackathon 2026 概念原型（示範資料）",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

// No global navigation: each surface (passenger app, staff tablet, demo,
// ops board) brings its own chrome, so it can be embedded in the demo frames.
export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-Hant-HK">
      <body>{children}</body>
    </html>
  );
}
