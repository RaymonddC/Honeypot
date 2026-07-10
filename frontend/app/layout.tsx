import type { Metadata } from "next";
import "./globals.css";
import { AuthProvider } from "@/components/auth/auth-provider";
import { AppGate } from "@/components/auth/app-gate";

export const metadata: Metadata = {
  title: "ITTU — Financial Crime Forensics",
  description:
    "Infiltrate, Trace, Takedown & Uncover — AI-powered financial-crime forensics platform.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className="dark">
      <body className="bg-bg text-fg antialiased">
        <AuthProvider>
          <AppGate>{children}</AppGate>
        </AuthProvider>
      </body>
    </html>
  );
}
