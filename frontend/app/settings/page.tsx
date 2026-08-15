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
  type ClientSettings,
  type SttSourceSetting,
  type VoiceProviderSetting,
} from "@/lib/settings";
import {
  GEMINI_VOICES,
  GOOGLE_VOICES,
  checkElevenLabsVoice,
  checkGemini,
  checkGoogle,
  fetchElevenLabsVoices,
  isKnownGeminiVoice,
  isKnownGoogleVoice,
  type VoiceCheckResult,
  type VoicesResult,
} from "@/lib/honeypot/voices";

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

/* ── Advanced voice (ElevenLabs) — overrides + "Check voices" ─────────────── */

const VOICE_INPUT_CLS =
  "h-8 rounded-lg border border-line bg-elevated px-3 font-mono text-[11px] text-fg outline-none transition-colors focus:border-accent/40";

function describeVoiceCheck(res: VoiceCheckResult): { ok: boolean; label: string } {
  if (res.ok) return { ok: true, label: "✓ playing sample…" };
  if (res.error === "no_key")
    return { ok: false, label: "no ElevenLabs key set on the server" };
  const s = res.status;
  if (s === 401 || res.error === "http_401")
    return { ok: false, label: "✗ key rejected — check API key" };
  if (s === 402 || res.error === "http_402")
    return { ok: false, label: "✗ out of credits — upgrade or wait for reset" };
  if (s === 404 || s === 422 || res.error === "http_404" || res.error === "http_422")
    return { ok: false, label: "✗ not a usable voice ID (not in your library)" };
  if (res.error?.startsWith("http_"))
    return { ok: false, label: `✗ ElevenLabs error (${s ?? res.error})` };
  return { ok: false, label: "✗ couldn't reach ElevenLabs / backend" };
}

function AdvancedVoice({
  settings,
  update,
}: {
  settings: ClientSettings;
  update: (patch: Partial<ClientSettings>) => void;
}) {
  type Role = "persona" | "scammer";
  const [results, setResults] = useState<Record<Role, VoiceCheckResult | null>>({
    persona: null,
    scammer: null,
  });
  const [testing, setTesting] = useState<Record<Role, boolean>>({
    persona: false,
    scammer: false,
  });
  const [listResult, setListResult] = useState<VoicesResult | null>(null);
  // Last voice ID that tested OK per role — what a failed Test reverts to.
  // ElevenLabs IDs are opaque per-account strings with no client-side list to
  // validate against, so (unlike Gemini/Google) the revert trigger is a failed
  // Test, not red-on-type. Seeded with the currently-saved value (assumed good).
  const lastGood = useRef<Record<Role, string>>({
    persona: settings.ttsVoicePersona,
    scammer: settings.ttsVoiceScammer,
  });

  // Best-effort voice list for the autocomplete datalist — harmless if the key
  // lacks the Voices-read scope (the ▶ Test button's real check is a synth).
  useEffect(() => {
    let alive = true;
    void fetchElevenLabsVoices().then((r) => {
      if (alive) setListResult(r);
    });
    return () => {
      alive = false;
    };
  }, []);

  // Play a short sample in the given voice (button click = the user gesture that
  // lets Audio.play() run). On success, remember it as good; on failure, show
  // the reason AND revert the field to the last voice that worked.
  const testVoice = async (role: Role, rawId: string, onChange: (v: string) => void) => {
    const voiceId = rawId.trim();
    if (!voiceId) return;
    setTesting((t) => ({ ...t, [role]: true }));
    try {
      const r = await checkElevenLabsVoice(voiceId, role);
      if (r.audioBlob) {
        const url = URL.createObjectURL(r.audioBlob);
        const audio = new Audio(url);
        audio.onended = () => URL.revokeObjectURL(url);
        void audio.play().catch(() => URL.revokeObjectURL(url));
      }
      setResults((s) => ({ ...s, [role]: r }));
      if (r.ok) {
        lastGood.current[role] = voiceId; // this ID works — the new revert target
      } else if (r.status === 404 || r.status === 422) {
        // Only a genuine bad-voice error reverts. Quota (402) / key (401) /
        // network errors aren't the voice's fault — keep the ID and let the
        // label say why (out of credits / key rejected / unreachable).
        onChange(lastGood.current[role] ?? "");
      }
    } finally {
      setTesting((t) => ({ ...t, [role]: false }));
    }
  };

  const listId = "el-voice-ids";
  const voices = listResult?.voices ?? [];

  // Rendered as a function call (not a nested <Component/>) so the input keeps
  // focus across keystrokes.
  const renderVoiceField = (
    role: Role,
    label: string,
    value: string,
    onChange: (v: string) => void,
  ) => {
    const res = results[role];
    const st = value.trim() && res ? describeVoiceCheck(res) : null;
    const busy = testing[role];
    return (
      <label key={role} className="grid gap-1">
        <span className="text-[11px] font-medium text-fg">{label}</span>
        <div className="flex gap-2">
          <input
            type="text"
            list={voices.length > 0 ? listId : undefined}
            value={value}
            placeholder="server default"
            spellCheck={false}
            onChange={(e) => {
              onChange(e.target.value);
              setResults((s) => ({ ...s, [role]: null })); // clear stale Test label
            }}
            className={`${VOICE_INPUT_CLS} flex-1`}
          />
          <button
            type="button"
            onClick={() => void testVoice(role, value, onChange)}
            disabled={!value.trim() || busy}
            title="Play a short sample in this voice"
            className="h-8 shrink-0 rounded-lg border border-line bg-elevated px-2.5 text-[11px] font-semibold text-fg transition-colors hover:border-accent/40 disabled:opacity-50"
          >
            {busy ? "…" : "▶ Test"}
          </button>
        </div>
        {st && (
          <span className={`text-[10px] ${st.ok ? "text-accent-bright" : "text-risk-high"}`}>
            {st.label}
          </span>
        )}
      </label>
    );
  };

  return (
    <div className="border-t border-line pt-3.5">
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="eyebrow">Advanced voice · ElevenLabs</div>
        <div className="flex gap-3">
          <a
            href="https://elevenlabs.io/app/voices"
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] text-accent-bright hover:underline"
          >
            Open Voices ↗
          </a>
          <a
            href="https://elevenlabs.io/app/settings/api-keys"
            target="_blank"
            rel="noopener noreferrer"
            className="text-[10px] text-muted hover:underline"
          >
            Get API key ↗
          </a>
        </div>
      </div>
      <p className="mb-2.5 text-[10.5px] text-muted">
        Per-request overrides — no restart. Blank = the server default. ▶ Test plays a
        short sample (uses a few credits) and says why if it fails — out of credits,
        key rejected, or a bad voice ID. Only a bad voice ID reverts to your last
        working voice.
      </p>

      {voices.length > 0 && (
        <datalist id={listId}>
          {voices.map((v) => (
            <option key={v.id} value={v.id}>
              {v.name}
            </option>
          ))}
        </datalist>
      )}

      <div className="grid gap-2.5">
        <label className="grid gap-1">
          <span className="text-[11px] font-medium text-fg">Model</span>
          <input
            type="text"
            value={settings.ttsModel}
            placeholder="eleven_flash_v2_5"
            spellCheck={false}
            onChange={(e) => update({ ttsModel: e.target.value })}
            className={VOICE_INPUT_CLS}
          />
        </label>
        {renderVoiceField(
          "persona",
          "Persona voice ID",
          settings.ttsVoicePersona,
          (v) => update({ ttsVoicePersona: v }),
        )}
        {renderVoiceField(
          "scammer",
          "Scammer voice ID",
          settings.ttsVoiceScammer,
          (v) => update({ ttsVoiceScammer: v }),
        )}
      </div>
    </div>
  );
}

/* ── Shared voice combobox — type OR pick, ▶ Test, revert-on-invalid ──────── */

/**
 * One field for a per-role voice: a free-text input WITH a datalist of known
 * voices (so you can type any value or pick a suggestion) + a ▶ Test button.
 * Safety: a value that isn't a known voice is "red" and, on blur, **reverts** to
 * the last committed value — so an invalid/unavailable voice can never stick.
 * Only accepted values (a known voice, or blank = server default) are committed.
 */
function VoiceComboField({
  label,
  fallback,
  value,
  onCommit,
  voices,
  isKnown,
  onTest,
  describe,
  datalistId,
}: {
  label: string;
  fallback: string;
  value: string;
  onCommit: (v: string) => void;
  voices: { name: string; tone: string }[];
  isKnown: (v: string) => boolean;
  onTest: (voiceName: string) => Promise<VoiceCheckResult>;
  describe: (r: VoiceCheckResult) => { ok: boolean; label: string };
  datalistId: string;
}) {
  const [draft, setDraft] = useState(value);
  const [res, setRes] = useState<VoiceCheckResult | null>(null);
  const [busy, setBusy] = useState(false);

  // Sync when the committed value changes elsewhere (e.g. "Reset to defaults").
  useEffect(() => setDraft(value), [value]);

  const accepted = draft.trim() === "" || isKnown(draft.trim());
  const red = draft.trim() !== "" && !accepted;

  const onChange = (v: string) => {
    setDraft(v);
    setRes(null);
    if (v.trim() === "" || isKnown(v.trim())) onCommit(v.trim()); // persist valid only
  };
  const onBlur = () => {
    if (red) {
      setDraft(value); // revert the unavailable value
      setRes(null);
    }
  };
  const test = async () => {
    setBusy(true);
    try {
      const r = await onTest(draft.trim());
      if (r.audioBlob) {
        const url = URL.createObjectURL(r.audioBlob);
        const audio = new Audio(url);
        audio.onended = () => URL.revokeObjectURL(url);
        void audio.play().catch(() => URL.revokeObjectURL(url));
      }
      setRes(r);
    } finally {
      setBusy(false);
    }
  };

  const st = red
    ? { ok: false, label: "✗ not an available voice — reverts when you click away" }
    : res
      ? describe(res)
      : null;

  return (
    <label className="grid gap-1">
      <span className="text-[11px] font-medium text-fg">{label}</span>
      <div className="flex gap-2">
        <input
          type="text"
          list={datalistId}
          value={draft}
          placeholder={`server default (${fallback})`}
          spellCheck={false}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onBlur}
          className={`${VOICE_INPUT_CLS} flex-1 ${red ? "border-risk-high" : ""}`}
        />
        <button
          type="button"
          onClick={() => void test()}
          disabled={busy}
          title="Play a short sample in this voice (checks key + quota)"
          className="h-8 shrink-0 rounded-lg border border-line bg-elevated px-2.5 text-[11px] font-semibold text-fg transition-colors hover:border-accent/40 disabled:opacity-50"
        >
          {busy ? "…" : "▶ Test"}
        </button>
      </div>
      <datalist id={datalistId}>
        {voices.map((v) => (
          <option key={v.name} value={v.name}>
            {v.tone}
          </option>
        ))}
      </datalist>
      {st && (
        <span className={`text-[10px] ${st.ok ? "text-accent-bright" : "text-risk-high"}`}>
          {st.label}
        </span>
      )}
    </label>
  );
}

/* ── Advanced voice (Gemini) — per-role voice picker + "Test Gemini" ──────── */

function describeGeminiCheck(res: VoiceCheckResult): { ok: boolean; label: string } {
  if (res.ok) return { ok: true, label: "✓ ready — playing sample…" };
  if (res.error === "no_key")
    return { ok: false, label: "no Gemini key set on the server" };
  const s = res.status;
  if (s === 429 || res.error === "http_429")
    return { ok: false, label: "✗ quota exceeded — enable billing (free tier = 10/day)" };
  if (s === 403 || res.error === "http_403")
    return { ok: false, label: "✗ key rejected — check the AI Studio key" };
  if (s === 400 || res.error === "http_400")
    return { ok: false, label: "✗ not a valid voice name (check spelling)" };
  if (s === 404 || res.error === "http_404")
    return { ok: false, label: "✗ model not available in your region" };
  if (res.error?.startsWith("config:"))
    return { ok: false, label: `✗ ${res.error.slice(7).trim()}` };
  if (res.error?.startsWith("http_"))
    return { ok: false, label: `✗ Gemini error (${s ?? res.error})` };
  return { ok: false, label: "✗ couldn't reach Gemini / backend" };
}

function AdvancedGemini({
  settings,
  update,
}: {
  settings: ClientSettings;
  update: (patch: Partial<ClientSettings>) => void;
}) {
  return (
    <div className="border-t border-line pt-3.5">
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="eyebrow">Advanced voice · Gemini</div>
        <a
          href="https://ai.google.dev/gemini-api/docs/speech-generation"
          target="_blank"
          rel="noopener noreferrer"
          className="text-[10px] text-accent-bright hover:underline"
        >
          Voice docs ↗
        </a>
      </div>
      <p className="mb-2.5 text-[10.5px] text-muted">
        Per-request overrides — no restart. Type or pick a prebuilt voice (the tone
        is its character); the style directive does the emotional shaping. ▶ Test
        plays a sample and spends one Gemini request (free tier = 10/day).
      </p>

      <div className="grid gap-2.5">
        <VoiceComboField
          label="Persona voice"
          fallback="Sulafat"
          value={settings.geminiVoicePersona}
          onCommit={(v) => update({ geminiVoicePersona: v })}
          voices={GEMINI_VOICES}
          isKnown={isKnownGeminiVoice}
          onTest={(name) => checkGemini("persona", name)}
          describe={describeGeminiCheck}
          datalistId="gemini-voices-persona"
        />
        <VoiceComboField
          label="Scammer voice"
          fallback="Charon"
          value={settings.geminiVoiceScammer}
          onCommit={(v) => update({ geminiVoiceScammer: v })}
          voices={GEMINI_VOICES}
          isKnown={isKnownGeminiVoice}
          onTest={(name) => checkGemini("scammer", name)}
          describe={describeGeminiCheck}
          datalistId="gemini-voices-scammer"
        />
      </div>
    </div>
  );
}

/* ── Advanced voice (Google) — per-role voice picker + "Test" ────────────── */

function describeGoogleCheck(res: VoiceCheckResult): { ok: boolean; label: string } {
  if (res.ok) return { ok: true, label: "✓ ready — playing sample…" };
  if (res.error === "no_key")
    return { ok: false, label: "no Google TTS key set on the server" };
  const s = res.status;
  if (s === 403 || res.error === "http_403")
    return { ok: false, label: "✗ key rejected / Text-to-Speech API not enabled" };
  if (s === 429 || res.error === "http_429")
    return { ok: false, label: "✗ quota exceeded" };
  if (s === 400 || res.error === "http_400")
    return { ok: false, label: "✗ bad request (voice not available for id-ID)" };
  if (res.error?.startsWith("http_"))
    return { ok: false, label: `✗ Google error (${s ?? res.error})` };
  return { ok: false, label: "✗ couldn't reach Google / backend" };
}

function AdvancedGoogle({
  settings,
  update,
}: {
  settings: ClientSettings;
  update: (patch: Partial<ClientSettings>) => void;
}) {
  return (
    <div className="border-t border-line pt-3.5">
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="eyebrow">Advanced voice · Google</div>
        <a
          href="https://cloud.google.com/text-to-speech/docs/voices"
          target="_blank"
          rel="noopener noreferrer"
          className="text-[10px] text-accent-bright hover:underline"
        >
          Voice list ↗
        </a>
      </div>
      <p className="mb-2.5 text-[10.5px] text-muted">
        Per-request overrides — no restart. Type or pick a flat id-ID WaveNet /
        Standard voice (no style control). ▶ Test plays a sample; ~1M chars/month
        free.
      </p>

      <div className="grid gap-2.5">
        <VoiceComboField
          label="Persona voice"
          fallback="id-ID-Wavenet-A"
          value={settings.googleVoicePersona}
          onCommit={(v) => update({ googleVoicePersona: v })}
          voices={GOOGLE_VOICES}
          isKnown={isKnownGoogleVoice}
          onTest={(name) => checkGoogle("persona", name)}
          describe={describeGoogleCheck}
          datalistId="google-voices-persona"
        />
        <VoiceComboField
          label="Scammer voice"
          fallback="id-ID-Wavenet-B"
          value={settings.googleVoiceScammer}
          onCommit={(v) => update({ googleVoiceScammer: v })}
          voices={GOOGLE_VOICES}
          isKnown={isKnownGoogleVoice}
          onTest={(name) => checkGoogle("scammer", name)}
          describe={describeGoogleCheck}
          datalistId="google-voices-scammer"
        />
      </div>
    </div>
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
          <AdvancedVoice settings={settings} update={update} />
        )}
        {settings.voiceProvider === "gemini" && (
          <AdvancedGemini settings={settings} update={update} />
        )}
        {settings.voiceProvider === "google" && (
          <AdvancedGoogle settings={settings} update={update} />
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
