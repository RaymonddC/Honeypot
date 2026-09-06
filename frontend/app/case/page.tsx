"use client";

/**
 * Case File (case-centric flow) — the spine screen and the working hub. Shows
 * the active case, a stage tracker walking the real investigation lifecycle
 * (intake → freeze → trace → takedown → report → recovery → closed), and a
 * rollup of everything attached to the case — bank accounts + crypto transfers
 * — which you can ADD right here (they attach to this case and feed TRACE /
 * TAKEDOWN), with links into the engines that consume them.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useCases } from "@/components/cases/case-provider";
import { addBankAccount, addCryptoTransfer } from "@/lib/casedata/api";
import { GOLDEN, ONRAMP_CATEGORY, deriveCaseBridge } from "@/lib/demo/golden-thread";
import {
  CASE_STAGES,
  fetchRollup,
  type Case,
  type CaseRollup,
  type CaseSessionSummary,
  type CaseStage,
} from "@/lib/cases/api";
import { fetchSessionTranscript } from "@/lib/honeypot/api";
import type { HpMessage, HpSession } from "@/lib/honeypot/types";
import { ChatTranscript } from "@/components/honeypot/chat-transcript";
import { HoneypotPanel } from "@/components/honeypot/panel";
import { BridgePanel } from "@/components/bridge/panel";
import { InvestigationPanel } from "@/components/investigation/panel";
import { ActionsPanel } from "@/components/actions/panel";

const CATEGORIES = ["unknown", "scam", "mule", "victim", "suspect", "exchange"];

// Victim-report vocabulary (the single intake form now lives in the Intake stage).
// UI labels come from i18n (see `crimeTypes` in the caseFile namespace); the
// English labels below are used only for the case-brief summary text written
// to the backend (see `submit` in IntakeStage) — that's persisted case DATA,
// not UI chrome, so it stays as authored English regardless of the UI locale.
const CRIME_TYPES = [
  { value: "investment_scam", enLabel: "Investment scam" },
  { value: "judol_deposit", enLabel: "Online gambling" },
  { value: "crypto_phishing", enLabel: "Crypto phishing" },
  { value: "romance_scam", enLabel: "Romance scam" },
  { value: "impersonation", enLabel: "Impersonation" },
  { value: "other", enLabel: "Other" },
];

// UI labels come from i18n (see `sources` in the caseFile namespace); enLabel
// is used only for the persisted case-brief summary text (see CRIME_TYPES note).
const SOURCES = [
  { value: "iasc", enLabel: "IASC" },
  { value: "bank", enLabel: "Bank" },
  { value: "police", enLabel: "Police report" },
  { value: "walk_in", enLabel: "Direct / walk-in" },
];

/** Current local date-time as "YYYY-MM-DDTHH:mm" for <input type=datetime-local>. */
function nowLocal() {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 16);
}

// The embedded tools, keyed by id. The case-workflow stepper IS the navigation:
// each stage opens one of these tools below it. "overview" is the case dashboard.
// (Command Center is agency-wide — it lives in the sidebar, not the case flow.)
type ToolTab = "overview" | "honeypot" | "bridge" | "investigation" | "actions";

// Tool labels come from i18n (see `toolMeta` in the caseFile namespace).

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

// STAGE_LABEL, STAGE_HINT, and VIEW_GUIDE (one line of "what to do at this
// stage" — the single source of stage guidance, replacing the per-panel guide
// strips) all come from i18n now: `t(\`stageLabel.${stage}\`)`,
// `t(\`stageHint.${stage}\`)`, `t(\`viewGuide.${stage}\`)` on the caseFile.page
// namespace, keyed by the same CaseStage values.

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

function stageAction(
  stage: CaseStage,
  r: CaseRollup | null,
  t: ReturnType<typeof useTranslations>,
): StageAction {
  const documents = r?.counts.documents ?? 0;
  const banks = r?.counts.bank_accounts ?? 0;
  const txs = r?.counts.crypto_transfers ?? 0;
  const dispatched = (r?.documents ?? []).some((d) => d.status === "dispatched");
  const sa = (key: CaseStage) => (k: string) => t(`stageAction.${key}.${k}`);
  const map: Record<CaseStage, StageAction> = {
    intake: {
      task: sa("intake")("task"),
      why: sa("intake")("why"),
      href: "/honeypot",
      cta: sa("intake")("cta"),
      checks: [
        // Either path (victim report or honeypot) satisfies intake — the real
        // requirement to move on is a captured suspect account or wallet.
        { label: sa("intake")("checkSuspectCaptured"), done: banks + txs > 0 },
      ],
    },
    freeze: {
      task: sa("freeze")("task"),
      why: sa("freeze")("why"),
      href: "/actions",
      cta: sa("freeze")("cta"),
      checks: [
        { label: sa("freeze")("checkDocGenerated"), done: documents > 0 },
        { label: sa("freeze")("checkDispatched"), done: dispatched },
      ],
    },
    trace: {
      task: sa("trace")("task"),
      why: sa("trace")("why"),
      href: "/bridge",
      cta: sa("trace")("cta"),
      checks: [
        { label: sa("trace")("checkBankTracked"), done: banks > 0 },
        { label: sa("trace")("checkTxLogged"), done: txs > 0 },
      ],
    },
    takedown: {
      task: sa("takedown")("task"),
      why: sa("takedown")("why"),
      href: "/investigation",
      cta: sa("takedown")("cta"),
      checks: [{ label: sa("takedown")("checkWalletInGraph"), done: txs > 0 }],
    },
    report: {
      task: sa("report")("task"),
      why: sa("report")("why"),
      href: "/actions",
      cta: sa("report")("cta"),
      checks: [
        { label: sa("report")("checkBundleGenerated"), done: documents > 0 },
        { label: sa("report")("checkDispatchedAgencies"), done: dispatched },
      ],
    },
    recovery: {
      task: sa("recovery")("task"),
      why: sa("recovery")("why"),
      href: "/case",
      cta: sa("recovery")("cta"),
      checks: [{ label: sa("recovery")("checkFreezeDispatched"), done: dispatched }],
    },
    closed: {
      task: sa("closed")("task"),
      why: sa("closed")("why"),
      href: "/case",
      cta: sa("closed")("cta"),
      checks: [],
    },
  };
  return map[stage];
}

// Clean, flat Framer field: surface fill, hairline, 10px radius, quiet focus.
const fieldCls =
  "h-9 w-full rounded-[10px] border border-[#262626] bg-[#1c1c1c] px-3 text-[13px] text-fg outline-none placeholder:text-[#666] focus:border-[#0099ff]/60";

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
  const t = useTranslations("caseFile.page");
  const idx = CASE_STAGES.indexOf(stage);
  // Closed is a STATUS, not a clickable work step — render the doing-stages as
  // steps and Closed as an end-marker.
  const workflow = CASE_STAGES.filter((s) => s !== "closed");
  const isClosed = stage === "closed";
  return (
    <div className="rounded-card border border-line bg-card p-3.5">
      <div className="mb-3 flex items-center justify-between gap-3">
        <div className="eyebrow">{t("stageFlow.eyebrow")}</div>
        <div className="text-[12px] text-muted">
          {isClosed
            ? t("stageFlow.caseClosed")
            : t("stageFlow.stepOf", {
                stage: t(`stageLabel.${stage}`),
                current: idx + 1,
                total: workflow.length,
              })}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {/* Overview — the case dashboard */}
        <button
          type="button"
          onClick={() => onView("overview")}
          aria-current={view === "overview" ? "page" : undefined}
          className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12px] font-medium transition-colors ${
            view === "overview"
              ? "border-accent bg-accent/15 text-accent-bright"
              : "border-line bg-card text-muted hover:text-fg"
          }`}
        >
          <span aria-hidden>▤</span>
          {t("stageFlow.overview")}
        </button>
        <span className="mx-1 h-5 w-px bg-line" aria-hidden />
        {workflow.map((s, i) => {
          const past = i < idx;
          const current = i === idx; // where the case officially is
          const selected = view === s; // what's open
          const tool = STAGE_TAB[s];
          const opensLabel =
            s === "intake"
              ? t("opensVictimReportOrHoneypot")
              : s === "recovery"
                ? t("opensRecoveryReview")
                : t(`toolMeta.${tool}`);
          return (
            <div key={s} className="flex items-center gap-1.5">
              <button
                type="button"
                onClick={() => onView(s)}
                title={t("stageFlow.stepTitle", {
                  stage: t(`stageLabel.${s}`),
                  hint: t(`stageHint.${s}`),
                  opens: opensLabel,
                })}
                aria-current={selected ? "page" : current ? "step" : undefined}
                className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12px] font-medium transition-colors ${
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
                  className={`flex h-4 w-4 items-center justify-center rounded-full font-mono text-[12px] ${
                    past
                      ? "bg-accent/20 text-accent-bright"
                      : current
                        ? "bg-accent text-[#090909]"
                        : "border border-line text-muted"
                  }`}
                >
                  {past ? "✓" : i + 1}
                </span>
                {t(`stageLabel.${s}`)}
                {current && (
                  <span className="text-[8.5px] font-bold uppercase tracking-wide text-accent-bright/80">
                    {t("stageFlow.now")}
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
          title={isClosed ? t("stageFlow.closedTitle") : t("stageFlow.closedSetFromTitle")}
          className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[12px] font-medium ${
            isClosed
              ? "border-accent/50 bg-accent/10 text-accent-bright"
              : "border-dashed border-line text-muted"
          }`}
        >
          <span
            className={`flex h-4 w-4 items-center justify-center rounded-full font-mono text-[12px] ${
              isClosed ? "bg-accent/20 text-accent-bright" : "border border-line text-muted"
            }`}
          >
            {isClosed ? "✓" : "•"}
          </span>
          {t("stageFlow.closed")}
        </div>
      </div>
    </div>
  );
}

// The one validated Back/Next control — shown both on the Overview "Now" panel
// and on each stage's tool view, so you can always move the case forward from
// wherever you're working. Next is gated by the stage's checklist (with an
// explicit override); Back is free.
function StageNav({
  stage,
  rollup,
  onGo,
}: {
  stage: CaseStage;
  rollup: CaseRollup | null;
  onGo: (s: CaseStage) => void;
}) {
  const t = useTranslations("caseFile.page");
  const a = stageAction(stage, rollup, t);
  const idx = CASE_STAGES.indexOf(stage);
  const prevStage = idx > 0 ? CASE_STAGES[idx - 1] : undefined;
  const nextStage = CASE_STAGES[idx + 1];
  const missing = a.checks.filter((c) => !c.done);
  const allDone = a.checks.length > 0 && missing.length === 0;
  const [showBlock, setShowBlock] = useState(false);
  useEffect(() => setShowBlock(false), [stage]);
  const tryNext = () => {
    if (!nextStage || nextStage === "closed") return;
    if (allDone) onGo(nextStage);
    else setShowBlock(true);
  };

  return (
    <div>
      {showBlock && !allDone && nextStage && (
        <div className="mb-2 rounded-lg border border-risk-med/30 bg-risk-med/10 px-3 py-2.5 text-[12px]">
          <div className="mb-1 font-semibold text-risk-med">
            {t("stageNav.finishBefore", { stage: t(`stageLabel.${nextStage}`) })}
          </div>
          <ul className="space-y-0.5">
            {missing.map((m) => (
              <li key={m.label} className="flex items-center gap-1.5 text-fg/80">
                <span aria-hidden className="text-risk-med">○</span>
                {m.label}
              </li>
            ))}
          </ul>
          <button
            type="button"
            onClick={() => onGo(nextStage)}
            className="mt-2 text-[12px] font-semibold text-muted hover:text-fg hover:underline"
          >
            {t("stageNav.advanceAnyway")}
          </button>
        </div>
      )}
      <div className="flex items-center justify-between gap-3">
        {prevStage ? (
          <button
            type="button"
            onClick={() => onGo(prevStage)}
            className="rounded-lg border border-line px-2.5 py-1.5 text-[12px] font-medium text-muted transition-colors hover:text-fg"
          >
            {t("stageNav.back", { stage: t(`stageLabel.${prevStage}`) })}
          </button>
        ) : (
          <span />
        )}
        {nextStage === "closed" ? (
          <span className="text-[12px] text-muted">
            {t.rich("stageNav.closeViaRecovery", {
              b: (chunks) => <b className="text-fg">{chunks}</b>,
            })}
          </span>
        ) : nextStage ? (
          <button
            type="button"
            onClick={tryNext}
            title={
              allDone
                ? t("stageNav.advanceTo", { stage: t(`stageLabel.${nextStage}`) })
                : t("stageNav.someStepsOpen")
            }
            className={`flex items-center gap-1.5 rounded-lg px-3.5 py-1.5 text-[12px] font-semibold transition-colors ${
              allDone
                ? "bg-accent text-[#090909] hover:bg-accent-bright"
                : "border border-accent/40 bg-accent/10 text-accent-bright hover:bg-accent/20"
            }`}
          >
            {allDone && <span aria-hidden>✓</span>}
            {t("stageNav.next", { stage: t(`stageLabel.${nextStage}`) })}
          </button>
        ) : (
          <span />
        )}
      </div>
    </div>
  );
}

function NextAction({
  stage,
  rollup,
  onGo,
  onFreeze,
  onOpen,
}: {
  stage: CaseStage;
  rollup: CaseRollup | null;
  onGo: (s: CaseStage) => void;
  /** Jump to the freeze desk — the ONE place freeze requests are generated. */
  onFreeze: () => void;
  onOpen: () => void;
}) {
  const t = useTranslations("caseFile.page");
  const a = stageAction(stage, rollup, t);
  // The time-critical shortcut: on Intake, jump straight to the freeze desk
  // once there's an account to block (on Freeze the main CTA already goes there).
  const canFreeze = stage === "intake" && (rollup?.counts.bank_accounts ?? 0) > 0;
  return (
    <div className="rounded-card border border-accent/30 bg-accent/[.05] p-3.5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="eyebrow mb-1 text-accent-bright">
            {t("nextAction.now", { stage: t(`stageLabel.${stage}`) })}
          </div>
          <div className="text-[14px] font-semibold text-fg">{a.task}</div>
          <p className="mt-0.5 text-[12px] text-muted">{a.why}</p>
        </div>
        <div className="flex flex-none flex-col items-end gap-1.5">
          {canFreeze && (
            <button
              type="button"
              onClick={onFreeze}
              className="h-8 whitespace-nowrap rounded-lg border border-risk-high/50 bg-risk-high/15 px-3.5 text-[12px] font-semibold text-risk-high transition-colors hover:bg-risk-high/25"
            >
              {t("nextAction.freezeNow")}
            </button>
          )}
          <button
            type="button"
            onClick={onOpen}
            className="h-8 whitespace-nowrap rounded-full bg-accent px-3.5 text-[12px] font-semibold leading-8 text-[#090909] transition-colors hover:bg-accent-bright"
          >
            {a.cta} →
          </button>
        </div>
      </div>

      {a.checks.length > 0 && (
        <ul className="mt-3 space-y-1">
          {a.checks.map((c) => (
            <li key={c.label} className="flex items-center gap-2 text-[12px]">
              <span
                className={`flex h-4 w-4 flex-none items-center justify-center rounded-full border text-[12px] ${
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

      {/* validated Back / Next */}
      <div className="mt-3 border-t border-accent/15 pt-3">
        <StageNav stage={stage} rollup={rollup} onGo={onGo} />
      </div>
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
  const t = useTranslations("caseFile.page");
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
            className="text-[12px] font-semibold text-accent-bright hover:underline"
          >
            {adding ? t("cardShell.cancel") : t("cardShell.add")}
          </button>
          <button type="button" onClick={onOpen} className="text-[12px] text-muted hover:text-fg">
            {t("cardShell.openArrow", { label: openLabel })}
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
      <div className="text-[12px] uppercase tracking-wide text-muted">{label}</div>
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

/* ── Honeypot sessions (chats + calls) on the case ────────────────────────── */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** Compact "14 Aug, 09:32". Formatted explicitly (not toLocaleString) so the
 *  layout is stable regardless of the viewer's locale. */
function sessionWhen(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return `${d.getDate()} ${MONTHS[d.getMonth()]}, ${hh}:${mm}`;
}

// Prefer the backend's channel_type; fall back to the channel name so an older
// cached rollup (pre-`channel_type`) still shows calls correctly.
const VOICE_CHANNELS = new Set(["pstn", "wa_call", "voice"]);
const isVoiceSession = (s: CaseSessionSummary): boolean =>
  (s.channel_type ?? "").toLowerCase() === "voice" ||
  VOICE_CHANNELS.has((s.channel ?? "").toLowerCase());

type TranscriptState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; session: HpSession; messages: HpMessage[] };

function CaseSessions({
  sessions,
  onOpenHoneypot,
}: {
  sessions: CaseSessionSummary[];
  onOpenHoneypot: () => void;
}) {
  const t = useTranslations("caseFile.page");
  // One row open at a time — keeps this half-width card from growing unbounded.
  const [openId, setOpenId] = useState<string | null>(null);
  // Transcripts are fetched on first expand and cached per session.
  const [transcripts, setTranscripts] = useState<Record<string, TranscriptState>>({});

  const toggle = (id: string) => {
    if (openId === id) {
      setOpenId(null);
      return;
    }
    setOpenId(id);
    if (transcripts[id]?.status === "ready") return; // cached — no refetch
    setTranscripts((prev) => ({ ...prev, [id]: { status: "loading" } }));
    void fetchSessionTranscript(id)
      .then((r) =>
        setTranscripts((prev) => ({
          ...prev,
          [id]: { status: "ready", session: r.session, messages: r.messages },
        })),
      )
      .catch((e: unknown) =>
        setTranscripts((prev) => ({
          ...prev,
          [id]: {
            status: "error",
            message: e instanceof Error ? e.message : t("caseSessions.transcriptErrorFallback"),
          },
        })),
      );
  };

  return (
    <div className="rounded-card border border-line bg-card">
      <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
        <span className="eyebrow">{t("caseSessions.eyebrow", { count: sessions.length })}</span>
        <button
          type="button"
          onClick={onOpenHoneypot}
          className="text-[12px] text-accent-bright hover:underline"
        >
          {t("caseSessions.honeypotLink")}
        </button>
      </div>
      <div className="p-2">
        {sessions.length === 0 ? (
          <p className="px-1.5 py-2 text-[12px] text-muted">
            {t("caseSessions.empty")}
          </p>
        ) : (
          <ul className="space-y-1">
            {sessions.map((s) => {
              const open = openId === s.id;
              const tr = transcripts[s.id];
              const voice = isVoiceSession(s);
              return (
                <li key={s.id} className="rounded-lg bg-elevated">
                  <button
                    type="button"
                    onClick={() => toggle(s.id)}
                    aria-expanded={open}
                    className="flex w-full items-start gap-2 px-2.5 py-1.5 text-left text-[12px] transition-colors hover:bg-fg/[.04]"
                  >
                    <span className="mt-[1px] flex-none text-[12px] text-muted">
                      {open ? "▾" : "▸"}
                    </span>
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-x-1.5">
                        {voice && (
                          <span
                            title={t("caseSessions.voiceCallTitle")}
                            className="rounded border border-accent/[.22] bg-accent/10 px-1 py-px text-[12px] uppercase tracking-[.06em] text-accent-bright"
                          >
                            {t("caseSessions.voiceCallBadge")}
                          </span>
                        )}
                        <span className="font-mono text-fg">{s.channel_ref || s.channel}</span>
                      </span>
                      <span className="mt-px block text-muted">
                        {sessionWhen(s.started_at)} · {s.crime_type ?? "—"} ·{" "}
                        {s.entity_count} entities · {s.status}
                      </span>
                    </span>
                  </button>

                  {open && (
                    <div className="border-t border-line px-2 pb-2 pt-2">
                      {!tr || tr.status === "loading" ? (
                        <p className="px-1.5 py-2 text-[12px] text-muted">{t("caseSessions.loadingTranscript")}</p>
                      ) : tr.status === "error" ? (
                        <p className="px-1.5 py-2 text-[12px] text-risk-high">
                          ✗ {tr.message} {t("caseSessions.transcriptErrorSuffix")}
                        </p>
                      ) : (
                        <ChatTranscript
                          session={tr.session}
                          messages={tr.messages}
                          heightClass="h-[320px]"
                        />
                      )}
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

// Intake has two entry paths, mirroring how real cases actually start:
//  · reactive  — a victim report was SUBMITTED (from IASC / a bank / police)
//  · proactive — a HONEYPOT infiltration surfaced the lead
// The analyst picks either; both feed the same case.
function IntakeStage({
  caseId,
  banks,
  txCount,
  defaultCrimeType,
  onSaveReport,
  onLogged,
  onDone,
  onTraceWallet,
}: {
  caseId: string;
  banks: CaseRollup["bank_accounts"];
  /** Crypto transfers on the case — with `banks`, what "something captured" means. */
  txCount: number;
  /** The case's current crime_type, to seed the selector. */
  defaultCrimeType?: string;
  /** Persist the report brief onto the case (crime_type + summary). */
  onSaveReport: (patch: { crime_type?: string; summary?: string }) => Promise<void>;
  onLogged: () => Promise<void>;
  /** Report logged → advance to Freeze; true = jump straight to the freeze desk. */
  onDone: (continueToFreeze: boolean) => void;
  /** Trace a honeypot-surfaced wallet in the case's Takedown tab. */
  onTraceWallet: (addr: string) => void;
}) {
  const t = useTranslations("caseFile.page");
  const [mode, setMode] = useState<"report" | "honeypot">("report");
  // Same precondition the stage checklist uses (see stageAction.intake): intake
  // is finishable once EITHER path has captured a freezable account or wallet.
  const captured = banks.length + txCount > 0;
  // Accounts already on the case, so the honeypot's "+ Case" controls render
  // "in case" across visits instead of inviting a duplicate promotion.
  const trackedAccounts = new Set(banks.map((b) => String(b.account_number)));
  const [form, setForm] = useState({ bank_name: "", account_number: "", holder_name: "" });
  const [crimeType, setCrimeType] = useState(
    defaultCrimeType && CRIME_TYPES.some((c) => c.value === defaultCrimeType)
      ? defaultCrimeType
      : "investment_scam",
  );
  const [source, setSource] = useState("iasc");
  const [amount, setAmount] = useState("");
  const [incidentAt, setIncidentAt] = useState(nowLocal());
  const [description, setDescription] = useState("");
  const [freezeNow, setFreezeNow] = useState(true);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const dateRef = useRef<HTMLInputElement>(null);
  const openPicker = () => {
    const el = dateRef.current as (HTMLInputElement & { showPicker?: () => void }) | null;
    try {
      el?.showPicker?.();
    } catch {
      /* unsupported / not user-activated — the field still works */
    }
  };

  // Note: this label/summary text is written into the case's persisted brief
  // (`summary`, saved via onSaveReport below) — that's case DATA, not UI
  // chrome, so it stays as authored English regardless of the UI locale.
  const sourceLabel = SOURCES.find((s) => s.value === source)?.enLabel ?? source;
  const crimeLabel = CRIME_TYPES.find((c) => c.value === crimeType)?.enLabel ?? crimeType;
  const amountPretty = amount.trim() ? `Rp ${Number(amount).toLocaleString("id-ID")}` : "";

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      // Write the report brief onto the case, then log the freezable account.
      const when = incidentAt ? new Date(incidentAt).toLocaleString() : "unknown time";
      const summary =
        `Reported via ${sourceLabel}. ${amountPretty || "an unspecified amount"} lost — ${crimeLabel}. Incident: ${when}.` +
        (description.trim() ? `\n\n${description.trim()}` : "");
      await onSaveReport({ crime_type: crimeType, summary });

      await addBankAccount({
        bank_name: form.bank_name.trim(),
        account_number: form.account_number.trim(),
        holder_name: form.holder_name.trim() || undefined,
        category: "scam",
        case_id: caseId,
      });
      setForm({ bank_name: "", account_number: "", holder_name: "" });
      // Refresh FIRST so the freeze desk generates from the just-logged account
      // (generation happens there — one desk, no duplicate bundles).
      await onLogged();
      onDone(freezeNow);
    } catch (e2) {
      setErr(e2 instanceof Error ? e2.message : t("intake.errorFallback"));
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
          : "border-line bg-elevated hover:border-fg/20"
      }`}
    >
      <div className={`text-[12.5px] font-semibold ${mode === id ? "text-accent-bright" : "text-fg"}`}>
        {title}
      </div>
      <div className="mt-0.5 text-[12px] leading-snug text-muted">{sub}</div>
    </button>
  );

  return (
    <div>
      {/* how did this case come in? */}
      <div className="mb-3.5 rounded-card border border-line bg-card p-3.5">
        <div className="eyebrow mb-2">{t("intake.howDidThisComeIn")}</div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <ModeCard
            id="report"
            title={t("intake.modeReportTitle")}
            sub={t("intake.modeReportSub")}
          />
          <ModeCard
            id="honeypot"
            title={t("intake.modeHoneypotTitle")}
            sub={t("intake.modeHoneypotSub")}
          />
        </div>
      </div>

      {mode === "report" ? (
        <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-[1fr_320px]">
          <form onSubmit={submit} className="space-y-4 rounded-card border border-line bg-card p-4">
            {/* the report */}
            <div>
              <div className="eyebrow mb-2">{t("intake.theReport")}</div>
              <label className="mb-1 block text-[12px] font-medium text-muted">{t("intake.scamType")}</label>
              <div className="mb-3 grid grid-cols-2 gap-2 sm:grid-cols-3">
                {CRIME_TYPES.map((c) => {
                  const on = crimeType === c.value;
                  return (
                    <button
                      key={c.value}
                      type="button"
                      onClick={() => setCrimeType(c.value)}
                      aria-pressed={on}
                      className={`flex items-center gap-2 rounded-lg border px-2.5 py-2 text-left text-[12px] transition-colors ${
                        on
                          ? "border-white/25 bg-[#1c1c1c] font-semibold text-white"
                          : "border-[#262626] bg-[#141414] text-[#999] hover:text-white"
                      }`}
                    >
                      {t(`crimeTypes.${c.value}`)}
                    </button>
                  );
                })}
              </div>

              <label className="mb-1 block text-[12px] font-medium text-muted">{t("intake.reportedVia")}</label>
              <div className="mb-3 flex flex-wrap gap-1.5">
                {SOURCES.map((s) => {
                  const on = source === s.value;
                  return (
                    <button
                      key={s.value}
                      type="button"
                      onClick={() => setSource(s.value)}
                      aria-pressed={on}
                      className={`rounded-lg border px-2.5 py-1 text-[12px] transition-colors ${
                        on
                          ? "border-white/25 bg-[#1c1c1c] font-semibold text-white"
                          : "border-[#262626] bg-[#141414] text-[#999] hover:text-white"
                      }`}
                    >
                      {t(`sources.${s.value}`)}
                    </button>
                  );
                })}
              </div>

              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-[12px] font-medium text-muted">{t("intake.amountLost")}</label>
                  <input className={fieldCls} type="number" min="0" inputMode="numeric"
                    placeholder={t("intake.amountPlaceholder")} value={amount}
                    onChange={(e) => setAmount(e.target.value)} />
                  {amountPretty && (
                    <div className="mt-1 font-mono text-[12px] text-accent-bright">{amountPretty}</div>
                  )}
                </div>
                <div>
                  <div className="mb-1 flex items-center justify-between">
                    <label className="text-[12px] font-medium text-muted">{t("intake.whenItHappened")}</label>
                    <button type="button" onClick={() => setIncidentAt(nowLocal())}
                      className="text-[12px] font-semibold text-accent-bright hover:underline">{t("intake.now")}</button>
                  </div>
                  <input ref={dateRef}
                    className={`${fieldCls} cursor-pointer`}
                    type="datetime-local" max={nowLocal()} value={incidentAt}
                    onChange={(e) => setIncidentAt(e.target.value)} onClick={openPicker} />
                </div>
              </div>
            </div>

            {/* receiving account */}
            <div className="border-t border-line pt-3.5">
              <div className="eyebrow mb-2">{t("intake.receivingAccount")}</div>
              <div className="grid grid-cols-1 gap-2.5 sm:grid-cols-3">
                <input required placeholder={t("intake.bankPlaceholder")} className={fieldCls}
                  value={form.bank_name} onChange={(e) => setForm({ ...form, bank_name: e.target.value })} />
                <input required placeholder={t("intake.accountNumberPlaceholder")} className={fieldCls}
                  value={form.account_number} onChange={(e) => setForm({ ...form, account_number: e.target.value })} />
                <input placeholder={t("intake.holderNamePlaceholder")} className={fieldCls}
                  value={form.holder_name} onChange={(e) => setForm({ ...form, holder_name: e.target.value })} />
              </div>
            </div>

            {/* context */}
            <div className="border-t border-line pt-3.5">
              <label className="mb-1 block text-[12px] font-medium text-muted">
                {t("intake.whatHappened")}
              </label>
              <textarea
                className="min-h-[64px] w-full rounded-[10px] border border-[#262626] bg-[#1c1c1c] px-3 py-2 text-[13px] leading-relaxed text-fg outline-none placeholder:text-[#666] focus:border-[#0099ff]/60"
                placeholder={t("intake.whatHappenedPlaceholder")}
                value={description} onChange={(e) => setDescription(e.target.value)} />
            </div>

            <label className="flex cursor-pointer items-center gap-2.5 rounded-lg border border-accent/30 bg-accent/[.06] px-3 py-2.5">
              <input type="checkbox" checked={freezeNow} onChange={(e) => setFreezeNow(e.target.checked)}
                className="h-4 w-4 accent-[#0099ff]" />
              <span className="text-[12px] text-fg">
                <b className="text-accent-bright">{t("intake.continueToFreezeLabel")}</b>{" "}
                {t("intake.continueToFreezeRest")}
              </span>
            </label>

            {err && (
              <p className="rounded-lg border border-risk-high/30 bg-risk-high/10 px-3 py-2 text-[12px] text-risk-high">
                {err}
              </p>
            )}

            <button type="submit" disabled={busy}
              className="h-9 w-full rounded-full bg-accent px-4 text-[12px] font-semibold text-[#090909] transition-colors hover:bg-accent-bright disabled:opacity-60">
              {busy ? t("intake.working") : freezeNow ? t("intake.logAndContinue") : t("intake.logReport")}
            </button>
          </form>

          <div className="rounded-card border border-line bg-card">
            <div className="border-b border-line px-3.5 py-2.5">
              <span className="eyebrow">{t("intake.reportedAccountsEyebrow", { count: banks.length })}</span>
            </div>
            <div className="p-2">
              {banks.length === 0 ? (
                <p className="px-1.5 py-2 text-[12px] text-muted">
                  {t("intake.noneLoggedYet")}
                </p>
              ) : (
                <ul className="space-y-1">
                  {banks.map((b) => (
                    <li key={String(b.id)} className="rounded-lg bg-elevated px-2.5 py-1.5 font-mono text-[12px] text-fg">
                      {String(b.bank_name)} {String(b.account_number)}
                      <span className="ml-2 text-[12px] text-muted">{String(b.category)}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      ) : (
        <>
          <HoneypotPanel
            embedded
            onTraceWallet={onTraceWallet}
            trackedAccounts={trackedAccounts}
            onPromoted={() => void onLogged()}
          />
          {/* The report branch ends in "Log & continue"; without this the
              honeypot branch had no way to finish intake at all — the analyst
              had to know to reach for the stepper. Same destination, same
              precondition (something captured), stated the same way. */}
          <div className="mt-3.5 flex flex-wrap items-center justify-between gap-3 rounded-card border border-accent/25 bg-accent/[.05] px-3.5 py-3">
            <p className="min-w-0 flex-1 text-[12px] leading-relaxed text-muted">
              {captured
                ? t("intake.honeypotDoneReady", { count: banks.length })
                : t("intake.honeypotDoneEmpty")}
            </p>
            <button
              type="button"
              disabled={!captured}
              onClick={() => onDone(true)}
              title={captured ? t("intake.logAndContinue") : t("intake.honeypotDoneEmpty")}
              className="h-8 flex-none rounded-full bg-accent px-4 text-[12px] font-semibold text-[#090909] transition-colors hover:bg-accent-bright disabled:opacity-40"
            >
              {t("intake.logAndContinue")}
            </button>
          </div>
        </>
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
  const t = useTranslations("caseFile.page");
  const docs = rollup?.documents ?? [];
  const txs = rollup?.crypto_transfers ?? [];
  const banks = rollup?.bank_accounts ?? [];
  const dispatched = docs.some((d) => d.status === "dispatched");
  const dispatchedCount = docs.filter((d) => d.status === "dispatched").length;
  const cryptoExposure = txs.reduce((sum, tx) => sum + Number(tx.value ?? 0), 0);
  const closed = caseData.status === "closed";

  const [amount, setAmount] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const checklist = [
    { label: t("recovery.checklist.freezeGenerated"), done: docs.length > 0 },
    { label: t("recovery.checklist.freezeDispatched"), done: dispatched },
    { label: t("recovery.checklist.outcomeRecorded"), done: closed },
  ];

  const recordOutcome = async () => {
    setBusy(true);
    setErr(null);
    try {
      // Note: this outcome line is written into the case's persisted brief
      // (`summary`) — that's case DATA, not UI chrome, so it stays as
      // authored English regardless of the UI locale.
      const amt = amount.trim()
        ? `Rp ${Number(amount).toLocaleString("id-ID")}`
        : "an unspecified amount";
      const line = `Recovered ${amt}${note.trim() ? ` — ${note.trim()}` : ""}.`;
      // Keep a single outcome line in the brief (replace any prior one).
      const base = (caseData.summary ?? "").split("— Outcome:")[0].trimEnd();
      const summary = `${base}${base ? "\n\n" : ""}— Outcome: ${line}`;
      await onUpdate({ summary, status: "closed", stage: "closed" });
    } catch (e) {
      setErr(e instanceof Error ? e.message : t("recovery.errorFallback"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <div className="mb-3.5 grid grid-cols-2 gap-2 sm:grid-cols-4">
        <StatTile
          label={t("recovery.cryptoExposure")}
          value={cryptoExposure > 0 ? `${cryptoExposure.toLocaleString()} USDT` : "—"}
          accent
        />
        <StatTile label={t("recovery.accountsTracked")} value={banks.length} />
        <StatTile label={t("recovery.freezeRequests")} value={docs.length} />
        <StatTile label={t("recovery.dispatched")} value={dispatchedCount} />
      </div>

      <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
        {/* checklist */}
        <div className="rounded-card border border-line bg-card p-3.5">
          <div className="eyebrow mb-2.5">{t("recovery.checklistTitle")}</div>
          <ul className="space-y-2">
            {checklist.map((c) => (
              <li key={c.label} className="flex items-center gap-2 text-[12px]">
                <span
                  className={`flex h-4 w-4 flex-none items-center justify-center rounded-full border text-[12px] ${
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
          {dispatched ? (
            <div className="mt-3 border-t border-line pt-2.5">
              <div className="mb-1.5 text-[12px] uppercase tracking-wide text-muted">
                {t("recovery.dispatchedToAgencies")}
              </div>
              <ul className="space-y-1">
                {docs
                  .filter((d) => d.status === "dispatched")
                  .map((d) => (
                    <li
                      key={d.id}
                      className="flex items-center justify-between rounded-lg bg-elevated px-2.5 py-1.5 text-[12px]"
                    >
                      <span className="font-mono text-fg">{t("recovery.docsCount", { count: d.document_count })}</span>
                      <span className="text-[12px] text-accent-bright">
                        {d.crime_type} · {t("recovery.dispatchedLabel")}
                      </span>
                    </li>
                  ))}
              </ul>
            </div>
          ) : (
            <p className="mt-3 text-[12px] text-muted">
              {t("recovery.noFreezeYet")}
            </p>
          )}
        </div>

        {/* outcome */}
        <div className="rounded-card border border-line bg-card p-3.5">
          <div className="eyebrow mb-2.5">{t("recovery.recordOutcomeTitle")}</div>
          {closed ? (
            <div>
              <p className="rounded-lg border border-accent/30 bg-accent/[.06] px-3 py-2 text-[12px] text-fg">
                {t("recovery.closedNotice")}
              </p>
              <button
                type="button"
                onClick={() => void onUpdate({ status: "open", stage: "recovery" })}
                className="mt-2.5 h-8 rounded-lg border border-line bg-elevated px-3 text-[12px] font-semibold text-muted transition-colors hover:text-fg"
              >
                {t("recovery.reopenCase")}
              </button>
            </div>
          ) : (
            <div className="space-y-2.5">
              <div>
                <label className="mb-1 block text-[12px] text-muted">
                  {t("recovery.recoveredAmountLabel")}
                </label>
                <input
                  type="number"
                  min="0"
                  placeholder={t("recovery.recoveredAmountPlaceholder")}
                  className={fieldCls}
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                />
              </div>
              <div>
                <label className="mb-1 block text-[12px] text-muted">{t("recovery.noteLabel")}</label>
                <input
                  placeholder={t("recovery.notePlaceholder")}
                  className={fieldCls}
                  value={note}
                  onChange={(e) => setNote(e.target.value)}
                />
              </div>
              {err && <p className="text-[12px] text-risk-high">{err}</p>}
              <button
                type="button"
                disabled={busy}
                onClick={() => void recordOutcome()}
                className="h-9 w-full rounded-full bg-accent px-4 text-[12px] font-semibold text-[#090909] transition-colors hover:bg-accent-bright disabled:opacity-60"
              >
                {busy ? t("recovery.saving") : t("recovery.recordOutcomeAndClose")}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function CaseFilePage() {
  const t = useTranslations("caseFile.page");
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
  const [err, setErr] = useState<string | null>(null);
  // A "package for action" handoff that could not attach its wallet to the case.
  // Surfaced instead of opening Uncover on an incomplete case (see below).
  const [attachError, setAttachError] = useState<string | null>(null);

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

  // Reload on every view switch too — work done inside a stage tool (a dispatch,
  // a honeypot session, an added transfer) must show the moment you come back.
  useEffect(() => {
    void load();
  }, [load, view]);

  // A brand-new case (still at Intake, nothing captured) opens straight on the
  // intake form — the single victim-report entry point. Established cases open
  // on the overview. Fires once per case.
  const bootstrapped = useRef<string | null>(null);
  useEffect(() => {
    if (!activeCase || !rollup) return;
    if (bootstrapped.current === activeCase.id) return;
    bootstrapped.current = activeCase.id;
    const captured =
      (rollup.counts?.bank_accounts ?? 0) +
      (rollup.counts?.crypto_transfers ?? 0) +
      (rollup.sessions?.length ?? 0);
    if (activeCase.stage === "intake" && captured === 0) setView("intake");
  }, [activeCase, rollup]);

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
      setErr(e2 instanceof Error ? e2.message : t("overview.errorFallbackBank"));
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
      setErr(e2 instanceof Error ? e2.message : t("overview.errorFallbackTx"));
    } finally {
      setBusy(false);
    }
  };

  // Navigate the workspace. Clears any per-row wallet override unless one is passed.
  const openView = (v: View, addr?: string) => {
    setInvestigateAddr(addr);
    setView(v);
  };
  // Open the tool for a stage, given the tool id (used by the rollup cards).
  const openTool = (tool: ToolTab, addr?: string) => {
    const stage = (Object.keys(STAGE_TAB) as CaseStage[]).find((s) => STAGE_TAB[s] === tool);
    openView(tool === "overview" || !stage ? "overview" : stage, addr);
  };

  // No active case → prompt to open one.
  if (!activeCase) {
    return (
      <div className="mx-auto max-w-[560px] pt-10 text-center">
        <h1 className="text-xl font-bold tracking-tight">{t("noCase.title")}</h1>
        <p className="mx-auto mt-1 max-w-[46ch] text-[12px] text-muted">
          {t("noCase.body")}
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
            placeholder={t("noCase.titlePlaceholder")}
            className="h-9 flex-1 rounded-lg border border-line bg-card px-3 text-[13px] text-fg outline-none focus:border-[#0099ff]/60"
          />
          <button
            type="submit"
            className="h-9 rounded-full bg-accent px-4 text-[12px] font-semibold text-[#090909] hover:bg-accent-bright"
          >
            {t("noCase.openCase")}
          </button>
        </form>
        <div className="mt-3 text-[12px] text-muted">
          {t.rich("noCase.hint", {
            b: (chunks) => <b className="text-fg">{chunks}</b>,
          })}
        </div>
      </div>
    );
  }

  const banks = rollup?.bank_accounts ?? [];
  const txs = rollup?.crypto_transfers ?? [];
  const sessions = rollup?.sessions ?? [];
  const documents = rollup?.documents ?? [];
  // Both endpoints of every case transfer are investigable — so an on-ramp
  // added from Trace (launderer → exchange) exposes the launderer too.
  const caseWallets = Array.from(
    new Set(
      txs
        .flatMap((tx) => [String(tx.from_addr), String(tx.to_addr)])
        .filter((a) => a && a.length >= 4),
    ),
  );
  const firstWallet = caseWallets[0];
  // The case's own fiat→crypto on-ramp (bank account → collection wallet) — the
  // bridge the honeypot lead surfaced; drives the "This case" card in Trace.
  const caseBridge = deriveCaseBridge(banks, caseWallets);
  const viewTool = view === "overview" ? "overview" : STAGE_TAB[view];
  const viewToolLabel =
    view === "intake"
      ? t("opensVictimReportOrHoneypot")
      : view === "recovery"
        ? t("opensRecoveryReview")
        : t(`toolMeta.${viewTool}`);

  return (
    <div className={`mx-auto ${viewTool === "overview" ? "max-w-[1000px]" : "max-w-[1320px]"}`}>
      {/* header */}
      <div className="mb-4">
        <div className="mb-1 flex items-center justify-between gap-3">
          <div className="eyebrow">{t("header.eyebrow")}</div>
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
                className="h-7 rounded-lg border border-line bg-elevated px-2.5 text-[12px] font-semibold text-muted transition-colors hover:text-fg"
              >
                {t("header.edit")}
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
              className={`h-7 rounded-lg border px-2.5 text-[12px] font-semibold transition-colors ${
                activeCase.status === "closed"
                  ? "border-accent/40 bg-accent/10 text-accent-bright hover:bg-accent/20"
                  : "border-[#262626] bg-[#141414] text-[#999] hover:text-white"
              }`}
            >
              {activeCase.status === "closed" ? t("header.reopenCase") : t("header.closeCase")}
            </button>
          </div>
        </div>

        {editing ? (
          <div className="rounded-card border border-line bg-card p-3.5">
            <input
              className="mb-2 h-9 w-full rounded-lg border border-line bg-elevated px-3 text-[15px] font-semibold text-fg outline-none focus:border-[#0099ff]/60"
              value={draft.title}
              onChange={(e) => setDraft({ ...draft, title: e.target.value })}
              placeholder={t("header.titlePlaceholder")}
            />
            <input
              className="mb-2 h-8 w-full rounded-lg border border-line bg-elevated px-3 text-[12px] text-fg outline-none focus:border-[#0099ff]/60"
              value={draft.crime_type}
              onChange={(e) => setDraft({ ...draft, crime_type: e.target.value })}
              placeholder={t("header.crimeTypePlaceholder")}
            />
            <textarea
              className="mb-2.5 min-h-[64px] w-full rounded-lg border border-line bg-elevated px-3 py-2 text-[12px] text-fg outline-none focus:border-[#0099ff]/60"
              value={draft.summary}
              onChange={(e) => setDraft({ ...draft, summary: e.target.value })}
              placeholder={t("header.summaryPlaceholder")}
            />
            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditing(false)}
                className="h-8 rounded-lg border border-line px-3 text-[12px] text-muted hover:text-fg"
              >
                {t("header.cancel")}
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
                className="h-8 rounded-full bg-accent px-3.5 text-[12px] font-semibold text-[#090909] hover:bg-accent-bright"
              >
                {t("header.save")}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2.5">
              <h1 className="text-xl font-bold tracking-tight">{activeCase.title}</h1>
              <span
                className={`rounded-md border px-2 py-0.5 font-mono text-[12px] ${
                  activeCase.status === "closed"
                    ? "border-line bg-elevated text-muted"
                    : "border-accent/30 bg-accent/10 text-accent-bright"
                }`}
              >
                {activeCase.status}
              </span>
              {activeCase.crime_type && (
                <span className="rounded-md border border-risk-med/30 bg-risk-med/10 px-2 py-0.5 text-[12px] text-risk-med">
                  {activeCase.crime_type}
                </span>
              )}
            </div>
            {activeCase.summary && (
              <p className="mt-1 max-w-[75ch] text-[12px] leading-relaxed text-muted">
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

      {/* the ONE stage banner: what to do here + set/return controls */}
      {view !== "overview" && (
        <div className="mb-3 flex flex-wrap items-start justify-between gap-x-4 gap-y-1.5 rounded-lg border border-accent/20 bg-accent/[.05] px-3 py-2">
          <p className="min-w-0 flex-1 text-[12px] leading-relaxed text-muted">
            <b className="text-accent-bright">{t(`stageLabel.${view}`)}</b>{" "}
            <span className="text-muted/70">· {viewToolLabel}</span> —{" "}
            {t(`viewGuide.${view}`)}
          </p>
          <div className="flex flex-none items-center gap-3 pt-0.5 text-[12px]">
            {view !== activeCase.stage && view !== "closed" && (
              <button
                type="button"
                onClick={() => void advanceStage(activeCase.id, view)}
                className="font-semibold text-accent-bright hover:underline"
                title={t("stageBanner.setAsCurrentStage")}
              >
                {t("stageBanner.setAsCurrentStage")}
              </button>
            )}
            <button
              type="button"
              onClick={() => openView("overview")}
              className="text-muted hover:text-fg"
            >
              {t("stageBanner.backToOverview")}
            </button>
          </div>
        </div>
      )}

      {/* Back/Next on the stage you're working — same validated control as Overview */}
      {view !== "overview" && view !== "closed" && view === activeCase.stage && (
        <div className="mb-3 rounded-lg border border-accent/20 bg-accent/[.04] px-3 py-2.5">
          <StageNav
            stage={activeCase.stage}
            rollup={rollup}
            onGo={(s) => {
              void advanceStage(activeCase.id, s);
              openView(s);
            }}
          />
        </div>
      )}

      {attachError && (
        <p className="mb-3 rounded-lg border border-risk-high/30 bg-risk-high/10 px-3 py-2.5 text-[12px] text-risk-high">
          {t("overview.attachErrorPrefix")} {attachError}
        </p>
      )}

      {viewTool === "honeypot" && (
        <IntakeStage
          caseId={activeCase.id}
          banks={banks}
          txCount={txs.length}
          defaultCrimeType={activeCase.crime_type ?? undefined}
          onSaveReport={(patch) => updateCase(activeCase.id, patch)}
          onLogged={load}
          onDone={(continueToFreeze) => {
            void advanceStage(activeCase.id, "freeze");
            if (continueToFreeze) openView("freeze");
          }}
          onTraceWallet={(addr) => openView("takedown", addr)}
        />
      )}
      {viewTool === "bridge" && (
        <BridgePanel
          embedded
          onOpenTakedown={(addr) => openView("takedown", addr)}
          caseTitle={activeCase.title}
          caseBridge={caseBridge}
        />
      )}
      {viewTool === "investigation" && (
        <InvestigationPanel
          embedded
          key={investigateAddr ?? firstWallet ?? "idle"}
          initialAddress={investigateAddr ?? firstWallet}
          caseWallets={caseWallets}
          onSendToActions={async (addr) => {
            // Ensure the clicked wallet is on the case so the freeze desk (Uncover)
            // packages it, then open the Report/Uncover stage.
            if (addr && !caseWallets.includes(addr)) {
              try {
                await addCryptoTransfer({
                  from_addr: GOLDEN.onrampSender,
                  to_addr: addr,
                  value: GOLDEN.amountUsdt,
                  ts: new Date().toISOString(),
                  chain: "tron",
                  category: ONRAMP_CATEGORY,
                  case_id: activeCase.id,
                });
                await load();
              } catch (e) {
                // Do NOT open Uncover regardless: the wallet isn't on the case,
                // so the bundle would be generated WITHOUT the wallet the analyst
                // just packaged — a wrong document, produced silently.
                setAttachError(
                  e instanceof Error ? e.message : t("overview.attachErrorFallback"),
                );
                return;
              }
            }
            setAttachError(null);
            openView("report");
          }}
        />
      )}
      {viewTool === "actions" && (view === "freeze" || view === "report") && (
        <ActionsPanel
          embedded
          key={view}
          outputs={view === "freeze" ? ["freeze"] : undefined}
          cacheSalt={`${banks.length}.${caseWallets.length}`}
          onChanged={load}
        />
      )}

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
        <StatTile label={t("overview.statStage")} value={activeCase.stage} accent />
        <StatTile label={t("overview.statAccounts")} value={banks.length} />
        <StatTile label={t("overview.statWallets")} value={txs.length} />
        <StatTile label={t("overview.statHoneypot")} value={sessions.length} />
        <StatTile label={t("overview.statDocuments")} value={documents.length} />
        <StatTile label={t("overview.statDaysOpen")} value={daysOpen(activeCase.created_at)} />
      </div>

      <div className="mb-3.5">
        <NextAction
          stage={activeCase.stage}
          rollup={rollup}
          onGo={(s) => void advanceStage(activeCase.id, s)}
          onFreeze={() => openView("freeze")}
          onOpen={() => openView(activeCase.stage)}
        />
      </div>

      {err && (
        <p className="mb-3 rounded-lg border border-risk-high/30 bg-risk-high/10 px-3 py-2 text-[12px] text-risk-high">
          {err}
        </p>
      )}

      {/* rollups (with inline add) */}
      <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
        {/* Bank accounts */}
        <CardShell
          title={t("overview.trackedBankAccounts")}
          count={banks.length}
          onOpen={() => openTool("bridge")}
          openLabel={t("overview.openBridge")}
          adding={addingBank}
          onAddToggle={() => setAddingBank((v) => !v)}
        >
          {addingBank && (
            <form onSubmit={submitBank} className="mb-2 space-y-2 rounded-lg bg-elevated p-2.5">
              <input required placeholder={t("intake.bankPlaceholder")} className={fieldCls}
                value={bank.bank_name} onChange={(e) => setBank({ ...bank, bank_name: e.target.value })} />
              <input required placeholder={t("intake.accountNumberPlaceholder")} className={fieldCls}
                value={bank.account_number} onChange={(e) => setBank({ ...bank, account_number: e.target.value })} />
              <input placeholder={t("intake.holderNamePlaceholder")} className={fieldCls}
                value={bank.holder_name} onChange={(e) => setBank({ ...bank, holder_name: e.target.value })} />
              <select className={`${fieldCls} font-sans`} value={bank.category}
                onChange={(e) => setBank({ ...bank, category: e.target.value })}>
                {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <button type="submit" disabled={busy}
                className="h-8 w-full rounded-full bg-accent text-[12px] font-semibold text-[#090909] hover:bg-accent-bright disabled:opacity-50">
                {busy ? t("overview.adding") : t("overview.addToCase")}
              </button>
            </form>
          )}
          {loading ? (
            <p className="px-1.5 py-2 text-[12px] text-muted">{t("overview.loading")}</p>
          ) : banks.length === 0 ? (
            <p className="px-1.5 py-2 text-[12px] text-muted">{t("overview.noneYetAdd")}</p>
          ) : (
            <ul className="space-y-1">
              {banks.map((b) => (
                <li key={String(b.id)} className="rounded-lg bg-elevated px-2.5 py-1.5 font-mono text-[12px] text-fg">
                  {String(b.bank_name)} {String(b.account_number)}
                  <span className="ml-2 text-[12px] text-muted">{String(b.category)}</span>
                </li>
              ))}
            </ul>
          )}
        </CardShell>

        {/* Crypto transfers */}
        <CardShell
          title={t("overview.cryptoTransfers")}
          count={txs.length}
          onOpen={() => openTool("investigation")}
          openLabel={t("overview.openInvestigation")}
          adding={addingTx}
          onAddToggle={() => setAddingTx((v) => !v)}
        >
          {addingTx && (
            <form onSubmit={submitTx} className="mb-2 space-y-2 rounded-lg bg-elevated p-2.5">
              <input required placeholder={t("overview.fromWalletPlaceholder")} className={fieldCls}
                value={tx.from_addr} onChange={(e) => setTx({ ...tx, from_addr: e.target.value })} />
              <input required placeholder={t("overview.toWalletPlaceholder")} className={fieldCls}
                value={tx.to_addr} onChange={(e) => setTx({ ...tx, to_addr: e.target.value })} />
              <input required type="number" min="0" step="any" placeholder={t("overview.amountUsdtPlaceholder")} className={fieldCls}
                value={tx.value} onChange={(e) => setTx({ ...tx, value: e.target.value })} />
              <select className={`${fieldCls} font-sans`} value={tx.category}
                onChange={(e) => setTx({ ...tx, category: e.target.value })}>
                {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
              </select>
              <button type="submit" disabled={busy}
                className="h-8 w-full rounded-full bg-accent text-[12px] font-semibold text-[#090909] hover:bg-accent-bright disabled:opacity-50">
                {busy ? t("overview.adding") : t("overview.addToCase")}
              </button>
            </form>
          )}
          {loading ? (
            <p className="px-1.5 py-2 text-[12px] text-muted">{t("overview.loading")}</p>
          ) : txs.length === 0 ? (
            <p className="px-1.5 py-2 text-[12px] text-muted">{t("overview.noneYetAdd")}</p>
          ) : (
            <ul className="space-y-1">
              {txs.map((tx2) => (
                <li key={String(tx2.id)} className="flex items-center justify-between gap-2 rounded-lg bg-elevated px-2.5 py-1.5 font-mono text-[12px] text-fg">
                  <span className="min-w-0 truncate">
                    <span className="text-muted">{String(tx2.from_addr).slice(0, 8)}…</span>
                    {" → "}
                    <span>{String(tx2.to_addr).slice(0, 8)}…</span>
                    <span className="ml-2 text-[12px] text-accent-bright">
                      {Number(tx2.value).toLocaleString()} USDT
                    </span>
                  </span>
                  <button
                    type="button"
                    onClick={() => openTool("investigation", String(tx2.to_addr))}
                    className="flex-none text-[12px] text-accent-bright hover:underline"
                  >
                    {t("overview.investigateArrow")}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </CardShell>
      </div>

      {/* honeypot sessions + action documents attached to the case */}
      <div className="mt-3.5 grid grid-cols-1 gap-3.5 lg:grid-cols-2">
        {/* Honeypot sessions (INFILTRATE) — chats + calls, expand for transcript */}
        <CaseSessions sessions={sessions} onOpenHoneypot={() => openTool("honeypot")} />

        {/* Action documents (UNCOVER) */}
        <div className="rounded-card border border-line bg-card">
          <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
            <span className="eyebrow">{t("overview.actionDocumentsEyebrow", { count: documents.length })}</span>
            <button
              type="button"
              onClick={() => openTool("actions")}
              className="text-[12px] text-accent-bright hover:underline"
            >
              {t("overview.actionPanelLink")}
            </button>
          </div>
          <div className="p-2">
            {documents.length === 0 ? (
              <p className="px-1.5 py-2 text-[12px] text-muted">
                {t("overview.noDocumentsYet")}
              </p>
            ) : (
              <ul className="space-y-1">
                {documents.map((d) => (
                  <li key={d.id} className="rounded-lg bg-elevated px-2.5 py-1.5 text-[12px]">
                    <span className="font-mono text-fg">{t("recovery.docsCount", { count: d.document_count })}</span>
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
          <span className="eyebrow">{t("overview.activityEyebrow")}</span>
        </div>
        <div className="p-3.5">
          <ol className="space-y-2.5">
            {(() => {
              type Ev = { t: number; label: string; sub: string };
              const evs: Ev[] = [
                {
                  t: new Date(activeCase.created_at).getTime(),
                  label: t("overview.activityCaseOpened"),
                  sub: activeCase.crime_type ?? t("overview.activityCaseOpenedSub"),
                },
                ...sessions.map((s) => ({
                  t: new Date(s.started_at).getTime(),
                  label: t("overview.activityHoneypotEngaged"),
                  sub: `${s.crime_type ?? "—"} · ${s.entity_count} entities`,
                })),
                ...documents.map((d) => ({
                  t: new Date(d.created_at).getTime(),
                  label: t("overview.activityDocumentsGenerated", { count: d.document_count }),
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
                    <div className="text-[12px] text-muted">
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

      <p className="mt-5 border-t border-line pt-3.5 text-[12px] leading-relaxed text-muted">
        {t.rich("overview.footerNote", {
          title: activeCase.title,
          b: (chunks) => <b className="text-fg">{chunks}</b>,
        })}
      </p>
        </>
      )}
    </div>
  );
}
