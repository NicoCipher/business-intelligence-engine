import type { Metadata } from "next";
import localFont from "next/font/local";

import "@/app/globals.css";

const geist = localFont({ src: "./fonts/geist-latin.woff2", variable: "--font-sans", display: "swap" });
const geistMono = localFont({ src: "./fonts/geist-mono-latin.woff2", variable: "--font-mono", display: "swap" });

export const metadata: Metadata = {
  title: { default: "BIA Operations Console", template: "%s · BIA Operations" },
  description: "Internal operations console for the BIA intelligence platform.",
  robots: { index: false, follow: false }
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${geist.variable} ${geistMono.variable}`}>
      <body>
        <a className="skip-link" href="#main-content">Skip to content</a>
        {children}
      </body>
    </html>
  );
}
