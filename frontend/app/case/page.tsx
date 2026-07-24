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
import { CASE_STAGES, fetchRollup, type Case, type CaseRollup, type CaseStage } from "@/lib/cases/api";
import { HoneypotPanel } from "@/components/honeypot/panel";
import { BridgePanel } from "@/components/bridge/panel";
import { InvestigationPanel } from "@/components/investigation/panel";
import { ActionsPanel } from "@/components/actions/panel";

const CATEGORIES = ["unknown", "scam", "mule", "victim", "suspect", "exchange"];

// The embedded tools, keyed by id. The case-workflow stepper IS the navigation:
// each stage opens one of these tools below it. "overview" is the case dashboard.
type ToolTab = "overview" | "honeypot" | "bridge" | "investigation" | "actions" | "response";

const TOOL_META: Record<ToolTab, { label: string; glyph: string }> = {
  overview: { label: "Overview", glyph: "▤" },
  honeypot: { label: "Honeypot", glyph: "⬡" },
  bridge: { label: "Bridge", glyph: "⇌" },
  investigation: { label: "Investigation", glyph: "◉" },
  actions: { label: "Action Panel", glyph: "⚑" },
  response: { label: "Command Center", glyph: "▦" }, // agency-wide — outside the case flow
};

// Which tool each stage's work happens in — the stage step opens this tool.
// Recovery reviews THIS case (overview), not the agency-wide dashboard — that
// lives outside the case flow, in the sidebar Command Center.
const STAGE_TAB: Record<CaseStage, ToolTab> = {
  intake: "honeypot",
  freeze: "actions",
  trace: "bridge",
  takedown: "investigation",
  report: "actions",
  recovery: "overview",
  closed: "overview",
};

// What the workspace is currently showing: the case dashboard, or one stage's tool.
type View = "overview" | CaseStage;

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
      why: "Catch the lead — log the submitted victim report, or run a honeypot.",
      href: "/honeypot",
      cta: "Open Intake",
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
      href: "/case",
      cta: "Review recovery",
      checks: [{ label: "Freeze dispatched", done: dispatched }],
    },
    closed: {
      task: "Case closed",
      why: "Outcome recorded — nothing more to do.",
      href: "/case",
      cta: "Review case",
      checks: [],
    },
  };
  return map[stage];
}

const fieldCls =
  "h-[32px] w-full rounded-lg border border-white/10 bg-card px-2.5 font-mono text-[11.5px] text-fg outline-none placeholder:text-muted focus:border-accent/40";

// The one navigation control: a linear case-workflow stepper that IS the tab
// bar. Each step opens its stage's tool below. Two visual dimensions on one row:
//   · progress (the circle): ✓ done · filled dot = where the case is now · number = upcoming
//   · selection (the pill highlight): which step's tool is open right now
// Monotonic — no out-of-order checkmarks. "Overview" sits at the front.
function StageFlow({
  stage,
  view,
  onView,
}: {
  stage: CaseStage; // official case stage (drives progress)
  view: View; // what's open (drives selection)
  onView: (v: View) => void;
}) {
  const idx = CASE_STAGES.indexOf(stage);
  // Closed is a STATUS, not a clickable work step — render the doing-stages as
  // steps and Closed as an end-marker.
  const workflow = CASE_STAGES.filter((s) => s !== "closed");
  const isClosed = stage === "closed";
  return (
    <div className="rounded-card border border-line bg-card p-3.5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="eyebrow">Case workflow</div>
        <div className="text-[10.5px] text-muted">
          {isClosed
            ? "Case closed"
            : `${STAGE_LABEL[stage]} · step ${idx + 1} of ${workflow.length} — click a step to work on it`}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {/* Overview — the case dashboard */}
        <button
          type="button"
          onClick={() => onView("overview")}
          aria-current={view === "overview" ? "page" : undefined}
          className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11.5px] font-medium transition-colors ${
            view === "overview"
              ? "border-accent bg-accent/15 text-accent-bright"
              : "border-line bg-card text-muted hover:text-fg"
          }`}
        >
          <span aria-hidden>▤</span>
          Overview
        </button>
        <span className="mx-1 h-5 w-px bg-line" aria-hidden />
        {workflow.map((s, i) => {
          const past = i < idx;
          const current = i === idx; // where the case officially is
          const selected = view === s; // what's open
          const tool = STAGE_TAB[s];
          const opensLabel =
            s === "intake"
              ? "Victim report or Honeypot"
              : s === "recovery"
                ? "Recovery review"
                : TOOL_META[tool].label;
          return (
            <div key={s} className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => onView(s)}
                title={`${STAGE_LABEL[s]} — ${STAGE_HINT[s]} · opens ${opensLabel}`}
                aria-current={selected ? "page" : current ? "step" : undefined}
                className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11.5px] font-medium transition-colors ${
                  selected
                    ? "border-accent bg-accent/15 text-accent-bright"
                    : current
                      ? "border-accent/40 bg-accent/[.06] text-fg"
                      : past
                        ? "border-line bg-elevated text-fg/70"
                        : "border-line bg-card text-muted hover:text-fg"
                }`}
              >
                <span
                  className={`flex h-4 w-4 items-center justify-center rounded-full font-mono text-[9px] ${
                    past
                      ? "bg-accent/20 text-accent-bright"
                      : current
                        ? "bg-accent text-[#04140d]"
                        : "border border-line text-muted"
                  }`}
                >
                  {past ? "✓" : i + 1}
                </span>
                {STAGE_LABEL[s]}
                {current && (
                  <span className="text-[8.5px] font-bold uppercase tracking-wide text-accent-bright/80">
                    now
                  </span>
                )}
              </button>
              {i < workflow.length - 1 && (
                <span className={i < idx ? "text-accent/50" : "text-muted"} aria-hidden>
                  →
                </span>
              )}
            </div>
          );
        })}

        {/* Closed — a status marker, not a clickable step */}
        <span className="mx-1 h-5 w-px bg-line" aria-hidden />
        <div
          title={isClosed ? "Case closed" : "Set from the Recovery step or the Close case button"}
          className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[11.5px] font-medium ${
            isClosed
              ? "border-accent/50 bg-accent/10 text-accent-bright"
              : "border-dashed border-line text-muted"
          }`}
        >
          <span
            className={`flex h-4 w-4 items-center justify-center rounded-full font-mono text-[9px] ${
              isClosed ? "bg-accent/20 text-accent-bright" : "border border-line text-muted"
            }`}
          >
            {isClosed ? "✓" : "•"}
          </span>
          Closed
        </div>
      </div>
    </div>
  );
}

function NextAction({
  stage,
  rollup,
  onAdvance,
  onFreeze,
  freezing,
  onOpen,
}: {
  stage: CaseStage;
  rollup: CaseRollup | null;
  onAdvance: (s: CaseStage) => void;
  onFreeze: () => void;
  freezing: boolean;
  onOpen: () => void;
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
          <button
            type="button"
            onClick={onOpen}
            className="h-8 whitespace-nowrap rounded-lg bg-accent px-3.5 text-xs font-semibold leading-8 text-[#04140d] transition-colors hover:bg-accent-bright"
          >
            {a.cta} →
          </button>
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
  onOpen,
  openLabel,
  onAddToggle,
  adding,
  children,
}: {
  title: string;
  count: number;
  onOpen: () => void;
  openLabel: string;
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
          <button type="button" onClick={onOpen} className="text-[11px] text-muted hover:text-fg">
            {openLabel} →
          </button>
        </div>
      </div>
      <div className="p-2">{children}</div>
    </div>
  );
}

function StatTile({
  label,
  value,
  accent,
}: {
  label: string;
  value: React.ReactNode;
  accent?: boolean;
}) {
  return (
    <div className="rounded-lg border border-line bg-card px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-wide text-muted">{label}</div>
      <div className={`tnum mt-0.5 text-lg font-bold ${accent ? "text-accent-bright" : "text-fg"}`}>
        {value}
      </div>
    </div>
  );
}

function daysOpen(iso: string): number {
  const d = new Date(iso).getTime();
  if (Number.isNaN(d)) return 0;
  return Math.max(0, Math.floor((Date.now() - d) / 86_400_000));
}

// Intake has two entry paths, mirroring how real cases actually start:
//  · reactive  — a victim report was SUBMITTED (from IASC / a bank / police)
//  · proactive — a HONEYPOT infiltration surfaced the lead
// The analyst picks either; both feed the same case.
function IntakeStage({
  caseId,
  banks,
  onLogged,
  onAdvanceFreeze,
}: {
  caseId: string;
  banks: CaseRollup["bank_accounts"];
  onLogged: () => Promise<void>;
  onAdvanceFreeze: () => void;
}) {
  const [mode, setMode] = useState<"report" | "honeypot">("report");
  const [form, setForm] = useState({ bank_name: "", account_number: "", holder_name: "" });
  const [freezeNow, setFreezeNow] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      await addBankAccount({
        bank_name: form.bank_name.trim(),
        account_number: form.account_number.trim(),
        holder_name: form.holder_name.trim() || undefined,
        category: "scam",
        case_id: caseId,
      });
      if (freezeNow) {
        await generateActions({
          caseId,
          outputs: ["freeze"],
          entities: [
            {
              type: "bank_account",
              value: form.account_number.trim(),
              bank_name: form.bank_name.trim() || null,
              holder_name: form.holder_name.trim() || null,
            },
          ],
        });
      }
      onAdvanceFreeze();
      setForm({ bank_name: "", account_number: "", holder_name: "" });
      await onLogged();
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : "Failed to log the report");
    } finally {
      setBusy(false);
    }
  };

  const ModeCard = ({
    id,
    title,
    sub,
  }: {
    id: "report" | "honeypot";
    title: string;
    sub: string;
  }) => (
    <button
      type="button"
      onClick={() => setMode(id)}
      aria-pressed={mode === id}
      className={`flex-1 rounded-lg border px-3 py-2.5 text-left transition-colors ${
        mode === id
          ? "border-accent bg-accent/10"
          : "border-line bg-elevated hover:border-white/20"
      }`}
    >
      <div className={`text-[12.5px] font-semibold ${mode === id ? "text-accent-bright" : "text-fg"}`}>
        {title}
      </div>
      <div className="mt-0.5 text-[10.5px] leading-snug text-muted">{sub}</div>
    </button>
  );

  return (
    <div>
      {/* how did this case come in? */}
      <div className="mb-3.5 rounded-card border border-line bg-card p-3.5">
        <div className="eyebrow mb-2">How did this case come in?</div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <ModeCard
            id="report"
            title="① Victim report — case submitted"
            sub="Reactive: a report from IASC, a bank, or police. Log the receiving account and freeze fast."
          />
          <ModeCard
            id="honeypot"
            title="② Honeypot — proactive"
            sub="Our AI persona baits the scammer and extracts the receiving accounts & wallets."
          />
        </div>
      </div>

      {mode === "report" ? (
        <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-[1fr_320px]">
          <form onSubmit={submit} className="space-y-3 rounded-card border border-line bg-card p-4">
            <div className="eyebrow">Receiving account reported (to freeze)</div>
            <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
              <input required placeholder="Bank (e.g. BCA)" className={fieldCls}
                value={form.bank_name} onChange={(e) => setForm({ ...form, bank_name: e.target.value })} />
              <input required placeholder="Account number" className={fieldCls}
                value={form.account_number} onChange={(e) => setForm({ ...form, account_number: e.target.value })} />
              <input placeholder="Holder name (optional)" className={fieldCls}
                value={form.holder_name} onChange={(e) => setForm({ ...form, holder_name: e.target.value })} />
            </div>

            <label className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-accent/30 bg-accent/[.06] px-3 py-2.5">
              <input type="checkbox" checked={freezeNow} onChange={(e) => setFreezeNow(e.target.checked)}
                className="h-4 w-4 accent-[#10b981]" />
              <span className="text-[12px] text-fg">
                <b className="text-accent-bright">Generate freeze request now</b> — freeze the
                receiving account first, trace later (the real 30-min window). Advances the case to Freeze.
              </span>
            </label>

            {err && (
              <p className="rounded-lg border border-risk-high/30 bg-risk-high/10 px-3 py-2 text-[11.5px] text-risk-high">
                {err}
              </p>
            )}

            <button type="submit" disabled={busy}
              className="h-9 w-full rounded-lg bg-accent px-4 text-xs font-semibold text-[#04140d] transition-colors hover:bg-accent-bright disabled:opacity-60">
              {busy ? "Working…" : freezeNow ? "Log report & freeze →" : "Log report →"}
            </button>
          </form>

          <div className="rounded-card border border-line bg-card">
            <div className="border-b border-line px-3.5 py-2.5">
              <span className="eyebrow">Reported accounts · {banks.length}</span>
            </div>
            <div className="p-2">
              {banks.length === 0 ? (
                <p className="px-1.5 py-2 text-[11px] text-muted">
                  None logged yet — add the receiving account from the report.
                </p>
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
            </div>
          </div>
        </div>
      ) : (
        <HoneypotPanel embedded />
      )}
    </div>
  );
}

// Recovery — the last "doing" stage: get the frozen funds back to the victim,
// then record the outcome and close. Case-scoped (this case's own freeze docs +
// exposure), NOT the agency-wide Command Center.
function RecoveryStage({
  caseData,
  rollup,
  onUpdate,
}: {
  caseData: Case;
  rollup: CaseRollup | null;
  onUpdate: (
    patch: Partial<Pick<Case, "summary" | "status" | "stage">>,
  ) => Promise<void>;
}) {
  const docs = rollup?.documents ?? [];
  const txs = rollup?.crypto_transfers ?? [];
  const banks = rollup?.bank_accounts ?? [];
  const dispatched = docs.some((d) => d.status === "dispatched");
  const dispatchedCount = docs.filter((d) => d.status === "dispatched").length;
  const cryptoExposure = txs.reduce((s, t) => s + Number(t.value ?? 0), 0);
  const closed = caseData.status === "closed";

  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const checklist = [
    { label: "Freeze request generated", done: docs.length > 0 },
    { label: "Freeze dispatched to bank / exchange", done: dispatched },
    { label: "Outcome recorded & case closed", done: closed },
  ];

  const recordOutcome = async () => {
    setBusy(true);
    setErr(null);
    try {
      const amt = amount.trim()
        ? `Rp ${Number(amount).toLocaleString("id-ID")}`
        : "an unspecified amount";
      const line = `Recovered ${amt}${note.trim() ? ` — ${note.trim()}` : ""}.`;
      // Keep a single outcome line in the brief (replace any prior one).
      const base = (caseData.summary ?? "").split("— Outcome:")[0].trimEnd();
      const summary = `${base}${base ? "\n\n" : ""}— Outcome: ${line}`;
      await onUpdate({ summary, status: "closed", stage: "closed" });
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Failed to record the outcome");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="mb-3.5 rounded-lg border border-accent/20 bg-accent/[.05] px-3 py-2 text-[11px] leading-relaxed text-muted">
        <b className="text-accent-bright">Recovery</b> — get the frozen funds back
        to the victim. Confirm the freeze landed, then record the outcome to close
        the case.
      </div>

      <div className="mb-3.5 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatTile
          label="Crypto exposure"
          value={cryptoExposure > 0 ? `${cryptoExposure.toLocaleString()} USDT` : "—"}
          accent
        />
        <StatTile label="Accounts tracked" value={banks.length} />
        <StatTile label="Freeze requests" value={docs.length} />
        <StatTile label="Dispatched" value={dispatchedCount} />
      </div>

      <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
        {/* checklist */}
        <div className="rounded-card border border-line bg-card p-3.5">
          <div className="eyebrow mb-2.5">Recovery checklist</div>
          <ul className="space-y-2">
            {checklist.map((c) => (
              <li key={c.label} className="flex items-center gap-2 text-[12px]">
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
          {!dispatched && (
            <p className="mt-3 text-[11px] text-muted">
              No freeze dispatched yet — generate &amp; dispatch it from the
              Freeze / Report step first.
            </p>
          )}
        </div>

        {/* outcome */}
        <div className="rounded-card border border-line bg-card p-3.5">
          <div className="eyebrow mb-2.5">Record outcome</div>
          {closed ? (
            <div>
              <p className="rounded-lg border border-accent/30 bg-accent/[.06] px-3 py-2 text-[12px] text-fg">
                ✓ Case closed — the outcome is recorded in the case brief.
              </p>
              <button
                type="button"
                onClick={() => void onUpdate({ status: "open", stage: "recovery" })}
                className="mt-2.5 h-8 rounded-lg border border-white/10 bg-elevated px-3 text-[11.5px] font-semibold text-muted transition-colors hover:text-fg"
              >
                Reopen case
              </button>
            </div>
          ) : (
            <div className="space-y-2.5">
              <div>
                <label className="mb-1 block text-[11px] text-muted">
                  Recovered amount (IDR)
                </label>
                <input
                  type="number"
                  min="0"
                  placeholder="e.g. 18000000"
                  className={fieldCls}
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                />
              </div>
              <div>
                <label className="mb-1 block text-[11px] text-muted">Note (optional)</label>
                <input
                  placeholder="e.g. BCA froze Rp 18M, returned to victim"
                  className={fieldCls}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
              </div>
              {err && <p className="text-[11px] text-risk-high">{err}</p>}
              <button
                type="button"
                disabled={busy}
                onClick={() => void recordOutcome()}
                className="h-9 w-full rounded-lg bg-accent px-4 text-xs font-semibold text-[#04140d] transition-colors hover:bg-accent-bright disabled:opacity-60"
              >
                {busy ? "Saving…" : "Record outcome & close case"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function CaseFilePage() {
  const { activeCase, advanceStage, updateCase, createCase } = useCases();
  const [rollup, setRollup] = useState<CaseRollup | null>(null);
  const [view, setView] = useState<View>("overview");
  // Wallet to auto-trace when the Investigation stage opens (from a transfer row).
  const [investigateAddr, setInvestigateAddr] = useState<string | undefined>(undefined);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState({ title: "", crime_type: "", summary: "" });
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

  // Navigate the workspace. Clears any per-row wallet override unless one is passed.
  const openView = (v: View, addr?: string) => {
    setInvestigateAddr(addr);
    setView(v);
  };
  // Open the tool for a stage, given the tool id (used by the rollup cards).
  const openTool = (t: ToolTab, addr?: string) => {
    const stage = (Object.keys(STAGE_TAB) as CaseStage[]).find((s) => STAGE_TAB[s] === t);
    openView(t === "overview" || !stage ? "overview" : stage, addr);
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
  const caseWallets = Array.from(new Set(txs.map((t) => String(t.to_addr))));
  const firstWallet = caseWallets[0];
  const viewTool = view === "overview" ? "overview" : STAGE_TAB[view];
  const viewToolLabel =
    view === "intake" ? "Victim report or Honeypot" : TOOL_META[viewTool].label;

  return (
    <div className={`mx-auto ${viewTool === "overview" ? "max-w-[1000px]" : "max-w-[1320px]"}`}>
      {/* header */}
      <div className="mb-4">
        <div className="mb-1 flex items-center justify-between gap-3">
          <div className="eyebrow">Case file</div>
          <div className="flex items-center gap-2">
            {!editing && (
              <button
                type="button"
                onClick={() => {
                  setDraft({
                    title: activeCase.title,
                    crime_type: activeCase.crime_type ?? "",
                    summary: activeCase.summary ?? "",
                  });
                  setEditing(true);
                }}
                className="h-7 rounded-lg border border-white/10 bg-elevated px-2.5 text-[11px] font-semibold text-muted transition-colors hover:text-fg"
              >
                ✎ Edit
              </button>
            )}
            <button
              type="button"
              onClick={() =>
                void updateCase(activeCase.id, {
                  status: activeCase.status === "closed" ? "open" : "closed",
                  ...(activeCase.status === "closed" ? {} : { stage: "closed" as CaseStage }),
                })
              }
              className={`h-7 rounded-lg border px-2.5 text-[11px] font-semibold transition-colors ${
                activeCase.status === "closed"
                  ? "border-accent/40 bg-accent/10 text-accent-bright hover:bg-accent/20"
                  : "border-white/10 bg-elevated text-muted hover:text-fg"
              }`}
            >
              {activeCase.status === "closed" ? "Reopen case" : "Close case"}
            </button>
          </div>
        </div>

        {editing ? (
          <div className="rounded-card border border-line bg-card p-3.5">
            <input
              className="mb-2 h-9 w-full rounded-lg border border-white/10 bg-elevated px-3 text-[15px] font-semibold text-fg outline-none focus:border-accent/40"
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              placeholder="Case title"
            />
            <input
              className="mb-2 h-8 w-full rounded-lg border border-white/10 bg-elevated px-3 text-[12px] text-fg outline-none focus:border-accent/40"
              value={draft.crime_type}
              onChange={(e) => setDraft({ ...draft, crime_type: e.target.value })}
              placeholder="Crime type (e.g. investment_scam)"
            />
            <textarea
              className="mb-2.5 min-h-[64px] w-full rounded-lg border border-white/10 bg-elevated px-3 py-2 text-[12px] text-fg outline-none focus:border-accent/40"
              value={draft.summary}
              onChange={(e) => setDraft({ ...draft, summary: e.target.value })}
              placeholder="Case brief / notes — what happened, amounts, context…"
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="h-8 rounded-lg border border-line px-3 text-[11.5px] text-muted hover:text-fg"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={async () => {
                  await updateCase(activeCase.id, {
                    title: draft.title.trim() || activeCase.title,
                    crime_type: draft.crime_type.trim() || undefined,
                    summary: draft.summary.trim() || undefined,
                  });
                  setEditing(false);
                }}
                className="h-8 rounded-lg bg-accent px-3.5 text-[11.5px] font-semibold text-[#04140d] hover:bg-accent-bright"
              >
                Save
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-xl font-bold tracking-tight">{activeCase.title}</h1>
              <span
                className={`rounded-md border px-2 py-0.5 font-mono text-[10.5px] ${
                  activeCase.status === "closed"
                    ? "border-line bg-elevated text-muted"
                    : "border-accent/30 bg-accent/10 text-accent-bright"
                }`}
              >
                {activeCase.status}
              </span>
              {activeCase.crime_type && (
                <span className="rounded-md border border-risk-med/30 bg-risk-med/10 px-2 py-0.5 text-[10.5px] text-risk-med">
                  {activeCase.crime_type}
                </span>
              )}
            </div>
            {activeCase.summary && (
              <p className="mt-1 max-w-[75ch] text-xs leading-relaxed text-muted">
                {activeCase.summary}
              </p>
            )}
          </>
        )}
      </div>

      {/* the ONE navigation: the case-workflow stepper, which opens each tool below */}
      <div className="mb-3.5">
        <StageFlow
          stage={activeCase.stage}
          view={view}
          onView={(v) => openView(v)}
        />
      </div>

      {/* when a stage's tool is open, a slim strip names it + lets you set/return */}
      {viewTool !== "overview" && view !== "overview" && (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-accent/20 bg-accent/[.05] px-3 py-1.5 text-[11px]">
          <span className="text-muted">
            <b className="text-accent-bright">{STAGE_LABEL[view]}</b> stage ·{" "}
            {viewToolLabel} — work here attaches to{" "}
            <b className="text-white/70">{activeCase.title}</b>.
          </span>
          <div className="flex flex-none items-center gap-3">
            {view !== activeCase.stage && (
              <button
                type="button"
                onClick={() => void advanceStage(activeCase.id, view)}
                className="font-semibold text-accent-bright hover:underline"
                title="Mark the case as being at this stage"
              >
                Set case to {STAGE_LABEL[view]}
              </button>
            )}
            <button
              type="button"
              onClick={() => openView("overview")}
              className="text-muted hover:text-fg"
            >
              ← Overview
            </button>
          </div>
        </div>
      )}

      {viewTool === "honeypot" && (
        <IntakeStage
          caseId={activeCase.id}
          banks={banks}
          onLogged={load}
          onAdvanceFreeze={() => void advanceStage(activeCase.id, "freeze")}
        />
      )}
      {viewTool === "bridge" && (
        <BridgePanel embedded onOpenTakedown={() => openView("takedown")} />
      )}
      {viewTool === "investigation" && (
        <InvestigationPanel
          embedded
          key={investigateAddr ?? firstWallet ?? "idle"}
          initialAddress={investigateAddr ?? firstWallet}
          caseWallets={caseWallets}
          onSendToActions={() => openView("report")}
        />
      )}
      {viewTool === "actions" && <ActionsPanel embedded />}

      {view === "recovery" && (
        <RecoveryStage
          caseData={activeCase}
          rollup={rollup}
          onUpdate={(patch) => updateCase(activeCase.id, patch)}
        />
      )}

      {viewTool === "overview" && view !== "recovery" && (
        <>
      {/* overview stat tiles */}
      <div className="mb-3.5 grid grid-cols-3 gap-2 sm:grid-cols-6">
        <StatTile label="Stage" value={activeCase.stage} accent />
        <StatTile label="Accounts" value={banks.length} />
        <StatTile label="Wallets" value={txs.length} />
        <StatTile label="Honeypot" value={sessions.length} />
        <StatTile label="Documents" value={documents.length} />
        <StatTile label="Days open" value={daysOpen(activeCase.created_at)} />
      </div>

      <div className="mb-3.5">
        <NextAction
          stage={activeCase.stage}
          rollup={rollup}
          onAdvance={(s) => void advanceStage(activeCase.id, s)}
          onFreeze={() => void generateFreeze()}
          freezing={freezing}
          onOpen={() => openView(activeCase.stage)}
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
          onOpen={() => openTool("bridge")}
          openLabel="Bridge"
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
          onOpen={() => openTool("investigation")}
          openLabel="Investigation"
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
                  <button
                    type="button"
                    onClick={() => openTool("investigation", String(t.to_addr))}
                    className="flex-none text-[10.5px] text-accent-bright hover:underline"
                  >
                    investigate →
                  </button>
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
            <button
              type="button"
              onClick={() => openTool("honeypot")}
              className="text-[11px] text-accent-bright hover:underline"
            >
              Honeypot →
            </button>
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
            <button
              type="button"
              onClick={() => openTool("actions")}
              className="text-[11px] text-accent-bright hover:underline"
            >
              Action Panel →
            </button>
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

      {/* activity timeline — derived from the case's records */}
      <div className="mt-3.5 rounded-card border border-line bg-card">
        <div className="border-b border-line px-3.5 py-2.5">
          <span className="eyebrow">Activity</span>
        </div>
        <div className="p-3.5">
          <ol className="space-y-2.5">
            {(() => {
              type Ev = { t: number; label: string; sub: string };
              const evs: Ev[] = [
                {
                  t: new Date(activeCase.created_at).getTime(),
                  label: "Case opened",
                  sub: activeCase.crime_type ?? "investigation",
                },
                ...sessions.map((s) => ({
                  t: new Date(s.started_at).getTime(),
                  label: "Honeypot session engaged",
                  sub: `${s.crime_type ?? "—"} · ${s.entity_count} entities`,
                })),
                ...documents.map((d) => ({
                  t: new Date(d.created_at).getTime(),
                  label: `${d.document_count} document(s) generated`,
                  sub: `${d.crime_type} · ${d.status}`,
                })),
              ].sort((a, b) => a.t - b.t);
              return evs.map((e, i) => (
                <li key={i} className="flex gap-2.5">
                  <span
                    className="mt-1 h-1.5 w-1.5 flex-none rounded-full bg-accent"
                    aria-hidden
                  />
                  <div className="min-w-0">
                    <div className="text-[12px] text-fg">{e.label}</div>
                    <div className="text-[10.5px] text-muted">
                      {e.sub}
                      {Number.isFinite(e.t) && (
                        <span className="ml-1.5 text-muted/60">
                          · {new Date(e.t).toLocaleString()}
                        </span>
                      )}
                    </div>
                  </div>
                </li>
              ));
            })()}
          </ol>
        </div>
      </div>

      <p className="mt-5 border-t border-line pt-3.5 text-[10.5px] leading-relaxed text-muted">
        Everything you touch while this case is active attaches to{" "}
        <b className="text-white/70">{activeCase.title}</b>: bank accounts feed the
        TRACE Bridge, crypto transfers merge into the TAKEDOWN graph, honeypot
        sessions and action documents roll up here. Switch cases from the top-bar
        selector.
      </p>
        </>
      )}
    </div>
  );
}
