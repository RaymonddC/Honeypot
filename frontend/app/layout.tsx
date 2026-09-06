import type { Metadata } from "next";
import { Hanken_Grotesk, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { THEME_INIT_SCRIPT } from "./theme-init";
import { AuthProvider } from "@/components/auth/auth-provider";
import { CaseProvider } from "@/components/cases/case-provider";
import { AppGate } from "@/components/auth/app-gate";
import { LocaleProvider } from "@/components/i18n/locale-provider";
import { ThemeProvider } from "@/components/theme/theme-provider";

// Corporate/neutral redesign: Inter for UI text, JetBrains Mono reserved for
// technical data (wallet addresses, hashes, account numbers) — see
// app/globals.css's --font-ui / --font-mono, which these variables feed.
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
  // No forced "dark" class here — light is the default ground now (see
  // globals.css). Dark applies via the system's prefers-color-scheme, OR an
  // explicit .dark class the inline script below adds before paint if the
  // user picked "dark" in the Control Panel's theme toggle (ThemeProvider /
  // useTheme in components/theme/theme-provider.tsx).
  return (
    <html
      lang="en"
      className={`${sans.variable} ${jetbrainsMono.variable}`}
      // The pre-hydration script above adds/removes .dark on this element
      // BEFORE React hydrates, based on a value (localStorage) the server
      // can't see — so client/server className will legitimately differ on
      // first render whenever "dark" is the stored choice. That's the
      // intended fix for theme flash, not a bug; suppress the one-time
      // hydration warning it would otherwise cause.
      suppressHydrationWarning
    >
      <head>
        {/* Must run before paint to avoid a flash of the wrong theme — see
            app/theme-init.ts for why this can't be a React effect. */}
        <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
      </head>
      <body className="bg-bg text-fg antialiased">
        <ThemeProvider>
          <LocaleProvider>
            <AuthProvider>
              <CaseProvider>
                <AppGate>{children}</AppGate>
              </CaseProvider>
            </AuthProvider>
          </LocaleProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
