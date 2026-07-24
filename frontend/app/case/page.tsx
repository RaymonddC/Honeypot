"use client";

/**
 * Case File (case-centric flow) — the spine screen and the working hub. Shows
 * the active case, a stage tracker walking the real investigation lifecycle
 * (intake → freeze → trace → takedown → report → recovery → closed), and a
 * rollup of everything attached to the case — bank accounts + crypto transfers
 * — which you can ADD right here (they attach to this case and feed TRACE /
 * TAKEDOWN), with links into the engines that consume them.
 */

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useCases } from "@/components/cases/case-provider";
import { generateActions } from "@/lib/actions/api";
import { addBankAccount, addCryptoTransfer } from "@/lib/casedata/api";
import { CASE_STAGES, fetchRollup, type CaseRollup, type CaseStage } from "@/lib/cases/api";

const CATEGORIES = ["unknown", "scam", "mule", "victim", "suspect", "exchange"];

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

// Per-stage action: the task, the module to do it in, and the checklist that
// ticks off from the case's actual rollup data.
type Check = { label: string; done: boolean };
type StageAction = {
  task: string;
  why: string;
  href: string;
  cta: string;
  checks: Check[];
};

function stageAction(stage: CaseStage, r: CaseRollup | null): StageAction {
  const sessions = r?.counts.sessions ?? 0;
  const documents = r?.counts.documents ?? 0;
  const banks = r?.counts.bank_accounts ?? 0;
  const txs = r?.counts.crypto_transfers ?? 0;
  const dispatched = (r?.documents ?? []).some((d) => d.status === "dispatched");
  const map: Record<CaseStage, StageAction> = {
    intake: {
      task: "Surface the suspect accounts & wallets",
      why: "Catch the lead — run a honeypot or log what the victim reported.",
      href: "/honeypot",
      cta: "Open Honeypot",
      checks: [
        { label: "Honeypot session engaged", done: sessions > 0 },
        { label: "Suspect account or wallet captured", done: banks + txs > 0 },
      ],
    },
    freeze: {
      task: "Generate & dispatch the freeze request",
      why: "Race to freeze the receiving accounts before the money moves.",
      href: "/actions",
      cta: "Open Action Panel",
      checks: [
        { label: "Freeze document generated", done: documents > 0 },
        { label: "Dispatched to bank / exchange", done: dispatched },
      ],
    },
    trace: {
      task: "Trace the money flow (fiat ↔ crypto)",
      why: "Map where the funds went and find the mule accounts.",
      href: "/bridge",
      cta: "Open Bridge",
      checks: [
        { label: "Bank account tracked", done: banks > 0 },
        { label: "Crypto transfer logged", done: txs > 0 },
      ],
    },
    takedown: {
      task: "Score the wallet network",
      why: "Identify collection wallets and the syndicate behind them.",
      href: "/investigation",
      cta: "Open Investigation",
      checks: [{ label: "Wallet in the graph", done: txs > 0 }],
    },
    report: {
      task: "File the STR / LTKM to PPATK",
      why: "Package court-admissible evidence and report it.",
      href: "/actions",
      cta: "Open Action Panel",
      checks: [
        { label: "Document bundle generated", done: documents > 0 },
        { label: "Dispatched to agencies", done: dispatched },
      ],
    },
    recovery: {
      task: "Track fund recovery",
      why: "Coordinate returning the frozen funds to victims.",
      href: "/response",
      cta: "Open Response",
      checks: [{ label: "Freeze dispatched", done: dispatched }],
    },
    closed: {
      task: "Case closed",
      why: "Outcome recorded — nothing more to do.",
      href: "/response",
      cta: "Open Response",
      checks: [],
    },
  };
  return map[stage];
}

// A stage is "evidenced" when all its checks pass — used for ✓ on the tracker.
function stageDoneMap(r: CaseRollup | null): Record<CaseStage, boolean> {
  const out = {} as Record<CaseStage, boolean>;
  for (const s of CASE_STAGES) {
    const a = stageAction(s, r);
    out[s] = a.checks.length > 0 && a.checks.every((c) => c.done);
  }
  return out;
}

const fieldCls =
  "h-[32px] w-full rounded-lg border border-white/10 bg-card px-2.5 font-mono text-[11.5px] text-fg outline-none placeholder:text-muted focus:border-accent/40";

function StageTracker({
  stage,
  done,
  onPick,
}: {
  stage: CaseStage;
  done: Record<CaseStage, boolean>;
  onPick: (s: CaseStage) => void;
}) {
  const idx = CASE_STAGES.indexOf(stage);
  return (
    <div className="rounded-card border border-line bg-card p-3.5">
      <div className="eyebrow mb-3">Investigation stage — click to set</div>
      <ol className="flex flex-wrap items-center gap-1.5">
        {CASE_STAGES.map((s, i) => {
          const past = i < idx;
          const current = i === idx;
          const evidenced = done[s];
          return (
            <li key={s} className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => onPick(s)}
                title={STAGE_HINT[s]}
                className={`flex items-center gap-1 rounded-lg border px-2.5 py-1.5 text-[11.5px] font-medium transition-colors ${
                  current
                    ? "border-accent/50 bg-accent/15 text-accent-bright"
                    : past
                      ? "border-line bg-elevated text-fg/70"
                      : "border-line bg-card text-muted hover:text-fg"
                }`}
              >
                <span
                  className={`font-mono text-[10px] ${evidenced ? "text-accent" : "opacity-60"}`}
                >
                  {evidenced ? "✓" : i + 1}
                </span>
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
    </div>
  );
}

function NextAction({
  stage,
  rollup,
  onAdvance,
  onFreeze,
  freezing,
}: {
  stage: CaseStage;
  rollup: CaseRollup | null;
  onAdvance: (s: CaseStage) => void;
  onFreeze: () => void;
  freezing: boolean;
}) {
  const a = stageAction(stage, rollup);
  const idx = CASE_STAGES.indexOf(stage);
  const nextStage = CASE_STAGES[idx + 1];
  const allDone = a.checks.length > 0 && a.checks.every((c) => c.done);
  // The time-critical shortcut: on Intake/Freeze, freeze the reported account now.
  const canFreeze = (stage === "intake" || stage === "freeze") && (rollup?.counts.bank_accounts ?? 0) > 0;
  return (
    <div className="rounded-card border border-accent/30 bg-accent/[.05] p-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="eyebrow mb-1 text-accent-bright">
            Now: {STAGE_LABEL[stage]}
          </div>
          <div className="text-[14px] font-semibold text-fg">{a.task}</div>
          <p className="mt-0.5 text-[11.5px] text-muted">{a.why}</p>
        </div>
        <div className="flex flex-none flex-col items-end gap-1.5">
          {canFreeze && (
            <button
              type="button"
              onClick={onFreeze}
              disabled={freezing}
              className="h-8 whitespace-nowrap rounded-lg border border-risk-high/50 bg-risk-high/15 px-3.5 text-xs font-semibold text-risk-high transition-colors hover:bg-risk-high/25 disabled:opacity-60"
            >
              {freezing ? "Freezing…" : "⚡ Freeze now"}
            </button>
          )}
          <Link
            href={a.href}
            className="h-8 whitespace-nowrap rounded-lg bg-accent px-3.5 text-xs font-semibold leading-8 text-[#04140d] transition-colors hover:bg-accent-bright"
          >
            {a.cta} →
          </Link>
        </div>
      </div>

      {a.checks.length > 0 && (
        <ul className="mt-3 space-y-1">
          {a.checks.map((c) => (
            <li key={c.label} className="flex items-center gap-2 text-[11.5px]">
              <span
                className={`flex h-4 w-4 flex-none items-center justify-center rounded-full border text-[9px] ${
                  c.done
                    ? "border-accent bg-accent/20 text-accent-bright"
                    : "border-line text-muted"
                }`}
              >
                {c.done ? "✓" : ""}
              </span>
              <span className={c.done ? "text-fg/80" : "text-muted"}>{c.label}</span>
            </li>
          ))}
        </ul>
      )}

      {allDone && nextStage && (
        <button
          type="button"
          onClick={() => onAdvance(nextStage)}
          className="mt-3 rounded-lg border border-accent/40 bg-accent/10 px-3 py-1.5 text-[11.5px] font-semibold text-accent-bright transition-colors hover:bg-accent/20"
        >
          Done — advance to {STAGE_LABEL[nextStage]} →
        </button>
      )}
    </div>
  );
}

function CardShell({
  title,
  count,
  href,
  hrefLabel,
  onAddToggle,
  adding,
  children,
}: {
  title: string;
  count: number;
  href: string;
  hrefLabel: string;
  onAddToggle: () => void;
  adding: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-card border border-line bg-card">
      <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
        <span className="eyebrow">
          {title} · {count}
        </span>
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={onAddToggle}
            className="text-[11px] font-semibold text-accent-bright hover:underline"
          >
            {adding ? "Cancel" : "+ Add"}
          </button>
          <Link href={href} className="text-[11px] text-muted hover:text-fg">
            {hrefLabel} →
          </Link>
        </div>
      </div>
      <div className="p-2">{children}</div>
    </div>
  );
}

export default function CaseFilePage() {
  const { activeCase, advanceStage, createCase } = useCases();
  const [rollup, setRollup] = useState<CaseRollup | null>(null);
  const [loading, setLoading] = useState(false);
  const [newTitle, setNewTitle] = useState("");

  // add-form state
  const [addingBank, setAddingBank] = useState(false);
  const [addingTx, setAddingTx] = useState(false);
  const [bank, setBank] = useState({ bank_name: "", account_number: "", holder_name: "", category: "mule" });
  const [tx, setTx] = useState({ from_addr: "", to_addr: "", value: "", category: "scam" });
  const [busy, setBusy] = useState(false);
  const [freezing, setFreezing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

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

  const submitBank = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeCase) return;
    setBusy(true);
    setErr(null);
    try {
      await addBankAccount({
        bank_name: bank.bank_name.trim(),
        account_number: bank.account_number.trim(),
        holder_name: bank.holder_name.trim() || undefined,
        category: bank.category,
        case_id: activeCase.id,
      });
      setBank({ bank_name: "", account_number: "", holder_name: "", category: "mule" });
      setAddingBank(false);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Failed to add account");
    } finally {
      setBusy(false);
    }
  };

  const submitTx = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!activeCase) return;
    setBusy(true);
    setErr(null);
    try {
      await addCryptoTransfer({
        from_addr: tx.from_addr.trim(),
        to_addr: tx.to_addr.trim(),
        value: Number(tx.value),
        ts: new Date().toISOString(),
        chain: "tron",
        category: tx.category,
        case_id: activeCase.id,
      });
      setTx({ from_addr: "", to_addr: "", value: "", category: "scam" });
      setAddingTx(false);
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Failed to add transfer");
    } finally {
      setBusy(false);
    }
  };

  // Fast freeze: generate a freeze request for the case's tracked accounts.
  const generateFreeze = async () => {
    if (!activeCase || !rollup) return;
    setFreezing(true);
    setErr(null);
    try {
      const entities = rollup.bank_accounts.map((b) => ({
        type: "bank_account",
        value: String(b.account_number),
        bank_name: (b.bank_name as string) ?? null,
        holder_name: (b.holder_name as string) ?? null,
      }));
      await generateActions({
        caseId: activeCase.id,
        outputs: ["freeze"],
        entities,
      });
      await load();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Freeze generation failed");
    } finally {
      setFreezing(false);
    }
  };

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
        <div className="mt-3 text-[11.5px] text-muted">
          or{" "}
          <Link href="/intake" className="font-semibold text-accent-bright hover:underline">
            start from a victim report →
          </Link>{" "}
          (opens a case, logs the account, and can freeze it in one step)
        </div>
      </div>
    );
  }

  const banks = rollup?.bank_accounts ?? [];
  const txs = rollup?.crypto_transfers ?? [];
  const sessions = rollup?.sessions ?? [];
  const documents = rollup?.documents ?? [];

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

      <div className="mb-3.5 space-y-3.5">
        <StageTracker
          stage={activeCase.stage}
          done={stageDoneMap(rollup)}
          onPick={(s) => void advanceStage(activeCase.id, s)}
        />
        <NextAction
          stage={activeCase.stage}
          rollup={rollup}
          onAdvance={(s) => void advanceStage(activeCase.id, s)}
          onFreeze={() => void generateFreeze()}
          freezing={freezing}
        />
      </div>

      {err && (
        <p className="mb-3 rounded-lg border border-risk-high/30 bg-risk-high/10 px-3 py-2 text-[11.5px] text-risk-high">
          {err}
        </p>
      )}

      {/* rollups (with inline add) */}
      <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
        {/* Bank accounts */}
        <CardShell
          title="Tracked bank accounts"
          count={banks.length}
          href="/bridge"
          hrefLabel="Bridge"
          adding={addingBank}
          onAddToggle={() => setAddingBank((v) => !v)}
        >
          {addingBank && (
            <form onSubmit={submitBank} className="mb-2 space-y-2 rounded-lg bg-elevated p-2.5">
              <input required placeholder="Bank (e.g. BCA)" className={fieldCls}
                value={bank.bank_name} onChange={(e) => setBank({ ...bank, bank_name: e.target.value })} />
              <input required placeholder="Account number" className={fieldCls}
                value={bank.account_number} onChange={(e) => setBank({ ...bank, account_number: e.target.value })} />
              <input placeholder="Holder name (optional)" className={fieldCls}
                value={bank.holder_name} onChange={(e) => setBank({ ...bank, holder_name: e.target.value })} />
              <select className={`${fieldCls} font-sans`} value={bank.category}
                onChange={(e) => setBank({ ...bank, category: e.target.value })}>
                {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <button type="submit" disabled={busy}
                className="h-8 w-full rounded-lg bg-accent text-xs font-semibold text-[#04140d] hover:bg-accent-bright disabled:opacity-50">
                {busy ? "Adding…" : "Add to case"}
              </button>
            </form>
          )}
          {loading ? (
            <p className="px-1.5 py-2 text-[11px] text-muted">Loading…</p>
          ) : banks.length === 0 ? (
            <p className="px-1.5 py-2 text-[11px] text-muted">None yet — click “+ Add”.</p>
          ) : (
            <ul className="space-y-1">
              {banks.map((b) => (
                <li key={String(b.id)} className="rounded-lg bg-elevated px-2.5 py-1.5 font-mono text-[11.5px] text-fg">
                  {String(b.bank_name)} {String(b.account_number)}
                  <span className="ml-2 text-[10.5px] text-muted">{String(b.category)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardShell>

        {/* Crypto transfers */}
        <CardShell
          title="Crypto transfers"
          count={txs.length}
          href="/investigation"
          hrefLabel="Investigation"
          adding={addingTx}
          onAddToggle={() => setAddingTx((v) => !v)}
        >
          {addingTx && (
            <form onSubmit={submitTx} className="mb-2 space-y-2 rounded-lg bg-elevated p-2.5">
              <input required placeholder="From wallet (T…)" className={fieldCls}
                value={tx.from_addr} onChange={(e) => setTx({ ...tx, from_addr: e.target.value })} />
              <input required placeholder="To wallet (T…)" className={fieldCls}
                value={tx.to_addr} onChange={(e) => setTx({ ...tx, to_addr: e.target.value })} />
              <input required type="number" min="0" step="any" placeholder="Amount (USDT)" className={fieldCls}
                value={tx.value} onChange={(e) => setTx({ ...tx, value: e.target.value })} />
              <select className={`${fieldCls} font-sans`} value={tx.category}
                onChange={(e) => setTx({ ...tx, category: e.target.value })}>
                {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <button type="submit" disabled={busy}
                className="h-8 w-full rounded-lg bg-accent text-xs font-semibold text-[#04140d] hover:bg-accent-bright disabled:opacity-50">
                {busy ? "Adding…" : "Add to case"}
              </button>
            </form>
          )}
          {loading ? (
            <p className="px-1.5 py-2 text-[11px] text-muted">Loading…</p>
          ) : txs.length === 0 ? (
            <p className="px-1.5 py-2 text-[11px] text-muted">None yet — click “+ Add”.</p>
          ) : (
            <ul className="space-y-1">
              {txs.map((t) => (
                <li key={String(t.id)} className="flex items-center justify-between gap-2 rounded-lg bg-elevated px-2.5 py-1.5 font-mono text-[11px] text-fg">
                  <span className="min-w-0 truncate">
                    <span className="text-muted">{String(t.from_addr).slice(0, 8)}…</span>
                    {" → "}
                    <span>{String(t.to_addr).slice(0, 8)}…</span>
                    <span className="ml-2 text-[10.5px] text-accent-bright">
                      {Number(t.value).toLocaleString()} USDT
                    </span>
                  </span>
                  <Link
                    href={`/investigation?address=${encodeURIComponent(String(t.to_addr))}`}
                    className="flex-none text-[10.5px] text-accent-bright hover:underline"
                  >
                    investigate →
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </CardShell>
      </div>

      {/* honeypot sessions + action documents attached to the case */}
      <div className="mt-3.5 grid grid-cols-1 gap-3.5 lg:grid-cols-2">
        {/* Honeypot sessions (INFILTRATE) */}
        <div className="rounded-card border border-line bg-card">
          <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
            <span className="eyebrow">Honeypot sessions · {sessions.length}</span>
            <Link href="/honeypot" className="text-[11px] text-accent-bright hover:underline">
              Honeypot →
            </Link>
          </div>
          <div className="p-2">
            {sessions.length === 0 ? (
              <p className="px-1.5 py-2 text-[11px] text-muted">
                None yet — start a call from the Honeypot with this case active.
              </p>
            ) : (
              <ul className="space-y-1">
                {sessions.map((s) => (
                  <li key={s.id} className="rounded-lg bg-elevated px-2.5 py-1.5 text-[11.5px]">
                    <span className="font-mono text-fg">{s.channel_ref || s.channel}</span>
                    <span className="ml-2 text-muted">
                      {s.crime_type ?? "—"} · {s.entity_count} entities · {s.status}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>

        {/* Action documents (UNCOVER) */}
        <div className="rounded-card border border-line bg-card">
          <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
            <span className="eyebrow">Action documents · {documents.length}</span>
            <Link href="/actions" className="text-[11px] text-accent-bright hover:underline">
              Action Panel →
            </Link>
          </div>
          <div className="p-2">
            {documents.length === 0 ? (
              <p className="px-1.5 py-2 text-[11px] text-muted">
                None yet — generate a bundle from the Action Panel with this case active.
              </p>
            ) : (
              <ul className="space-y-1">
                {documents.map((d) => (
                  <li key={d.id} className="rounded-lg bg-elevated px-2.5 py-1.5 text-[11.5px]">
                    <span className="font-mono text-fg">{d.document_count} docs</span>
                    <span className="ml-2 text-muted">
                      {d.crime_type} ·{" "}
                      <span className={d.status === "dispatched" ? "text-accent-bright" : ""}>
                        {d.status}
                      </span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      </div>

      <p className="mt-5 border-t border-line pt-3.5 text-[10.5px] leading-relaxed text-muted">
        Everything you touch while this case is active attaches to{" "}
        <b className="text-white/70">{activeCase.title}</b>: bank accounts feed the
        TRACE Bridge, crypto transfers merge into the TAKEDOWN graph, honeypot
        sessions and action documents roll up here. Switch cases from the top-bar
        selector.
      </p>
    </div>
  );
}
