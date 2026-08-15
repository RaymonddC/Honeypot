"use client";

/**
 * Control Panel — analyst-local voice/call settings (lib/settings.ts) +
 * a READ-ONLY backend status panel (GET /api/config). Settings persist to
 * localStorage and take effect on the NEXT honeypot call — no rebuild.
 * NEVER shows or accepts secrets: the backend section only ever renders
 * booleans / mode strings, matching the API contract (docs/API-Contract.md).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  CALL_MODE_SETTINGS,
  STT_SOURCE_SETTINGS,
  VOICE_PROVIDER_SETTINGS,
  fetchBackendConfig,
  useSettings,
  type BackendConfigStatus,
  type CallModeSetting,
  type SttSourceSetting,
  type VoiceProviderSetting,
} from "@/lib/settings";

const VOICE_PROVIDER_COPY: Record<
  VoiceProviderSetting,
  { label: string; sub: string }
> = {
  browser: { label: "Browser", sub: "Web Speech API · free, offline" },
  elevenlabs: {
    label: "ElevenLabs",
    sub: "Backend audio · GET /sessions/{id}/audio/{seq}",
  },
  gemini: {
    label: "Gemini TTS",
    sub: "Backend audio · style-controlled persona (AI Studio)",
  },
  google: {
    label: "Google TTS",
    sub: "Backend audio · GET /sessions/{id}/audio/{seq}",
  },
};

const CALL_MODE_COPY: Record<CallModeSetting, { label: string; sub: string }> =
  {
    scripted: {
      label: "Scripted replay",
      sub: "Agent loop pre-run server-side · faithful simulation",
    },
    "live-mic": {
      label: "Live mic (interactive)",
      sub: "You play the scammer on the mic · Tier-B, docs/Live-Voice-Calls.md",
    },
  };

const STT_SOURCE_COPY: Record<SttSourceSetting, { label: string; sub: string }> =
  {
    "web-speech": {
      label: "Browser Web Speech API",
      sub: "Chrome/Edge only · id-ID · free (Safari/Firefox fall back to text input)",
    },
  };

/* ── Shared card shell (mirrors EntityPanel/CustodyCard) ────────────────── */

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
      <div className="flex items-center justify-between border-b border-line px-3.5 py-3">
        <span className="eyebrow">{title}</span>
        {action}
      </div>
      <div className="space-y-5 p-3.5">{children}</div>
    </div>
  );
}

/* ── Segmented option control (radio-group semantics) ────────────────────── */

function SegmentedControl<T extends string>({
  legend,
  hint,
  name,
  options,
  copy,
  value,
  onChange,
}: {
  legend: string;
  hint?: string;
  name: string;
  options: readonly T[];
  copy: Record<T, { label: string; sub: string }>;
  value: T;
  onChange: (v: T) => void;
}) {
  return (
    <fieldset>
      <legend className="text-[13px] font-medium text-fg">{legend}</legend>
      {hint && <p className="mt-0.5 text-[11px] text-muted">{hint}</p>}
      <div
        role="radiogroup"
        aria-label={legend}
        className="mt-2.5 grid gap-2 sm:grid-cols-3"
      >
        {options.map((opt) => {
          const active = opt === value;
          return (
            <button
              key={opt}
              type="button"
              role="radio"
              aria-checked={active}
              name={name}
              onClick={() => onChange(opt)}
              className={`cursor-pointer rounded-lg border px-3 py-2.5 text-left transition-colors ${
                active
                  ? "border-accent/40 bg-accent/[.08]"
                  : "border-line bg-elevated hover:border-white/15"
              }`}
            >
              <div
                className={`text-xs font-semibold ${
                  active ? "text-accent-bright" : "text-fg"
                }`}
              >
                {copy[opt].label}
              </div>
              <div className="mt-0.5 text-[10.5px] leading-snug text-muted">
                {copy[opt].sub}
              </div>
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

/* ── Backend status (read-only) ──────────────────────────────────────────── */

function ModeChip({ mode }: { mode: "POC" | "LIVE" }) {
  return (
    <span
      className={`rounded-md border px-2 py-0.5 font-mono text-[10.5px] font-bold tracking-widest ${
        mode === "LIVE"
          ? "border-accent/40 bg-accent/10 text-accent-bright"
          : "border-risk-med/40 bg-risk-med/10 text-risk-med"
      }`}
    >
      {mode}
    </span>
  );
}

function BackendStatus({
  status,
  loading,
}: {
  status: BackendConfigStatus | null;
  loading: boolean;
}) {
  if (loading && !status) {
    return (
      <div className="grid h-24 animate-pulse place-items-center text-[11px] text-muted">
        Reading GET /api/config…
      </div>
    );
  }
  if (!status) return null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[11px] text-muted">Global mode</span>
        <ModeChip mode={status.mode} />
        {status.source === "env" && (
          <span
            className="rounded-md border border-risk-med/30 bg-risk-med/10 px-1.5 py-0.5 text-[10px] text-risk-med"
            title="GET /api/config was unreachable — showing the NEXT_PUBLIC_ITTU_MODE build fallback"
          >
            env fallback · backend unreachable
          </span>
        )}
      </div>

      {status.modules.length > 0 && (
        <div>
          <div className="text-[11px] text-muted">Per-module mode</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {status.modules.map((m) => (
              <span
                key={m.module}
                className="rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[10.5px] text-fg/80"
                title={m.adapters ? JSON.stringify(m.adapters) : undefined}
              >
                {m.module} · <ModeChip mode={m.mode} />
              </span>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="text-[11px] text-muted">Server TTS provider</div>
        <div className="mt-1.5 font-mono text-xs text-fg">
          {status.ttsProvider ?? (
            <span className="text-muted">
              not reported by this backend build — Control Panel choice below
              still governs playback path (browser vs. backend audio)
            </span>
          )}
        </div>
      </div>

      <div>
        <div className="text-[11px] text-muted">
          Live-voice key presence{" "}
          <span className="text-muted/70">(booleans only — never a value)</span>
        </div>
        {status.keys.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {status.keys.map((k) => (
              <span
                key={k.provider}
                className={`rounded-md border px-2 py-0.5 font-mono text-[10.5px] ${
                  k.present
                    ? "border-accent/30 bg-accent/10 text-accent-bright"
                    : "border-line bg-elevated text-muted"
                }`}
              >
                {k.provider} · {k.present ? "configured" : "not set"}
              </span>
            ))}
          </div>
        ) : (
          <p className="mt-1 text-[11px] text-muted">
            not reported by this backend build yet.
          </p>
        )}
      </div>
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────────── */

export default function SettingsPage() {
  const { settings, update, reset } = useSettings();
  const [status, setStatus] = useState<BackendConfigStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const loadSeq = useRef(0);

  const load = useCallback(async () => {
    const seq = ++loadSeq.current;
    setLoading(true);
    const result = await fetchBackendConfig();
    if (seq !== loadSeq.current) return; // superseded
    setStatus(result);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto max-w-[760px]">
      {/* ── header ─────────────────────────────────────────────────── */}
      <div className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Control Panel</h1>
          <p className="mt-1 text-xs text-muted">
            Analyst-local voice &amp; call preferences — saved to this browser,
            applied on your next honeypot call. No API keys or secrets ever
            live here.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="h-8 flex-none rounded-lg border border-white/10 bg-elevated px-3.5 text-xs font-semibold text-fg transition-colors hover:bg-white/[.07] disabled:opacity-50"
        >
          {loading ? "Refreshing…" : "Refresh status"}
        </button>
      </div>

      <Card title="Voice & call">
        <SegmentedControl
          legend="Voice provider"
          hint="Which engine speaks the honeypot persona's lines."
          name="voiceProvider"
          options={VOICE_PROVIDER_SETTINGS}
          copy={VOICE_PROVIDER_COPY}
          value={settings.voiceProvider}
          onChange={(v) => update({ voiceProvider: v })}
        />
        <SegmentedControl
          legend="Call mode"
          hint="How /honeypot/call runs the conversation."
          name="callMode"
          options={CALL_MODE_SETTINGS}
          copy={CALL_MODE_COPY}
          value={settings.callMode}
          onChange={(v) => update({ callMode: v })}
        />
        <SegmentedControl
          legend="Speech-to-text source"
          hint="Used to transcribe the operator's mic in live-mic mode."
          name="sttSource"
          options={STT_SOURCE_SETTINGS}
          copy={STT_SOURCE_COPY}
          value={settings.sttSource}
          onChange={(v) => update({ sttSource: v })}
        />

        {settings.voiceProvider === "elevenlabs" && (
          <div className="border-t border-line pt-3.5">
            <div className="eyebrow mb-1">Advanced voice · ElevenLabs</div>
            <p className="mb-2.5 text-[10.5px] text-muted">
              Per-request overrides — no restart. Blank = the server default;
              voice IDs come from your ElevenLabs Voices page.
            </p>
            <div className="grid gap-2.5">
              <label className="grid gap-1">
                <span className="text-[11px] font-medium text-fg">Model</span>
                <input
                  type="text"
                  value={settings.ttsModel}
                  placeholder="eleven_flash_v2_5"
                  spellCheck={false}
                  onChange={(e) => update({ ttsModel: e.target.value })}
                  className="h-8 rounded-lg border border-line bg-elevated px-3 font-mono text-[11px] text-fg outline-none transition-colors focus:border-accent/40"
                />
              </label>
              <label className="grid gap-1">
                <span className="text-[11px] font-medium text-fg">
                  Persona voice ID
                </span>
                <input
                  type="text"
                  value={settings.ttsVoicePersona}
                  placeholder="server default"
                  spellCheck={false}
                  onChange={(e) => update({ ttsVoicePersona: e.target.value })}
                  className="h-8 rounded-lg border border-line bg-elevated px-3 font-mono text-[11px] text-fg outline-none transition-colors focus:border-accent/40"
                />
              </label>
              <label className="grid gap-1">
                <span className="text-[11px] font-medium text-fg">
                  Scammer voice ID
                </span>
                <input
                  type="text"
                  value={settings.ttsVoiceScammer}
                  placeholder="server default"
                  spellCheck={false}
                  onChange={(e) => update({ ttsVoiceScammer: e.target.value })}
                  className="h-8 rounded-lg border border-line bg-elevated px-3 font-mono text-[11px] text-fg outline-none transition-colors focus:border-accent/40"
                />
              </label>
            </div>
          </div>
        )}

        <div className="flex items-center justify-between border-t border-line pt-3.5">
          <p className="text-[10.5px] text-muted">
            Overrides this browser&apos;s build defaults (NEXT_PUBLIC_*). Clear
            to fall back to the deployment&apos;s configured defaults.
          </p>
          <button
            type="button"
            onClick={reset}
            className="h-8 flex-none rounded-lg border border-line bg-elevated px-3 text-[11px] font-semibold text-muted transition-colors hover:bg-white/[.07] hover:text-fg"
          >
            Reset to defaults
          </button>
        </div>
      </Card>

      <Card title="Backend status · GET /api/config (read-only)">
        <BackendStatus status={status} loading={loading} />
      </Card>
    </div>
  );
}
