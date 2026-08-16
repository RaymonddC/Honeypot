"use client";

/**
 * Honeypot Ops — the outbound-calling operations surface
 * (docs/Voice-Honeypot-Outbound.md §2/§7).
 *
 * Deliberately NOT the Control Panel: that page holds per-browser analyst
 * preferences (localStorage). Numbers and campaigns are shared, agency-scoped,
 * server-side operational data with their own lifecycle.
 *
 * Phase 3 = CRUD only. Starting a campaign moves its status; no call is placed
 * (the dial worker is phase 4, real Twilio calls phase 5).
 */

import { useCallback, useEffect, useState } from "react";
import {
  createCampaign,
  listCampaigns,
  listNumbers,
  listTargets,
  normalizeE164,
  pauseCampaign,
  registerNumber,
  splitPasted,
  startCampaign,
  updateNumber,
  uploadTargets,
  type DialCampaign,
  type DialTarget,
  type HoneypotNumber,
  type UploadTargetsResult,
} from "@/lib/honeypot-ops/api";

type Tab = "numbers" | "campaigns";

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
      setError(e instanceof Error ? e.message : "could not load numbers");
    } finally {
      setLoading(false);
    }
  }, []);

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
      setError(e instanceof Error ? e.message : "could not register number");
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
      setError(e instanceof Error ? e.message : "could not update number");
    }
  };

  return (
    <Card
      title="Number pool"
      action={
        <a
          href="https://console.twilio.com/us1/develop/phone-numbers/manage/incoming"
          target="_blank"
          rel="noopener noreferrer"
          className="text-[10px] text-accent-bright hover:underline"
        >
          Twilio console ↗
        </a>
      }
    >
      <p className="mb-3 text-[10.5px] text-muted">
        The numbers the honeypot dials <em>from</em>, rotated so a single caller
        ID isn&apos;t burned. Buy and configure them in the Twilio console, then
        register them here — this app never provisions numbers itself.
      </p>

      <div className="mb-3 grid gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_minmax(0,1.2fr)_auto]">
        <input
          type="text"
          value={phone}
          placeholder="+6281234567890"
          spellCheck={false}
          onChange={(e) => setPhone(e.target.value)}
          className={`${INPUT_CLS} font-mono ${phoneBad ? "border-risk-high" : ""}`}
        />
        <input
          type="text"
          value={sid}
          placeholder="Twilio SID (optional)"
          spellCheck={false}
          onChange={(e) => setSid(e.target.value)}
          className={`${INPUT_CLS} font-mono`}
        />
        <input
          type="text"
          value={label}
          placeholder="Label, e.g. Bareskrim #1"
          onChange={(e) => setLabel(e.target.value)}
          className={INPUT_CLS}
        />
        <button
          type="button"
          onClick={() => void add()}
          disabled={!normalized || saving}
          className={BTN_CLS}
        >
          {saving ? "…" : "Register"}
        </button>
      </div>
      {phoneBad && (
        <p className="mb-2 text-[10px] text-risk-high">
          Must be E.164 with a country code — e.g. +6281234567890 (a bare
          08&hellip; is rejected rather than guessed at).
        </p>
      )}

      {loading ? (
        <p className="text-[11px] text-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-[11px] text-muted">
          No numbers yet — register the first one above.
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
                  {n.label || "—"} ·{" "}
                  <span className={NUMBER_STATUS_STYLE[n.status] ?? "text-muted"}>
                    {n.status}
                  </span>
                </span>
              </div>
              <button
                type="button"
                onClick={() => void toggleRetire(n)}
                title={
                  n.status === "retired"
                    ? "Return this number to rotation"
                    : "Stop dialing from this number (kept for provenance)"
                }
                className="shrink-0 text-[10.5px] text-accent-bright hover:underline"
              >
                {n.status === "retired" ? "Reactivate" : "Retire"}
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

function CampaignDetail({
  campaign,
  onChanged,
}: {
  campaign: DialCampaign;
  onChanged: () => void;
}) {
  const [targets, setTargets] = useState<DialTarget[] | null>(null);
  const [paste, setPaste] = useState("");
  const [result, setResult] = useState<UploadTargetsResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadTargets = useCallback(async () => {
    try {
      setTargets(await listTargets(campaign.id));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "could not load targets");
    }
  }, [campaign.id]);

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
      setError(e instanceof Error ? e.message : "upload failed");
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
      setError(e instanceof Error ? e.message : `could not ${action} campaign`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mt-2 border-t border-line pt-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={() => void lifecycle("start")}
          disabled={busy || campaign.status === "running" || campaign.status === "completed"}
          title="Mark the campaign running (does not dial yet — the dialer is phase 4)"
          className={BTN_CLS}
        >
          {campaign.status === "paused" ? "Resume" : "Start"}
        </button>
        <button
          type="button"
          onClick={() => void lifecycle("pause")}
          disabled={busy || campaign.status !== "running"}
          className={BTN_CLS}
        >
          Pause
        </button>
        <span className="text-[10px] text-muted">
          Status changes only — no calls are placed yet.
        </span>
      </div>

      <label className="grid gap-1">
        <span className="text-[11px] font-medium text-fg">
          Add targets — paste one number per line (CSV: number first)
        </span>
        <textarea
          value={paste}
          onChange={(e) => setPaste(e.target.value)}
          rows={4}
          spellCheck={false}
          placeholder={"+6281234567890\n+6285600001111,Kredibel,reported 3x"}
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
          {busy ? "…" : "Upload"}
        </button>
        {parsed.length > 0 && (
          <span className="text-[10px] text-muted">
            {validCount} of {parsed.length} line{parsed.length === 1 ? "" : "s"}{" "}
            look valid
          </span>
        )}
      </div>

      {result && (
        <div className="mt-2 text-[10.5px]">
          <span className="text-accent-bright">✓ {result.added} added</span>
          {result.rejected.length > 0 && (
            <ul className="mt-1 space-y-0.5">
              {result.rejected.map((r, i) => (
                <li key={`${r.value}-${i}`} className="text-risk-high">
                  ✗ <span className="font-mono">{r.value || "(blank)"}</span> —{" "}
                  {r.reason.replace(/_/g, " ")}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}

      <div className="mt-3">
        <div className="eyebrow mb-1">Targets · {targets?.length ?? 0}</div>
        {targets === null ? (
          <p className="text-[11px] text-muted">Loading…</p>
        ) : targets.length === 0 ? (
          <p className="text-[11px] text-muted">
            None yet — paste a dial list above.
          </p>
        ) : (
          <ul className="max-h-52 space-y-1 overflow-y-auto">
            {targets.map((t) => (
              <li
                key={t.id}
                className="flex items-center justify-between gap-2 rounded-lg bg-elevated px-2.5 py-1 text-[11px]"
              >
                <span className="font-mono text-fg">{t.phone_number}</span>
                <span className="text-muted">
                  {t.status}
                  {t.attempt_count > 0 && ` · ${t.attempt_count} attempts`}
                  {t.last_error && ` · ${t.last_error}`}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <ErrorLine msg={error} />
    </div>
  );
}

/* ── Campaigns tab ───────────────────────────────────────────────────────── */

function CampaignsTab() {
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
      setError(e instanceof Error ? e.message : "could not load campaigns");
    } finally {
      setLoading(false);
    }
  }, []);

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
      setError(e instanceof Error ? e.message : "could not create campaign");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card title="Dial campaigns">
      <p className="mb-3 text-[10.5px] text-muted">
        A batch of scammer numbers to work through. Upload the list, then start
        it — dialing itself is not wired yet, and engaging real reported numbers
        stays gated on law-enforcement authorization.
      </p>

      <div className="mb-3 grid gap-2 sm:grid-cols-[minmax(0,2fr)_minmax(0,1fr)_auto]">
        <input
          type="text"
          value={name}
          placeholder="Campaign name, e.g. Judol sweep Aug"
          onChange={(e) => setName(e.target.value)}
          className={INPUT_CLS}
        />
        <input
          type="number"
          min={1}
          max={60}
          value={pacing}
          onChange={(e) => setPacing(e.target.value)}
          title="Dial pacing cap (calls per minute)"
          className={`${INPUT_CLS} tnum`}
        />
        <button
          type="button"
          onClick={() => void create()}
          disabled={!name.trim() || saving}
          className={BTN_CLS}
        >
          {saving ? "…" : "Create"}
        </button>
      </div>

      {loading ? (
        <p className="text-[11px] text-muted">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="text-[11px] text-muted">
          No campaigns yet — create one above.
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
                      {fmtDate(c.created_at)} · {c.target_count} target
                      {c.target_count === 1 ? "" : "s"} ·{" "}
                      <span
                        className={CAMPAIGN_STATUS_STYLE[c.status] ?? "text-muted"}
                      >
                        {c.status}
                      </span>
                      {c.counts.engaged ? ` · ${c.counts.engaged} engaged` : ""}
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

/* ── Page ────────────────────────────────────────────────────────────────── */

export default function HoneypotOpsPage() {
  const [tab, setTab] = useState<Tab>("numbers");

  return (
    <div className="mx-auto max-w-[760px]">
      <div className="mb-4">
        <h1 className="text-xl font-bold tracking-tight">Honeypot Ops</h1>
        <p className="mt-1 text-xs text-muted">
          Outbound calling operations — the pool of numbers we dial from and the
          campaigns of numbers to work through. Shared across your agency (unlike
          the Control Panel, which is per-browser).
        </p>
      </div>

      <div
        className="mb-3.5 flex gap-0.5 border-b border-line"
        role="tablist"
        aria-label="Honeypot Ops sections"
      >
        {(
          [
            ["numbers", "Numbers"],
            ["campaigns", "Campaigns"],
          ] as const
        ).map(([key, label]) => (
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

      {tab === "numbers" ? <NumbersTab /> : <CampaignsTab />}
    </div>
  );
}
