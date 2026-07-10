import type { Metadata } from "next";
import { LoginForm } from "@/components/auth/login-form";

export const metadata: Metadata = {
  title: "Sign in — ITTU",
};

export default function LoginPage() {
  return (
    <div className="relative flex min-h-screen flex-col items-center justify-center bg-bg px-4 py-10">
      {/* Faint emerald glow behind the card */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(600px 320px at 50% 32%, rgba(16,185,129,0.07), transparent 70%)",
        }}
      />

      <header className="relative mb-8 flex flex-col items-center gap-3">
        <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-accent/25 bg-accent/10 font-mono text-sm font-bold text-accent-bright">
          IT
        </span>
        <div className="text-center">
          <h1 className="text-lg font-semibold tracking-wide">ITTU</h1>
          <p className="eyebrow pt-1">
            Infiltrate · Trace · Takedown · Uncover
          </p>
        </div>
      </header>

      <main className="relative flex w-full justify-center">
        <LoginForm />
      </main>

      <footer className="relative pt-8 text-center text-[11px] leading-relaxed text-muted">
        Multi-agency financial-crime forensics console
        <br />
        Access is agency-scoped (RLS) and fully audited.
      </footer>
    </div>
  );
}
