"use client";

/**
 * Honeypot Ops — the outbound-calling operations surface
 * (docs/Voice-Honeypot-Outbound.md §2/§7).
 *
 * Deliberately NOT the Control Panel: that page holds per-browser analyst
 * preferences (localStorage). Numbers and campaigns are shared, agency-scoped,
 * server-side operational data with their own lifecycle.
 *
 * Starting a campaign marks it running and — only when the dialer is enabled
 * server-side (ITTU_DIAL_ENQUEUE_ON_START) — hands its queued targets to the
 * worker, which SIMULATES the call in POC. Real telephony is still to come.
 * "Call again" (requeue) sends finished targets back to the queue.
 *
 * NOTE for copy: GET /api/config now reports `dialing.enabled` (both
 * ITTU_DIAL_ENQUEUE_ON_START and Postgres persistence), so the page CAN say
 * when Start won't place calls — see `useDialingEnabled`. It still never
 * claims dialing is "on": even enabled, this build only simulates. Until the
 * flag loads (and against an older API) it falls back to the unconditionally
 * true line rather than guessing.
 *
 * Triage is the third tab: connected calls auto-linking couldn't place. Linking
 * is exact-match only by design (§9), so this queue is the normal path rather
 * than an error state.
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { listCases, type Case } from "@/lib/cases/api";
import { fetchBackendConfig } from "@/lib/settings";
import {
  attachTriageSession,
  createCampaign,
  listAttempts,
  listCampaigns,
  listNumbers,
  listTargets,
  listTriage,
  normalizeE164,
  pauseCampaign,
  promoteTriageSession,
  registerNumber,
  requeueTargets,
  splitPasted,
  startCampaign,
  updateNumber,
  uploadTargets,
  type DialAttempt,
  type DialCampaign,
  type DialTarget,
  type HoneypotNumber,
  type RejectReason,
  type RequeueResult,
  type RequeueableStatus,
  type TriageSession,
  type UploadTargetsResult,
} from "@/lib/honeypot-ops/api";

type Tab = "numbers" | "campaigns" | "triage";
type OpsT = ReturnType<typeof useTranslations>;

const INPUT_CLS =
  "h-8 rounded-lg border border-line bg-elevated px-2.5 text-[11.5px] text-fg outline-none transition-colors placeholder:text-muted focus:border-accent/40";
const BTN_CLS =
  "h-8 shrink-0 rounded-lg border border-line bg-elevated px-3 text-[11px] font-semibold text-fg transition-colors hover:border-accent/40 disabled:opacity-50";

const NUMBER_STATUS_STYLE: Record<string, string> = {
  active: "text-accent-bright",
  retired: "text-muted",
  rate_limited: "text-risk-med",
};

const CAMPAIGN_STATUS_STYLE: Record<string, string> = {
  draft: "text-muted",
  running: "text-accent-bright",
  paused: "text-risk-med",
  completed: "text-fg",
};

function fmtDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  const day = d.getDate();
  const month = d.toLocaleString("en-US", { month: "short" });
  const hh = `${d.getHours()}`.padStart(2, "0");
  const mm = `${d.getMinutes()}`.padStart(2, "0");
  return `${day} ${month}, ${hh}:${mm}`;
}

function Card({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="mb-3.5 rounded-card border border-line bg-card">
      <div className="flex items-center justify-between gap-2 border-b border-line px-3.5 py-3">
        <span className="eyebrow">{title}</span>
        {action}
      </div>
      <div className="p-3.5">{children}</div>
    </div>
  );
}

function ErrorLine({ msg }: { msg: string | null }) {
  if (!msg) return null;
  return <p className="mt-2 text-[10.5px] text-risk-high">✗ {msg}</p>;
}

/* ── Numbers tab ─────────────────────────────────────────────────────────── */

function NumbersTab() {
  const t = useTranslations("honeypotOps");
  const [rows, setRows] = useState<HoneypotNumber[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [phone, setPhone] = useState("");
  const [sid, setSid] = useState("");
  const [label, setLabel] = useState("");
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await listNumbers());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("numbersTab.errors.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const normalized = normalizeE164(phone);
  const phoneBad = phone.trim() !== "" && normalized === null;

  const add = async () => {
    if (!normalized) return;
    setSaving(true);
    try {
      await registerNumber({
        phone_number: normalized,
        twilio_sid: sid.trim() || undefined,
        label: label.trim() || undefined,
      });
      setPhone("");
      setSid("");
      setLabel("");
      setError(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("numbersTab.errors.registerFailed"));
    } finally {
      setSaving(false);
    }
  };

  const toggleRetire = async (n: HoneypotNumber) => {
    try {
      await updateNumber(n.id, {
        status: n.status === "retired" ? "active" : "retired",
      });
      setError(null);
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("numbersTab.errors.updateFailed"));
    }
  };

  return (
    <Card
      title={t("numbersTab.cardTitle")}
      action={
        <a
          href="https://console.twilio.com/us1/develop/phone-numbers/manage/incoming"
          target="_blank"
          rel="noopener noreferrer"
          className="text-[10px] text-accent-bright hover:underline"
        >
          {t("numbersTab.twilioConsole")}
        </a>
      }
    >
      <p className="mb-3 text-[10.5px] text-muted">
        {t("numbersTab.intro")}
      </p>

      <div className="mb-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)_auto]">
        <input
          type="text"
          value={phone}
          placeholder={t("numbersTab.phonePlaceholder")}
          spellCheck={false}
          onChange={(e) => setPhone(e.target.value)}
          className={`${INPUT_CLS} font-mono ${phoneBad ? "border-risk-high" : ""}`}
        />
        <input
          type="text"
          value={sid}
          placeholder={t("numbersTab.sidPlaceholder")}
          spellCheck={false}
          onChange={(e) => setSid(e.target.value)}
          className={`${INPUT_CLS} font-mono`}
        />
        <input
          type="text"
          value={label}
          placeholder={t("numbersTab.labelPlaceholder")}
          onChange={(e) => setLabel(e.target.value)}
          className={INPUT_CLS}
        />
        <button
          type="button"
          onClick={() => void add()}
          disabled={!normalized || saving}
          className={BTN_CLS}
        >
          {saving ? t("numbersTab.registerBusy") : t("numbersTab.register")}
        </button>
      </div>
      {phoneBad && (
        <p className="mb-2 text-[10px] text-risk-high">
          {t("numbersTab.phoneInvalidHint")}
        </p>
      )}

      {loading ? (
        <p className="text-[11px] text-muted">{t("numbersTab.loading")}</p>
      ) : rows.length === 0 ? (
        <p className="text-[11px] text-muted">
          {t("numbersTab.empty")}
        </p>
      ) : (
        <ul className="space-y-1">
          {rows.map((n) => (
            <li
              key={n.id}
              className="flex items-center justify-between gap-2 rounded-lg bg-elevated px-2.5 py-1.5 text-[11.5px]"
            >
              <div className="min-w-0">
                <span className="font-mono text-fg">{n.phone_number}</span>
                <span className="ml-2 text-muted">
                  {n.label || t("numbersTab.noLabel")} ·{" "}
                  <span className={NUMBER_STATUS_STYLE[n.status] ?? "text-muted"}>
                    {t(`numbersTab.numberStatus.${n.status}`)}
                  </span>
                </span>
              </div>
              <button
                type="button"
                onClick={() => void toggleRetire(n)}
                title={
                  n.status === "retired"
                    ? t("numbersTab.reactivateTitle")
                    : t("numbersTab.retireTitle")
                }
                className="shrink-0 text-[10.5px] text-accent-bright hover:underline"
              >
                {n.status === "retired" ? t("numbersTab.reactivate") : t("numbersTab.retire")}
              </button>
            </li>
          ))}
        </ul>
      )}
      <ErrorLine msg={error} />
    </Card>
  );
}

/* ── Campaign detail (targets + upload) ──────────────────────────────────── */

/**
 * Why each pasted row was rejected. `already_in_campaign` deliberately points at
 * the "Call again" action: the number IS in the campaign, and re-dialing it is a
 * state change on that row, not a second row — two rows for one number would
 * make the per-status counts meaningless.
 */
function rejectCopy(reason: RejectReason, t: OpsT): string {
  return t(`campaignDetail.rejectReasons.${reason}`);
}

/**
 * Whether Start will actually hand numbers to the dialer, per GET /api/config.
 *
 * The page cannot infer this: both preconditions (ITTU_DIAL_ENQUEUE_ON_START and
 * Postgres persistence) live server-side and BOTH fail silently — the flag is
 * read at boot, and enqueue errors are logged rather than raised so a broker
 * hiccup can't 500 a campaign start. `null` while loading or if the API is old.
 */
function useDialingEnabled(): boolean | null {
  const [enabled, setEnabled] = useState<boolean | null>(null);
  useEffect(() => {
    let alive = true;
    void fetchBackendConfig().then((c) => {
      if (alive) setEnabled(c.dialingEnabled);
    });
    return () => {
      alive = false;
    };
  }, []);
  return enabled;
}

function CampaignDetail({
  campaign,
  onChanged,
}: {
  campaign: DialCampaign;
  onChanged: () => void;
}) {
  const t = useTranslations("honeypotOps");
  const [targets, setTargets] = useState<DialTarget[] | null>(null);
  const [paste, setPaste] = useState("");
  const [result, setResult] = useState<UploadTargetsResult | null>(null);
  const [requeued, setRequeued] = useState<RequeueResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTargets = useCallback(async () => {
    try {
      setTargets(await listTargets(campaign.id));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("campaignDetail.errors.loadTargetsFailed"));
    }
  }, [campaign.id, t]);

  useEffect(() => {
    void loadTargets();
  }, [loadTargets]);

  // Live preview of what the paste box will actually submit — the server
  // re-validates, this is purely so a bad list is obvious before upload.
  const parsed = splitPasted(paste);
  const validCount = parsed.filter((p) => normalizeE164(p) !== null).length;

  const upload = async () => {
    if (!paste.trim()) return;
    setBusy(true);
    try {
      const res = await uploadTargets(campaign.id, { text: paste });
      setResult(res);
      setPaste("");
      setError(null);
      await loadTargets();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("campaignDetail.errors.uploadFailed"));
    } finally {
      setBusy(false);
    }
  };

  const lifecycle = async (action: "start" | "pause") => {
    setBusy(true);
    try {
      await (action === "start" ? startCampaign : pauseCampaign)(campaign.id);
      setError(null);
      onChanged();
    } catch (e) {
      setError(
        e instanceof Error ? e.message : t("campaignDetail.errors.lifecycleFailed", { action }),
      );
    } finally {
      setBusy(false);
    }
  };

  // Requeue = call these numbers again. The campaign never gets a duplicate row
  // for a number, so re-dialing is a state change on the existing target and the
  // attempt history is kept.
  const requeue = async (input: {
    target_ids?: string[];
    statuses?: RequeueableStatus[];
  }) => {
    setBusy(true);
    try {
      const res = await requeueTargets(campaign.id, input);
      setRequeued(res);
      setError(null);
      await loadTargets();
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("campaignDetail.errors.requeueFailed"));
    } finally {
      setBusy(false);
    }
  };

  const finished = (targets ?? []).filter((tg) =>
    ["no_answer", "failed"].includes(tg.status),
  );
  const dialingEnabled = useDialingEnabled();

  return (
    <div className="mt-2 border-t border-line pt-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void lifecycle("start")}
          disabled={busy || campaign.status === "running" || campaign.status === "completed"}
          title={t("campaignDetail.startTitle")}
          className={BTN_CLS}
        >
          {campaign.status === "paused" ? t("campaignDetail.resume") : t("campaignDetail.start")}
        </button>
        <button
          type="button"
          onClick={() => void lifecycle("pause")}
          disabled={busy || campaign.status !== "running"}
          title={t("campaignDetail.pauseTitle")}
          className={BTN_CLS}
        >
          {t("campaignDetail.pause")}
        </button>
        <button
          type="button"
          onClick={() => void requeue({ statuses: ["no_answer", "failed"] })}
          disabled={busy || finished.length === 0}
          title={t("campaignDetail.callAgainTitle")}
          className={BTN_CLS}
        >
          {t("campaignDetail.callAgain")} {finished.length > 0 ? `(${finished.length})` : ""}
        </button>
        <span className="text-[10px] text-muted">
          {dialingEnabled === false
            ? t("campaignDetail.dialingOffNote")
            : t("campaignDetail.simulatedNote")}
        </span>
      </div>

      {requeued && (
        <p className="mb-2 text-[10.5px]">
          <span className="text-accent-bright">
            {t("campaignDetail.requeuedSummary", { count: requeued.requeued })}
          </span>
          {requeued.skipped > 0 && (
            <span className="text-muted">
              {" "}
              {t("campaignDetail.requeuedSkipped", { count: requeued.skipped })}
            </span>
          )}
        </p>
      )}

      <label className="grid gap-1">
        <span className="text-[11px] font-medium text-fg">
          {t("campaignDetail.addNumbersLabel")}
        </span>
        <textarea
          value={paste}
          onChange={(e) => setPaste(e.target.value)}
          rows={4}
          spellCheck={false}
          placeholder={t("campaignDetail.pastePlaceholder")}
          className="rounded-lg border border-line bg-elevated px-2.5 py-2 font-mono text-[11px] text-fg outline-none transition-colors placeholder:text-muted focus:border-accent/40"
        />
      </label>
      <div className="mt-1.5 flex items-center gap-2.5">
        <button
          type="button"
          onClick={() => void upload()}
          disabled={busy || validCount === 0}
          className={BTN_CLS}
        >
          {busy ? t("campaignDetail.uploadBusy") : t("campaignDetail.upload")}
        </button>
        {parsed.length > 0 && (
          <span className="text-[10px] text-muted">
            {t("campaignDetail.validCount", {
              valid: validCount,
              total: parsed.length,
              plural: parsed.length === 1 ? "" : "s",
            })}
          </span>
        )}
      </div>

      {result && (
        <div className="mt-2 text-[10.5px]">
          <span className="text-accent-bright">{t("campaignDetail.added", { count: result.added })}</span>
          {result.rejected.length > 0 && (
            <ul className="mt-1 space-y-0.5">
              {result.rejected.map((r, i) => (
                <li key={`${r.value}-${i}`} className="text-risk-high">
                  ✗ <span className="font-mono">{r.value || "(blank)"}</span> —{" "}
                  {rejectCopy(r.reason, t)}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="mt-3">
        <div className="eyebrow mb-1">
          {t("campaignDetail.numbersToCall", { count: targets?.length ?? 0 })}
        </div>
        {targets === null ? (
          <p className="text-[11px] text-muted">{t("campaignDetail.loading")}</p>
        ) : targets.length === 0 ? (
          <p className="text-[11px] text-muted">
            {t("campaignDetail.emptyTargets")}
          </p>
        ) : (
          <ul className="max-h-52 space-y-1 overflow-y-auto">
            {targets.map((tg) => (
              <TargetRow key={tg.id} target={tg} />
            ))}
          </ul>
        )}
      </div>
      <ErrorLine msg={error} />
    </div>
  );
}

/* ── One target + its call log ───────────────────────────────────────────── */

const ATTEMPT_STYLE: Record<string, string> = {
  engaged: "text-accent-bright",
  no_answer: "text-muted",
  failed: "text-risk-high",
};

/**
 * A dial target, expandable into its call log.
 *
 * `attempt_count` only says "tried 3 times"; the log says WHEN each attempt
 * happened and what came of it — including the silent ones, since "never picks
 * up" is itself intel. Loaded lazily on first expand: a campaign can hold
 * hundreds of targets and most are never opened.
 */
function TargetRow({ target }: { target: DialTarget }) {
  const t = useTranslations("honeypotOps");
  const [open, setOpen] = useState(false);
  const [attempts, setAttempts] = useState<DialAttempt[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (!next || attempts !== null) return;
    try {
      setAttempts(await listAttempts(target.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : t("targetRow.errorLoadFailed"));
    }
  };

  return (
    <li className="rounded-lg bg-elevated text-[11px]">
      <button
        type="button"
        onClick={() => void toggle()}
        className="flex w-full items-center justify-between gap-2 px-2.5 py-1 text-left transition-colors hover:text-accent-bright"
      >
        <span className="font-mono text-fg">
          <span className="mr-1 inline-block w-2 text-muted">
            {open ? "▾" : "▸"}
          </span>
          {target.phone_number}
        </span>
        <span className="text-muted">
          {t(`targetRow.targetStatus.${target.status}`)}
          {target.attempt_count > 0 && ` · ${t("targetRow.attemptsSuffix", { count: target.attempt_count })}`}
          {target.last_error && ` · ${target.last_error}`}
        </span>
      </button>

      {open && (
        <div className="border-t border-line px-2.5 py-1.5">
          {error ? (
            <p className="text-[10.5px] text-risk-high">✗ {error}</p>
          ) : attempts === null ? (
            <p className="text-[10.5px] text-muted">{t("targetRow.loadingCallLog")}</p>
          ) : attempts.length === 0 ? (
            <p className="text-[10.5px] text-muted">
              {t("targetRow.noAttempts")}
            </p>
          ) : (
            <ul className="space-y-0.5">
              {attempts.map((a) => (
                <li key={a.id} className="flex items-baseline gap-2 text-[10.5px]">
                  <span className="w-8 shrink-0 font-mono text-muted">
                    #{a.attempt_no}
                  </span>
                  <span
                    className={`w-16 shrink-0 ${ATTEMPT_STYLE[a.outcome] ?? "text-fg"}`}
                  >
                    {t(`targetRow.outcome.${a.outcome}`)}
                  </span>
                  <span className="text-muted">
                    {fmtDate(a.started_at)}
                    {a.outcome === "engaged" &&
                      a.duration_seconds != null &&
                      ` · ${a.duration_seconds}s`}
                    {a.error && ` · ${a.error}`}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

/* ── Campaigns tab ───────────────────────────────────────────────────────── */

/**
 * The outcome mix at a glance — "9 of 40 called · 6 engaged · 3 no answer".
 *
 * A bare status word ("running") doesn't answer the question an investigator
 * actually has, which is how far through the list we are and what came of it.
 * Built from the per-status counts the list endpoint already returns; statuses
 * with a zero count are omitted rather than padding the line with noise.
 */
function progressSummary(c: DialCampaign, t: OpsT): string {
  const n = (k: string) => c.counts[k] ?? 0;
  const called = n("engaged") + n("no_answer") + n("failed");
  const parts = [t("campaignsTab.progress.called", { called, total: c.target_count })];
  if (n("dialing")) parts.push(t("campaignsTab.progress.dialingNow", { count: n("dialing") }));
  if (n("engaged")) parts.push(t("campaignsTab.progress.engaged", { count: n("engaged") }));
  if (n("no_answer")) parts.push(t("campaignsTab.progress.noAnswer", { count: n("no_answer") }));
  if (n("failed")) parts.push(t("campaignsTab.progress.failed", { count: n("failed") }));
  return parts.join(" · ");
}

function CampaignsTab() {
  const t = useTranslations("honeypotOps");
  const [rows, setRows] = useState<DialCampaign[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [pacing, setPacing] = useState("6");
  const [open, setOpen] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      setRows(await listCampaigns());
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("campaignsTab.errors.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const create = async () => {
    if (!name.trim()) return;
    setSaving(true);
    try {
      const paceNum = Number(pacing);
      const created = await createCampaign({
        name: name.trim(),
        pacing_per_minute: Number.isFinite(paceNum) ? paceNum : 6,
      });
      setName("");
      setError(null);
      await load();
      setOpen(created.id); // jump straight to uploading its targets
    } catch (e) {
      setError(e instanceof Error ? e.message : t("campaignsTab.errors.createFailed"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title={t("campaignsTab.cardTitle")}>
      <p className="mb-3 text-[10.5px] text-muted">
        {t("campaignsTab.intro")}
      </p>

      <div className="mb-3 grid gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto]">
        <input
          type="text"
          value={name}
          placeholder={t("campaignsTab.namePlaceholder")}
          onChange={(e) => setName(e.target.value)}
          className={INPUT_CLS}
        />
        <label className="flex min-w-0 items-center gap-1.5">
          <input
            type="number"
            min={1}
            max={60}
            value={pacing}
            onChange={(e) => setPacing(e.target.value)}
            title={t("campaignsTab.pacingTitle")}
            className={`${INPUT_CLS} tnum w-full min-w-0`}
          />
          <span className="shrink-0 text-[10px] text-muted">{t("campaignsTab.pacingUnit")}</span>
        </label>
        <button
          type="button"
          onClick={() => void create()}
          disabled={!name.trim() || saving}
          className={BTN_CLS}
        >
          {saving ? t("campaignsTab.createBusy") : t("campaignsTab.create")}
        </button>
      </div>

      {loading ? (
        <p className="text-[11px] text-muted">{t("campaignsTab.loading")}</p>
      ) : rows.length === 0 ? (
        <p className="text-[11px] text-muted">
          {t("campaignsTab.empty")}
        </p>
      ) : (
        <ul className="space-y-1">
          {rows.map((c) => {
            const isOpen = open === c.id;
            return (
              <li key={c.id} className="rounded-lg bg-elevated px-2.5 py-1.5">
                <button
                  type="button"
                  onClick={() => setOpen(isOpen ? null : c.id)}
                  aria-expanded={isOpen}
                  className="flex w-full items-center justify-between gap-2 text-left text-[11.5px]"
                >
                  <span className="min-w-0">
                    <span className="text-fg">{c.name}</span>
                    <span className="ml-2 text-muted">
                      {fmtDate(c.created_at)} ·{" "}
                      <span
                        className={CAMPAIGN_STATUS_STYLE[c.status] ?? "text-muted"}
                      >
                        {t(`campaignsTab.status.${c.status}`)}
                      </span>
                      {c.target_count === 0
                        ? ` · ${t("campaignsTab.noNumbersAddedYet")}`
                        : ` · ${progressSummary(c, t)}`}
                    </span>
                  </span>
                  <span className="shrink-0 text-[10px] text-muted">
                    {isOpen ? "▾" : "▸"}
                  </span>
                </button>
                {isOpen && <CampaignDetail campaign={c} onChanged={() => void load()} />}
              </li>
            );
          })}
        </ul>
      )}
      <ErrorLine msg={error} />
    </Card>
  );
}

/* ── Triage tab ──────────────────────────────────────────────────────────── */

/**
 * One unplaced call. Attach it to an existing case, or open a new one.
 *
 * Both actions are one click from the row on purpose: triage is a queue an
 * investigator works down, and auto-linking is deliberately conservative
 * (exact-match only), so this queue is the normal path, not an error state.
 */
function TriageRow({
  row,
  cases,
  onPlaced,
}: {
  row: TriageSession;
  cases: Case[];
  onPlaced: () => void;
}) {
  const t = useTranslations("honeypotOps");
  const [busy, setBusy] = useState(false);
  const [picked, setPicked] = useState("");
  const [error, setError] = useState<string | null>(null);

  const place = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await fn();
      setError(null);
      onPlaced();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("triageTab.errors.placeFailed"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <li className="rounded-lg bg-elevated px-2.5 py-2">
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-[11.5px]">
        <span className="font-mono text-fg">{row.channel_ref ?? t("triageRow.unknownNumber")}</span>
        <span className="text-muted">
          {fmtDate(row.started_at)}
          {row.duration_seconds ? ` · ${row.duration_seconds}s` : ""}
          {row.crime_type ? ` · ${row.crime_type}` : ""}
          {" · "}
          {/* An engaged call with nothing extracted is still evidence the
              number is live — shown, never hidden, but easy to rank by. */}
          <span className={row.entity_count > 0 ? "text-accent-bright" : ""}>
            {row.entity_count === 1
              ? t("triageRow.entityCount", { count: row.entity_count })
              : t("triageRow.entityCountPlural", { count: row.entity_count })}
          </span>
        </span>
      </div>

      {row.preview && (
        <p className="mt-1 line-clamp-2 text-[10.5px] italic text-muted">
          “{row.preview}”
        </p>
      )}

      <div className="mt-1.5 flex flex-wrap items-center gap-2">
        <select
          value={picked}
          onChange={(e) => setPicked(e.target.value)}
          aria-label={t("triageRow.attachSelectLabel")}
          className={`${INPUT_CLS} min-w-0 flex-1`}
        >
          <option value="">{t("triageRow.attachPlaceholder")}</option>
          {cases.map((c) => (
            <option key={c.id} value={c.id}>
              {c.title}
            </option>
          ))}
        </select>
        <button
          type="button"
          disabled={!picked || busy}
          onClick={() => void place(() => attachTriageSession(row.id, picked))}
          className={BTN_CLS}
        >
          {busy ? t("triageRow.attachBusy") : t("triageRow.attach")}
        </button>
        <button
          type="button"
          disabled={busy}
          title={t("triageRow.newCaseTitle")}
          onClick={() => void place(() => promoteTriageSession(row.id))}
          className={BTN_CLS}
        >
          {t("triageRow.newCase")}
        </button>
      </div>
      <ErrorLine msg={error} />
    </li>
  );
}

function TriageTab() {
  const t = useTranslations("honeypotOps");
  const [rows, setRows] = useState<TriageSession[]>([]);
  const [cases, setCases] = useState<Case[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [triage, caseList] = await Promise.all([listTriage(), listCases()]);
      setRows(triage);
      setCases(caseList);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : t("triageTab.errors.loadFailed"));
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <Card title={t("triageTab.cardTitle", { count: rows.length })}>
      <p className="mb-3 text-[10.5px] text-muted">
        {t("triageTab.intro")}
      </p>

      {loading ? (
        <p className="text-[11px] text-muted">{t("triageTab.loading")}</p>
      ) : rows.length === 0 ? (
        <p className="text-[11px] text-muted">
          {t("triageTab.empty")}
        </p>
      ) : (
        <ul className="space-y-1.5">
          {rows.map((r) => (
            <TriageRow key={r.id} row={r} cases={cases} onPlaced={() => void load()} />
          ))}
        </ul>
      )}
      <ErrorLine msg={error} />
    </Card>
  );
}

/* ── Page ────────────────────────────────────────────────────────────────── */

export default function HoneypotOpsPage() {
  const t = useTranslations("honeypotOps");
  const [tab, setTab] = useState<Tab>("numbers");

  const steps = [
    t("steps.registerNumbers"),
    t("steps.uploadNumbers"),
    t("steps.fileCalls"),
  ];

  const tabList: [Tab, string][] = [
    ["numbers", t("tabs.numbers")],
    ["campaigns", t("tabs.campaigns")],
    ["triage", t("tabs.triage")],
  ];

  return (
    <div className="mx-auto max-w-[760px]">
      <div className="mb-3">
        <h1 className="text-xl font-bold tracking-tight">{t("title")}</h1>
        <p className="mt-1 text-xs text-muted">
          {t("subtitle")}
        </p>
      </div>

      {/* The three tabs are a pipeline, not three unrelated screens — a first-
          time operator has no way to know the order without being told. */}
      <ol className="mb-3.5 flex flex-wrap items-center gap-x-2 gap-y-1 rounded-card border border-line bg-card px-3 py-2 text-[10.5px] text-muted">
        {steps.map((step, i) => (
          <li key={step} className="flex items-center gap-2">
            {i > 0 && <span aria-hidden="true">→</span>}
            <span>
              <span className="mr-1 font-semibold text-accent-bright">
                {i + 1}
              </span>
              {step}
            </span>
          </li>
        ))}
      </ol>

      <div
        className="mb-3.5 flex gap-0.5 border-b border-line"
        role="tablist"
        aria-label={t("tabsAriaLabel")}
      >
        {tabList.map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`border-b-2 px-3 py-2 text-[11px] font-semibold transition-colors ${
              tab === key
                ? "border-accent text-accent-bright"
                : "border-transparent text-muted hover:text-white/60"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "numbers" ? (
        <NumbersTab />
      ) : tab === "campaigns" ? (
        <CampaignsTab />
      ) : (
        <TriageTab />
      )}
    </div>
  );
}
