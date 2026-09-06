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
    <div className="relative min-h-screen" style={{ background: "#090909", color: "#fff" }}>
      {/* full-bleed ambient money-flow graph — desaturated to monochrome so the
          canvas stays Framer-neutral (one accent only) */}
      <LoginGraph className="login-breathe pointer-events-none absolute inset-0 h-full w-full opacity-30 [filter:grayscale(1)] [mask-image:radial-gradient(90%_110%_at_52%_44%,#000_18%,transparent_72%)] [-webkit-mask-image:radial-gradient(90%_110%_at_52%_44%,#000_18%,transparent_72%)]" />
      <div className="relative mx-auto flex min-h-screen w-full max-w-[1060px] items-stretch">
        {/* left scrim — keeps the brand copy crisp over the graph */}
        <div
          aria-hidden
          className="pointer-events-none absolute inset-y-0 left-0 hidden w-[62%] lg:block"
          style={{ background: "linear-gradient(90deg, #090909 0%, rgba(9,9,9,.8) 55%, transparent 100%)" }}
        />

        {/* ── Left: brand / pillars (desktop only) ───────────────────────── */}
        <aside className="relative hidden w-[50%] flex-col justify-between p-10 lg:flex xl:p-12">
          <div className="login-rise relative flex items-center gap-3">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl border border-[#262626] bg-[#141414] font-mono text-sm font-bold text-white">
              IT
            </span>
            <div>
              <div className="text-[15px] font-semibold tracking-tight">ITTU</div>
              <div className="text-[12px] text-[#999]">Financial-crime forensics</div>
            </div>
          </div>

          <div className="relative">
            <h2
              className="login-rise max-w-[15ch] text-balance font-semibold text-white"
              style={{ animationDelay: "90ms", fontSize: "clamp(28px,3.4vw,40px)", lineHeight: 1.02, letterSpacing: "-0.035em" }}
            >
              From a scam report to a frozen account — in minutes, not days.
            </h2>

            <ul className="relative mt-8 space-y-3.5">
              {PILLARS.map((p, i) => (
                <li
                  key={p.name}
                  className="login-rise flex items-start gap-3"
                  style={{ animationDelay: `${200 + i * 80}ms` }}
                >
                  <span className="mt-0.5 flex h-6 w-6 flex-none items-center justify-center rounded-md border border-[#262626] bg-[#141414] font-mono text-[12px] font-bold text-white">
                    {p.k}
                  </span>
                  <div>
                    <div className="text-[13px] font-semibold text-white">{p.name}</div>
                    <div className="text-[12px] leading-snug text-[#999]">{p.desc}</div>
                  </div>
                </li>
              ))}
            </ul>
          </div>

          <div
            className="login-rise relative flex items-center gap-2 text-[12px] leading-relaxed text-[#999]"
            style={{ animationDelay: "560ms" }}
          >
            <span className="login-pulse h-1.5 w-1.5 flex-none rounded-full" style={{ background: "#0099ff" }} aria-hidden />
            <span>Secure session · agency-scoped (RLS) · every action hash-chained &amp; audited</span>
          </div>
        </aside>

        {/* ── Right: sign-in ─────────────────────────────────────────────── */}
        <main className="relative flex flex-1 items-center justify-center px-6 py-10">
          <div className="w-full max-w-[380px]">
            {/* mobile brand */}
            <header className="login-rise mb-7 flex flex-col items-center gap-2 lg:hidden">
              <span className="flex h-11 w-11 items-center justify-center rounded-xl border border-[#262626] bg-[#141414] font-mono text-sm font-bold text-white">
                IT
              </span>
              <div className="text-center">
                <h1 className="text-lg font-semibold tracking-tight">ITTU</h1>
                <p className="pt-1 text-[12px] font-medium tracking-wide text-[#999]">
                  Infiltrate · Trace · Takedown · Uncover
                </p>
              </div>
            </header>

            {/* desktop header — shield + title */}
            <div
              className="login-rise mb-5 hidden items-center gap-3 lg:flex"
              style={{ animationDelay: "80ms" }}
            >
              <span className="flex h-9 w-9 flex-none items-center justify-center rounded-lg border border-[#262626] bg-[#141414] text-white">
                <ShieldCheck />
              </span>
              <div>
                <h1 className="text-[17px] font-semibold tracking-tight">Secure sign-in</h1>
                <p className="text-[12px] text-[#999]">Choose your agency &amp; role to continue.</p>
              </div>
            </div>

            {/* form with soft halo */}
            <div className="login-rise relative" style={{ animationDelay: "160ms" }}>
              <div
                aria-hidden
                className="pointer-events-none absolute -inset-1.5 rounded-2xl blur-xl"
                style={{ background: "rgba(255,255,255,0.03)" }}
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
                  className="rounded-[10px] border border-[#262626] bg-[#141414] px-2 py-2 text-center"
                >
                  <div className="flex items-center justify-center gap-1 text-[12px] font-semibold text-white/80">
                    <span className="h-1 w-1 rounded-full" style={{ background: "#0099ff" }} aria-hidden />
                    {t.label}
                  </div>
                  <div className="mt-0.5 text-[12px] leading-tight text-[#999]">{t.sub}</div>
                </div>
              ))}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
