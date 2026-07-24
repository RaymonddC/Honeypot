import type { Metadata } from "next";
import { LoginForm } from "@/components/auth/login-form";
import { LoginGraph } from "@/components/auth/login-graph";

export const metadata: Metadata = {
  title: "Sign in — ITTU",
};

const PILLARS = [
  { k: "I", name: "Infiltrate", desc: "AI honeypot baits the scammer & extracts intel" },
  { k: "T", name: "Trace", desc: "Follow the money across the fiat→crypto bridge" },
  { k: "T", name: "Takedown", desc: "Score wallets, surface the collection wallet" },
  { k: "U", name: "Uncover", desc: "One-click freeze requests & STR / LTKM filings" },
];

const TRUST = [
  { label: "Encrypted", sub: "in transit & at rest" },
  { label: "Agency-isolated", sub: "row-level security" },
  { label: "Audit trail", sub: "hash-chained" },
];

function ShieldCheck() {
  return (
    <svg viewBox="0 0 24 24" className="h-5 w-5" fill="none" aria-hidden>
      <path
        d="M12 3l7 2.5v5.5c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V5.5L12 3z"
        stroke="currentColor"
        strokeWidth="1.6"
        strokeLinejoin="round"
      />
      <path
        d="M9 12.2l2.1 2.1L15 10.5"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

export default function LoginPage() {
  return (
    <div className="relative min-h-screen bg-bg">
      {/* full-bleed ambient money-flow graph — densest in the empty middle,
          fading toward both text columns and the page edges */}
      <LoginGraph className="login-breathe pointer-events-none absolute inset-0 h-full w-full opacity-40 [mask-image:radial-gradient(90%_110%_at_52%_44%,#000_18%,transparent_72%)] [-webkit-mask-image:radial-gradient(90%_110%_at_52%_44%,#000_18%,transparent_72%)]" />
      {/* faint scan-grid */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          backgroundImage:
            "linear-gradient(rgba(255,255,255,0.02) 1px, transparent 1px), linear-gradient(90deg, rgba(255,255,255,0.02) 1px, transparent 1px)",
          backgroundSize: "46px 46px",
          maskImage: "radial-gradient(760px 560px at 52% 44%, #000 25%, transparent 75%)",
          WebkitMaskImage: "radial-gradient(760px 560px at 52% 44%, #000 25%, transparent 75%)",
        }}
      />
      <div className="relative mx-auto flex min-h-screen w-full max-w-[1060px] items-stretch">
        {/* left scrim — keeps the brand copy crisp over the graph */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-0 hidden w-[62%] bg-gradient-to-r from-bg via-bg/80 to-transparent lg:block"
        />

        {/* ── Left: brand / pillars (desktop only) ───────────────────────── */}
        <aside className="relative hidden w-[50%] flex-col justify-between p-10 lg:flex xl:p-12">
          <div className="login-rise relative flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-accent/25 bg-accent/10 font-mono text-sm font-bold text-accent-bright shadow-[0_0_24px_-6px_rgba(16,185,129,0.55)]">
              IT
            </span>
            <div>
              <div className="text-[15px] font-semibold tracking-wide">ITTU</div>
              <div className="text-[11px] text-muted">Financial-crime forensics</div>
            </div>
          </div>

          <div className="relative">
            <h2
              className="login-rise max-w-[18rem] text-balance text-[26px] font-bold leading-[1.22] tracking-tight text-fg"
              style={{ animationDelay: "90ms" }}
            >
              From a scam report to a frozen account —{" "}
              <span className="text-accent-bright">in minutes, not days.</span>
            </h2>

            <ul className="relative mt-8 space-y-3.5">
              {PILLARS.map((p, i) => (
                <li
                  key={p.name}
                  className="login-rise flex items-start gap-3"
                  style={{ animationDelay: `${200 + i * 80}ms` }}
                >
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

          <div
            className="login-rise relative flex items-center gap-2 text-[11px] leading-relaxed text-muted"
            style={{ animationDelay: "560ms" }}
          >
            <span className="login-pulse h-1.5 w-1.5 flex-none rounded-full bg-accent" aria-hidden />
            <span>Secure session · agency-scoped (RLS) · every action hash-chained &amp; audited</span>
          </div>
        </aside>

        {/* ── Right: sign-in ─────────────────────────────────────────────── */}
        <main className="relative flex flex-1 items-center justify-center px-6 py-10">
          <div className="w-full max-w-[380px]">
            {/* mobile brand */}
            <header className="login-rise mb-7 flex flex-col items-center gap-2 lg:hidden">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-accent/25 bg-accent/10 font-mono text-sm font-bold text-accent-bright shadow-[0_0_24px_-6px_rgba(16,185,129,0.55)]">
                IT
              </span>
              <div className="text-center">
                <h1 className="text-lg font-semibold tracking-wide">ITTU</h1>
                <p className="eyebrow pt-1">Infiltrate · Trace · Takedown · Uncover</p>
              </div>
            </header>

            {/* desktop header — shield + title */}
            <div
              className="login-rise mb-5 hidden items-center gap-3 lg:flex"
              style={{ animationDelay: "80ms" }}
            >
              <span className="flex h-9 w-9 flex-none items-center justify-center rounded-lg border border-accent/25 bg-accent/10 text-accent-bright">
                <ShieldCheck />
              </span>
              <div>
                <h1 className="text-[17px] font-semibold tracking-tight">Secure sign-in</h1>
                <p className="text-[12px] text-muted">Choose your agency &amp; role to continue.</p>
              </div>
            </div>

            {/* form with soft halo */}
            <div className="login-rise relative" style={{ animationDelay: "160ms" }}>
              <div
                aria-hidden
                className="pointer-events-none absolute -inset-1.5 rounded-2xl bg-accent/[.05] blur-xl"
              />
              <div className="relative">
                <LoginForm />
              </div>
            </div>

            {/* trust badges — anchors the form, fills the space */}
            <div
              className="login-rise mt-4 grid grid-cols-3 gap-2"
              style={{ animationDelay: "240ms" }}
            >
              {TRUST.map((t) => (
                <div
                  key={t.label}
                  className="rounded-lg border border-line bg-card/60 px-2 py-2 text-center"
                >
                  <div className="flex items-center justify-center gap-1 text-[10.5px] font-semibold text-fg/80">
                    <span className="h-1 w-1 rounded-full bg-accent" aria-hidden />
                    {t.label}
                  </div>
                  <div className="mt-0.5 text-[9.5px] leading-tight text-muted">{t.sub}</div>
                </div>
              ))}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
