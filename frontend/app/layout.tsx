import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/components/auth/auth-provider";
import { CaseProvider } from "@/components/cases/case-provider";
import { AppGate } from "@/components/auth/app-gate";
import { LocaleProvider } from "@/components/i18n/locale-provider";

// Corporate/neutral redesign: Inter for UI text, JetBrains Mono reserved for
// technical data (wallet addresses, hashes, account numbers) — see
// app/globals.css's --font-ui / --font-mono, which these variables feed.
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-ui",
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
  // No forced "dark" class here — light is the default ground now (see
  // globals.css); dark applies only via the system's prefers-color-scheme
  // or an explicit .dark class from a future theme toggle.
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable}`}>
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
