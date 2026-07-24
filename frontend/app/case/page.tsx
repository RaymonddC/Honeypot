"use client";

/**
 * Case File (case-centric flow) — the spine screen. Shows the active case, a
 * stage tracker walking the real investigation lifecycle (intake → freeze →
 * trace → takedown → report → recovery → closed), and a rollup of everything
 * attached to the case (tracked bank accounts + crypto transfers), with links
 * into the engines that consume them.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useCases } from "@/components/cases/case-provider";
import { CASE_STAGES, fetchRollup, type CaseRollup, type CaseStage } from "@/lib/cases/api";

const STAGE_LABEL: Record<CaseStage, string> = {
  intake: "Intake",
  freeze: "Freeze",
  trace: "Trace",
  takedown: "Takedown",
  report: "Report",
  recovery: "Recovery",
  closed: "Closed",
};

const STAGE_HINT: Record<CaseStage, string> = {
  intake: "Report / proactive intel in",
  freeze: "Race to freeze receiving accounts",
  trace: "Follow the money (fiat ↔ crypto)",
  takedown: "Attribute + score the wallet network",
  report: "Package evidence + file STR/LTKM",
  recovery: "Recover funds",
  closed: "Case done",
};

function StageTracker({
  stage,
  onPick,
}: {
  stage: CaseStage;
  onPick: (s: CaseStage) => void;
}) {
  const idx = CASE_STAGES.indexOf(stage);
  return (
    <div className="rounded-card border border-line bg-card p-3.5">
      <div className="eyebrow mb-3">Investigation stage</div>
      <ol className="flex flex-wrap items-center gap-1.5">
        {CASE_STAGES.map((s, i) => {
          const done = i < idx;
          const current = i === idx;
          return (
            <li key={s} className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => onPick(s)}
                title={STAGE_HINT[s]}
                className={`rounded-lg border px-2.5 py-1.5 text-[11.5px] font-medium transition-colors ${
                  current
                    ? "border-accent/50 bg-accent/15 text-accent-bright"
                    : done
                      ? "border-line bg-elevated text-fg/70"
                      : "border-line bg-card text-muted hover:text-fg"
                }`}
              >
                <span className="mr-1 font-mono text-[10px] opacity-60">{i + 1}</span>
                {STAGE_LABEL[s]}
              </button>
              {i < CASE_STAGES.length - 1 && (
                <span className="text-muted" aria-hidden>
                  →
                </span>
              )}
            </li>
          );
        })}
      </ol>
      <p className="mt-2.5 text-[11.5px] text-muted">{STAGE_HINT[stage]}</p>
    </div>
  );
}

function RollupCard({
  title,
  count,
  href,
  hrefLabel,
  rows,
}: {
  title: string;
  count: number;
  href: string;
  hrefLabel: string;
  rows: React.ReactNode;
}) {
  return (
    <div className="rounded-card border border-line bg-card">
      <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
        <span className="eyebrow">
          {title} · {count}
        </span>
        <Link href={href} className="text-[11px] text-accent-bright hover:underline">
          {hrefLabel} →
        </Link>
      </div>
      <div className="p-2">{rows}</div>
    </div>
  );
}

export default function CaseFilePage() {
  const { activeCase, advanceStage, createCase } = useCases();
  const [rollup, setRollup] = useState<CaseRollup | null>(null);
  const [loading, setLoading] = useState(false);
  const [newTitle, setNewTitle] = useState("");

  const load = useCallback(async () => {
    if (!activeCase) {
      setRollup(null);
      return;
    }
    setLoading(true);
    try {
      setRollup(await fetchRollup(activeCase.id));
    } catch {
      setRollup(null);
    } finally {
      setLoading(false);
    }
  }, [activeCase]);

  useEffect(() => {
    void load();
  }, [load]);

  // No active case → prompt to open one.
  if (!activeCase) {
    return (
      <div className="mx-auto max-w-[560px] pt-10 text-center">
        <h1 className="text-xl font-bold tracking-tight">No case selected</h1>
        <p className="mx-auto mt-1 max-w-[46ch] text-xs text-muted">
          A case is the file every investigation hangs off — accounts, wallets,
          honeypot sessions and documents all attach to it. Open one to begin.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (newTitle.trim()) void createCase({ title: newTitle.trim() });
          }}
          className="mx-auto mt-5 flex max-w-[420px] gap-2"
        >
          <input
            value={newTitle}
            onChange={(e) => setNewTitle(e.target.value)}
            placeholder="Case title (e.g. PT A2Z syndicate)"
            className="h-9 flex-1 rounded-lg border border-white/10 bg-card px-3 text-[13px] text-fg outline-none focus:border-accent/40"
          />
          <button
            type="submit"
            className="h-9 rounded-lg bg-accent px-4 text-xs font-semibold text-[#04140d] hover:bg-accent-bright"
          >
            Open case
          </button>
        </form>
      </div>
    );
  }

  const banks = rollup?.bank_accounts ?? [];
  const txs = rollup?.crypto_transfers ?? [];

  return (
    <div className="mx-auto max-w-[1000px]">
      {/* header */}
      <div className="mb-4">
        <div className="eyebrow mb-1">Case file</div>
        <div className="flex flex-wrap items-center gap-2.5">
          <h1 className="text-xl font-bold tracking-tight">{activeCase.title}</h1>
          <span className="rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[10.5px] text-muted">
            {activeCase.status}
          </span>
          {activeCase.crime_type && (
            <span className="rounded-md border border-risk-med/30 bg-risk-med/10 px-2 py-0.5 text-[10.5px] text-risk-med">
              {activeCase.crime_type}
            </span>
          )}
        </div>
        {activeCase.summary && (
          <p className="mt-1 max-w-[70ch] text-xs text-muted">{activeCase.summary}</p>
        )}
      </div>

      <div className="mb-3.5">
        <StageTracker
          stage={activeCase.stage}
          onPick={(s) => void advanceStage(activeCase.id, s)}
        />
      </div>

      {/* rollups */}
      <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
        <RollupCard
          title="Tracked bank accounts"
          count={banks.length}
          href="/bridge"
          hrefLabel="Open Bridge"
          rows={
            loading ? (
              <p className="px-1.5 py-2 text-[11px] text-muted">Loading…</p>
            ) : banks.length === 0 ? (
              <p className="px-1.5 py-2 text-[11px] text-muted">
                None yet — add from the Bridge watchlist.
              </p>
            ) : (
              <ul className="space-y-1">
                {banks.map((b) => (
                  <li
                    key={String(b.id)}
                    className="rounded-lg bg-elevated px-2.5 py-1.5 font-mono text-[11.5px] text-fg"
                  >
                    {String(b.bank_name)} {String(b.account_number)}
                    <span className="ml-2 text-[10.5px] text-muted">
                      {String(b.category)}
                    </span>
                  </li>
                ))}
              </ul>
            )
          }
        />
        <RollupCard
          title="Crypto transfers"
          count={txs.length}
          href="/investigation"
          hrefLabel="Open Investigation"
          rows={
            loading ? (
              <p className="px-1.5 py-2 text-[11px] text-muted">Loading…</p>
            ) : txs.length === 0 ? (
              <p className="px-1.5 py-2 text-[11px] text-muted">
                None yet — add from Investigation.
              </p>
            ) : (
              <ul className="space-y-1">
                {txs.map((t) => (
                  <li
                    key={String(t.id)}
                    className="rounded-lg bg-elevated px-2.5 py-1.5 font-mono text-[11px] text-fg"
                  >
                    <span className="text-muted">{String(t.from_addr).slice(0, 10)}…</span>
                    {" → "}
                    <span>{String(t.to_addr).slice(0, 10)}…</span>
                    <span className="ml-2 text-[10.5px] text-accent-bright">
                      {Number(t.value).toLocaleString()} USDT
                    </span>
                  </li>
                ))}
              </ul>
            )
          }
        />
      </div>

      <p className="mt-5 border-t border-line pt-3.5 text-[10.5px] leading-relaxed text-muted">
        Everything you add while this case is active attaches to it. Switch or
        open cases from the selector in the top bar.
      </p>
    </div>
  );
}
