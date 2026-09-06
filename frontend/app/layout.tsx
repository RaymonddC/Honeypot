import type { Metadata } from "next";
import { Hanken_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/components/auth/auth-provider";
import { CaseProvider } from "@/components/cases/case-provider";
import { AppGate } from "@/components/auth/app-gate";
import { LocaleProvider } from "@/components/i18n/locale-provider";

// Hanken Grotesk for UI text, JetBrains Mono reserved for technical data
// (wallet addresses, hashes, account numbers) — see app/globals.css's
// --font-ui / --font-mono, which these variables feed.
const sans = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-ui-next",
  display: "swap",
});
const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "ITTU — Financial Crime Forensics",
  description:
    "Infiltrate, Trace, Takedown & Uncover — AI-powered financial-crime forensics platform.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    // ITTU is dark-only (single palette in globals.css), so there is no stored
    // theme choice to read before paint — no pre-hydration script, and nothing
    // that could differ between server and client, so no suppressHydrationWarning.
    <html lang="en" className={`${sans.variable} ${jetbrainsMono.variable}`}>
      <body className="bg-bg text-fg antialiased">
        <LocaleProvider>
          <AuthProvider>
            <CaseProvider>
              <AppGate>{children}</AppGate>
            </CaseProvider>
          </AuthProvider>
        </LocaleProvider>
      </body>
    </html>
  );
}
