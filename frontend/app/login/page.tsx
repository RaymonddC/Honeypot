import type { Metadata } from "next";
import { LoginForm } from "@/components/auth/login-form";

export const metadata: Metadata = {
  title: "Sign in — ITTU",
};

const PILLARS = [
  { k: "I", name: "Infiltrate", desc: "AI honeypot baits the scammer & extracts intel" },
  { k: "T", name: "Trace", desc: "Follow the money across the fiat→crypto bridge" },
  { k: "T", name: "Takedown", desc: "Score wallets, surface the collection wallet" },
  { k: "U", name: "Uncover", desc: "One-click freeze requests & STR / LTKM filings" },
];

export default function LoginPage() {
  return (
    <div className="relative flex min-h-screen bg-bg">
      {/* Faint emerald glow */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(680px 360px at 28% 30%, rgba(16,185,129,0.08), transparent 70%)",
        }}
      />

      {/* ── Left: brand / pillars (desktop only) ─────────────────────────── */}
      <aside className="relative hidden w-[46%] max-w-[560px] flex-col justify-between border-r border-line bg-sidebar/40 p-10 lg:flex">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-accent/25 bg-accent/10 font-mono text-sm font-bold text-accent-bright">
            IT
          </span>
          <div>
            <div className="text-[15px] font-semibold tracking-wide">ITTU</div>
            <div className="text-[11px] text-muted">Financial-crime forensics</div>
          </div>
        </div>

        <div>
          <h2 className="max-w-[22ch] text-[22px] font-bold leading-snug tracking-tight text-fg">
            From a scam report to a frozen account — in minutes, not days.
          </h2>
          <ul className="mt-6 space-y-3">
            {PILLARS.map((p) => (
              <li key={p.name} className="flex items-start gap-3">
                <span className="mt-0.5 flex h-6 w-6 flex-none items-center justify-center rounded-md bg-accent/12 font-mono text-[11px] font-bold text-accent-bright">
                  {p.k}
                </span>
                <div>
                  <div className="text-[13px] font-semibold text-fg">{p.name}</div>
                  <div className="text-[11.5px] leading-snug text-muted">{p.desc}</div>
                </div>
              </li>
            ))}
          </ul>
        </div>

        <p className="text-[11px] leading-relaxed text-muted">
          Multi-agency console — every agency sees only its own cases
          (row-level security), and every action is hash-chained &amp; audited.
        </p>
      </aside>

      {/* ── Right: sign-in ───────────────────────────────────────────────── */}
      <main className="relative flex flex-1 items-center justify-center px-4 py-10">
        <div className="w-full max-w-sm">
          {/* compact brand for mobile (left panel hidden) */}
          <header className="mb-6 flex flex-col items-center gap-2 lg:hidden">
            <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-accent/25 bg-accent/10 font-mono text-sm font-bold text-accent-bright">
              IT
            </span>
            <div className="text-center">
              <h1 className="text-lg font-semibold tracking-wide">ITTU</h1>
              <p className="eyebrow pt-1">Infiltrate · Trace · Takedown · Uncover</p>
            </div>
          </header>

          <div className="mb-4 hidden lg:block">
            <h1 className="text-lg font-semibold tracking-tight">Sign in</h1>
            <p className="text-[12px] text-muted">
              Choose your agency &amp; role to enter the console.
            </p>
          </div>

          <LoginForm />

          <p className="mt-5 text-center text-[11px] leading-relaxed text-muted">
            Access is agency-scoped and fully audited.
          </p>
        </div>
      </main>
    </div>
  );
}
