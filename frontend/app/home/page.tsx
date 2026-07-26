"use client";

/**
 * Home — the front door. Two clearly separated paths so an investigator always
 * knows what to do:
 *   1. THE CASE FLOW (guided) — start/continue a case that walks the real
 *      lifecycle (intake → freeze → trace → takedown → report → recovery).
 *   2. QUICK TOOLS (ad hoc) — standalone tasks you can run without a case
 *      (trace a wallet, run a honeypot, look at the bridge…).
 * Same ELSA theme (cards, eyebrows, emerald accent) as the rest of the app.
 */

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCases } from "@/components/cases/case-provider";

const STAGE_TASK: Record<string, string> = {
  intake: "Surface suspect accounts & wallets",
  freeze: "Generate & dispatch the freeze request",
  trace: "Trace the money flow",
  takedown: "Score the wallet network",
  report: "File the STR / LTKM",
  recovery: "Track fund recovery",
  closed: "Case closed",
};

type Tool = {
  glyph: string;
  title: string;
  desc: string;
  href: string;
};

const TOOLS: Tool[] = [
  { glyph: "⬡", title: "Run a honeypot", desc: "Engage a scammer with an AI persona; extract wallets & accounts.", href: "/honeypot" },
  { glyph: "⇌", title: "Bridge / BridgeWatch", desc: "See the fiat → QRIS → crypto money flow as a Sankey.", href: "/bridge" },
  { glyph: "◉", title: "Investigate a wallet", desc: "Trace a wallet's network and score its risk.", href: "/investigation" },
  { glyph: "⚑", title: "Action documents", desc: "Generate freeze requests & suspicious-transaction reports.", href: "/actions" },
  { glyph: "▦", title: "Command Center", desc: "Agency-wide metrics: funds at risk / frozen, recovery rate, time-to-freeze.", href: "/response" },
];

function Glyph({ children }: { children: React.ReactNode }) {
  return (
    <span
      className="flex h-8 w-8 flex-none items-center justify-center rounded-lg bg-accent/10 text-base text-accent-bright"
      aria-hidden
    >
      {children}
    </span>
  );
}

export default function HomePage() {
  const router = useRouter();
  const { cases, activeCase, setActiveCase, createCase } = useCases();
  const [wallet, setWallet] = useState("");
  const [creating, setCreating] = useState(false);

  const recent = cases.slice(0, 4);

  // New report = open a fresh case; the Case File opens straight on its Intake
  // stage (the single victim-report form now lives there).
  const startReport = async () => {
    setCreating(true);
    try {
      await createCase({ title: `Scam report — ${new Date().toISOString().slice(0, 10)}` });
      router.push("/case");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="mx-auto max-w-[980px]">
      <div className="mb-5">
        <div className="eyebrow mb-1">ITTU · financial-crime forensics</div>
        <h1 className="text-2xl font-bold tracking-tight">What do you want to do?</h1>
        <p className="mt-1 text-xs text-muted">
          Work a case through the guided flow, or jump straight to a tool.
        </p>
      </div>

      {/* ── 1. THE CASE FLOW (guided) ─────────────────────────────────── */}
      <section className="mb-6">
        <div className="eyebrow mb-2 flex items-center gap-2">
          <span className="text-accent-bright">1 · Case workflow</span>
          <span className="text-muted/60">— the guided investigation</span>
        </div>

        <div className="rounded-card border border-accent/25 bg-accent/[.05] p-4">
          {activeCase ? (
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="text-[11px] text-muted">Active case</div>
                <div className="flex items-center gap-2.5">
                  <span className="truncate text-lg font-semibold text-fg">
                    {activeCase.title}
                  </span>
                  <span className="rounded border border-accent/30 bg-accent/10 px-1.5 py-0.5 text-[9.5px] font-bold uppercase tracking-wide text-accent-bright">
                    {activeCase.stage}
                  </span>
                </div>
                <div className="mt-0.5 text-[12px] text-muted">
                  Next: {STAGE_TASK[activeCase.stage] ?? "—"}
                </div>
              </div>
              <div className="flex gap-2">
                <Link
                  href="/case"
                  className="h-9 rounded-lg bg-accent px-4 text-xs font-semibold leading-9 text-[#04140d] transition-colors hover:bg-accent-bright"
                >
                  Continue case →
                </Link>
                <button
                  type="button"
                  onClick={startReport}
                  disabled={creating}
                  className="h-9 rounded-lg border border-white/10 bg-elevated px-4 text-xs font-semibold text-fg transition-colors hover:bg-white/[.07] disabled:opacity-60"
                >
                  {creating ? "Opening…" : "New report"}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-wrap items-center justify-between gap-4">
              <div>
                <div className="text-[14px] font-semibold text-fg">
                  Start a new investigation
                </div>
                <p className="mt-0.5 max-w-[52ch] text-[12px] text-muted">
                  Most cases begin with a victim report — log it, and the app opens
                  the case, records the account, and can freeze it in one step.
                </p>
              </div>
              <button
                type="button"
                onClick={startReport}
                disabled={creating}
                className="h-9 rounded-lg bg-accent px-4 text-xs font-semibold text-[#04140d] transition-colors hover:bg-accent-bright disabled:opacity-60"
              >
                {creating ? "Opening…" : "✎ New report (Intake) →"}
              </button>
            </div>
          )}

          {recent.length > 0 && (
            <div className="mt-3.5 border-t border-accent/15 pt-3">
              <div className="mb-1.5 text-[10.5px] uppercase tracking-wide text-muted">
                Recent cases
              </div>
              <div className="flex flex-wrap gap-2">
                {recent.map((c) => (
                  <button
                    key={c.id}
                    type="button"
                    onClick={() => {
                      setActiveCase(c.id);
                      router.push("/case");
                    }}
                    className="flex items-center gap-2 rounded-lg border border-line bg-card px-2.5 py-1.5 text-left text-[12px] transition-colors hover:border-white/15"
                  >
                    <span className="max-w-[14rem] truncate text-fg">{c.title}</span>
                    <span className="text-[9.5px] uppercase text-muted">{c.stage}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </section>

      {/* ── 2. QUICK TOOLS (ad hoc) ───────────────────────────────────── */}
      <section>
        <div className="eyebrow mb-2 flex items-center gap-2">
          <span>2 · Quick tools</span>
          <span className="text-muted/60">— run a task standalone, no case needed</span>
        </div>

        {/* immediate task: trace a wallet */}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (wallet.trim())
              router.push(`/investigation?address=${encodeURIComponent(wallet.trim())}`);
          }}
          className="mb-3 flex gap-2"
        >
          <div className="flex h-[38px] flex-1 items-center gap-2 rounded-lg border border-white/10 bg-card px-3">
            <span className="text-muted" aria-hidden>⌕</span>
            <input
              value={wallet}
              onChange={(e) => setWallet(e.target.value)}
              spellCheck={false}
              placeholder="Paste a wallet address to trace it…"
              className="min-w-0 flex-1 bg-transparent font-mono text-[12.5px] text-fg outline-none placeholder:text-muted"
            />
          </div>
          <button
            type="submit"
            className="h-[38px] rounded-lg bg-accent px-4 text-xs font-semibold text-[#04140d] transition-colors hover:bg-accent-bright"
          >
            Trace →
          </button>
        </form>

        <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
          {TOOLS.map((t) => (
            <Link
              key={t.href}
              href={t.href}
              className="group flex gap-3 rounded-card border border-line bg-card p-3.5 transition-colors hover:border-white/15"
            >
              <Glyph>{t.glyph}</Glyph>
              <div className="min-w-0">
                <div className="text-[13px] font-semibold text-fg group-hover:text-accent-bright">
                  {t.title}
                </div>
                <p className="mt-0.5 text-[11px] leading-snug text-muted">{t.desc}</p>
              </div>
            </Link>
          ))}
        </div>

        <p className="mt-4 border-t border-line pt-3.5 text-[10.5px] leading-relaxed text-muted">
          Tools are standalone — use them to explore or answer a quick question.
          When you&apos;re working a real case, start from the{" "}
          <Link href="/case" className="text-accent-bright hover:underline">
            Case File
          </Link>{" "}
          so everything attaches to the case.
        </p>
      </section>
    </div>
  );
}
