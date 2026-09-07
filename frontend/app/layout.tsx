import type { Metadata } from "next";
import { Hanken_Grotesk } from "next/font/google";
import "./globals.css";
import { AuthProvider } from "@/components/auth/auth-provider";
import { CaseProvider } from "@/components/cases/case-provider";
import { AppGate } from "@/components/auth/app-gate";
import { LocaleProvider } from "@/components/i18n/locale-provider";

// Hanken Grotesk is the app's only face — see --font-ui in app/globals.css,
// which this variable feeds. There is no monospace face: addresses, hashes and
// figures are set in the UI face with tabular numerals (.tnum) where columns
// need to line up.
//
// Both use a "-next" suffix so they DON'T collide with the tokens globals.css
// defines. next/font emits its variable via a class on <html>, and :root has
// the same specificity (0,1,0) — so with a shared name the tie breaks on source
// order, globals.css wins, and next/font's value is silently discarded along
// with the "… Fallback" family it generates. That fallback is metric-adjusted
// to match the real face, and it is what stops text reflowing when the webfont
// lands under `display: swap`.
const sans = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-ui-next",
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
    <html lang="en" className={sans.variable}>
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
