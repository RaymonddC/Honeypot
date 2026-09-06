"use client";

/**
 * Control Panel — analyst-local voice/call settings (lib/settings.ts) +
 * a READ-ONLY backend status panel (GET /api/config). Settings persist to
 * localStorage and take effect on the NEXT honeypot call — no rebuild.
 * NEVER shows or accepts secrets: the backend section only ever renders
 * booleans / mode strings, matching the API contract (docs/API-Contract.md).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { useLocale } from "@/components/i18n/locale-provider";
import type { Locale } from "@/i18n/config";
import { useTheme, type ThemeChoice } from "@/components/theme/theme-provider";
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

type SettingsT = ReturnType<typeof useTranslations>;

function voiceProviderCopy(
  t: SettingsT,
): Record<VoiceProviderSetting, { label: string; sub: string }> {
  return {
    browser: {
      label: t("voiceCall.voiceProvider.browser.label"),
      sub: t("voiceCall.voiceProvider.browser.sub"),
    },
    elevenlabs: {
      label: t("voiceCall.voiceProvider.elevenlabs.label"),
      sub: t("voiceCall.voiceProvider.elevenlabs.sub"),
    },
    gemini: {
      label: t("voiceCall.voiceProvider.gemini.label"),
      sub: t("voiceCall.voiceProvider.gemini.sub"),
    },
    google: {
      label: t("voiceCall.voiceProvider.google.label"),
      sub: t("voiceCall.voiceProvider.google.sub"),
    },
  };
}

function callModeCopy(
  t: SettingsT,
): Record<CallModeSetting, { label: string; sub: string }> {
  return {
    scripted: {
      label: t("voiceCall.callMode.scripted.label"),
      sub: t("voiceCall.callMode.scripted.sub"),
    },
    "live-mic": {
      label: t("voiceCall.callMode.liveMic.label"),
      sub: t("voiceCall.callMode.liveMic.sub"),
    },
  };
}

function sttSourceCopy(
  t: SettingsT,
): Record<SttSourceSetting, { label: string; sub: string }> {
  return {
    "web-speech": {
      label: t("voiceCall.sttSource.webSpeech.label"),
      sub: t("voiceCall.sttSource.webSpeech.sub"),
    },
  };
}

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
      {hint && <p className="mt-0.5 text-[12px] text-muted">{hint}</p>}
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
                  : "border-line bg-elevated hover:border-fg/15"
              }`}
            >
              <div
                className={`text-[12px] font-semibold ${
                  active ? "text-accent-bright" : "text-fg"
                }`}
              >
                {copy[opt].label}
              </div>
              <div className="mt-0.5 text-[12px] leading-snug text-muted">
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
  "h-8 rounded-lg border border-line bg-elevated px-3 font-mono text-[12px] text-fg outline-none transition-colors focus:border-[#0099ff]/60";

function describeVoiceCheck(
  res: VoiceCheckResult,
  t: SettingsT,
): { ok: boolean; label: string } {
  if (res.ok) return { ok: true, label: t("voiceCheck.elevenlabs.playing") };
  if (res.error === "no_key")
    return { ok: false, label: t("voiceCheck.elevenlabs.noKey") };
  const s = res.status;
  if (s === 401 || res.error === "http_401")
    return { ok: false, label: t("voiceCheck.elevenlabs.keyRejected") };
  if (s === 402 || res.error === "http_402")
    return { ok: false, label: t("voiceCheck.elevenlabs.outOfCredits") };
  if (s === 404 || s === 422 || res.error === "http_404" || res.error === "http_422")
    return { ok: false, label: t("voiceCheck.elevenlabs.badVoiceId") };
  if (res.error?.startsWith("http_"))
    return { ok: false, label: t("voiceCheck.elevenlabs.httpError", { code: String(s ?? res.error) }) };
  return { ok: false, label: t("voiceCheck.elevenlabs.unreachable") };
}

function AdvancedVoice({
  settings,
  update,
}: {
  settings: ClientSettings;
  update: (patch: Partial<ClientSettings>) => void;
}) {
  const t = useTranslations("settings");
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
    setTesting((prev) => ({ ...prev, [role]: true }));
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
      } else {
        // Any failure reverts to the last working voice; the label (kept below)
        // says exactly why — out of credits / key rejected / not a usable ID /
        // unreachable — so the user knows whether it's the voice or the account.
        onChange(lastGood.current[role] ?? "");
      }
    } finally {
      setTesting((prev) => ({ ...prev, [role]: false }));
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
    // Always show a Test result (even after reverting to the blank default) so
    // the reason for a failure/revert stays visible until the user edits again.
    const st = res ? describeVoiceCheck(res, t) : null;
    const busy = testing[role];
    return (
      <label key={role} className="grid gap-1">
        <span className="text-[12px] font-medium text-fg">{label}</span>
        <div className="flex gap-2">
          <input
            type="text"
            list={voices.length > 0 ? listId : undefined}
            value={value}
            placeholder={t("advancedVoice.serverDefaultPlaceholder")}
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
            title={t("advancedVoice.testTitle")}
            className="h-8 shrink-0 rounded-lg border border-line bg-elevated px-2.5 text-[12px] font-semibold text-fg transition-colors hover:border-accent/40 disabled:opacity-50"
          >
            {busy ? t("advancedVoice.testBusy") : t("advancedVoice.testButton")}
          </button>
        </div>
        {st && (
          <span className={`text-[12px] ${st.ok ? "text-accent-bright" : "text-risk-high"}`}>
            {st.label}
          </span>
        )}
      </label>
    );
  };

  return (
    <div className="border-t border-line pt-3.5">
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="eyebrow">{t("advancedVoice.elevenlabsEyebrow")}</div>
        <div className="flex gap-3">
          <a
            href="https://elevenlabs.io/app/voices"
            target="_blank"
            rel="noopener noreferrer"
            className="text-[12px] text-accent-bright hover:underline"
          >
            {t("advancedVoice.openVoices")}
          </a>
          <a
            href="https://elevenlabs.io/app/settings/api-keys"
            target="_blank"
            rel="noopener noreferrer"
            className="text-[12px] text-muted hover:underline"
          >
            {t("advancedVoice.getApiKey")}
          </a>
        </div>
      </div>
      <p className="mb-2.5 text-[12px] text-muted">
        {t("advancedVoice.elevenlabsHelp")}
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
          <span className="text-[12px] font-medium text-fg">{t("advancedVoice.modelLabel")}</span>
          <input
            type="text"
            value={settings.ttsModel}
            placeholder={t("advancedVoice.modelPlaceholder")}
            spellCheck={false}
            onChange={(e) => update({ ttsModel: e.target.value })}
            className={VOICE_INPUT_CLS}
          />
        </label>
        {renderVoiceField(
          "persona",
          t("advancedVoice.personaVoiceIdLabel"),
          settings.ttsVoicePersona,
          (v) => update({ ttsVoicePersona: v }),
        )}
        {renderVoiceField(
          "scammer",
          t("advancedVoice.scammerVoiceIdLabel"),
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
  const t = useTranslations("settings");
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
      // Any failed Test reverts to the last committed voice; the reason (kept in
      // the label below) tells the user why — quota / key / voice not available.
      if (!r.ok) setDraft(value);
    } finally {
      setBusy(false);
    }
  };

  const st = red
    ? { ok: false, label: t("advancedVoice.revertHint") }
    : res
      ? describe(res)
      : null;

  return (
    <label className="grid gap-1">
      <span className="text-[12px] font-medium text-fg">{label}</span>
      <div className="flex gap-2">
        <input
          type="text"
          list={datalistId}
          value={draft}
          placeholder={t("advancedVoice.serverDefaultWithFallback", { fallback })}
          spellCheck={false}
          onChange={(e) => onChange(e.target.value)}
          onBlur={onBlur}
          className={`${VOICE_INPUT_CLS} flex-1 ${red ? "border-risk-high" : ""}`}
        />
        <button
          type="button"
          onClick={() => void test()}
          disabled={busy}
          title={t("advancedVoice.testTitleWithCheck")}
          className="h-8 shrink-0 rounded-lg border border-line bg-elevated px-2.5 text-[12px] font-semibold text-fg transition-colors hover:border-accent/40 disabled:opacity-50"
        >
          {busy ? t("advancedVoice.testBusy") : t("advancedVoice.testButton")}
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
        <span className={`text-[12px] ${st.ok ? "text-accent-bright" : "text-risk-high"}`}>
          {st.label}
        </span>
      )}
    </label>
  );
}

/* ── Advanced voice (Gemini) — per-role voice picker + "Test Gemini" ──────── */

function describeGeminiCheck(
  res: VoiceCheckResult,
  t: SettingsT,
): { ok: boolean; label: string } {
  if (res.ok) return { ok: true, label: t("voiceCheck.gemini.ready") };
  if (res.error === "no_key")
    return { ok: false, label: t("voiceCheck.gemini.noKey") };
  const s = res.status;
  if (s === 429 || res.error === "http_429")
    return { ok: false, label: t("voiceCheck.gemini.quotaExceeded") };
  if (s === 403 || res.error === "http_403")
    return { ok: false, label: t("voiceCheck.gemini.keyRejected") };
  if (s === 400 || res.error === "http_400")
    return { ok: false, label: t("voiceCheck.gemini.badVoiceName") };
  if (s === 404 || res.error === "http_404")
    return { ok: false, label: t("voiceCheck.gemini.modelUnavailable") };
  if (res.error?.startsWith("config:"))
    return { ok: false, label: t("voiceCheck.gemini.configError", { message: res.error.slice(7).trim() }) };
  if (res.error?.startsWith("http_"))
    return { ok: false, label: t("voiceCheck.gemini.httpError", { code: String(s ?? res.error) }) };
  return { ok: false, label: t("voiceCheck.gemini.unreachable") };
}

function AdvancedGemini({
  settings,
  update,
}: {
  settings: ClientSettings;
  update: (patch: Partial<ClientSettings>) => void;
}) {
  const t = useTranslations("settings");
  return (
    <div className="border-t border-line pt-3.5">
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="eyebrow">{t("advancedVoice.geminiEyebrow")}</div>
        <a
          href="https://ai.google.dev/gemini-api/docs/speech-generation"
          target="_blank"
          rel="noopener noreferrer"
          className="text-[12px] text-accent-bright hover:underline"
        >
          {t("advancedVoice.voiceDocs")}
        </a>
      </div>
      <p className="mb-2.5 text-[12px] text-muted">
        {t("advancedVoice.geminiHelp")}
      </p>

      <div className="grid gap-2.5">
        <VoiceComboField
          label={t("advancedVoice.personaVoiceLabel")}
          fallback="Sulafat"
          value={settings.geminiVoicePersona}
          onCommit={(v) => update({ geminiVoicePersona: v })}
          voices={GEMINI_VOICES}
          isKnown={isKnownGeminiVoice}
          onTest={(name) => checkGemini("persona", name)}
          describe={(r) => describeGeminiCheck(r, t)}
          datalistId="gemini-voices-persona"
        />
        <VoiceComboField
          label={t("advancedVoice.scammerVoiceLabel")}
          fallback="Charon"
          value={settings.geminiVoiceScammer}
          onCommit={(v) => update({ geminiVoiceScammer: v })}
          voices={GEMINI_VOICES}
          isKnown={isKnownGeminiVoice}
          onTest={(name) => checkGemini("scammer", name)}
          describe={(r) => describeGeminiCheck(r, t)}
          datalistId="gemini-voices-scammer"
        />
      </div>
    </div>
  );
}

/* ── Advanced voice (Google) — per-role voice picker + "Test" ────────────── */

function describeGoogleCheck(
  res: VoiceCheckResult,
  t: SettingsT,
): { ok: boolean; label: string } {
  if (res.ok) return { ok: true, label: t("voiceCheck.google.ready") };
  if (res.error === "no_key")
    return { ok: false, label: t("voiceCheck.google.noKey") };
  const s = res.status;
  if (s === 403 || res.error === "http_403")
    return { ok: false, label: t("voiceCheck.google.keyRejected") };
  if (s === 429 || res.error === "http_429")
    return { ok: false, label: t("voiceCheck.google.quotaExceeded") };
  if (s === 400 || res.error === "http_400")
    return { ok: false, label: t("voiceCheck.google.badRequest") };
  if (res.error?.startsWith("http_"))
    return { ok: false, label: t("voiceCheck.google.httpError", { code: String(s ?? res.error) }) };
  return { ok: false, label: t("voiceCheck.google.unreachable") };
}

function AdvancedGoogle({
  settings,
  update,
}: {
  settings: ClientSettings;
  update: (patch: Partial<ClientSettings>) => void;
}) {
  const t = useTranslations("settings");
  return (
    <div className="border-t border-line pt-3.5">
      <div className="mb-1 flex items-center justify-between gap-2">
        <div className="eyebrow">{t("advancedVoice.googleEyebrow")}</div>
        <a
          href="https://cloud.google.com/text-to-speech/docs/voices"
          target="_blank"
          rel="noopener noreferrer"
          className="text-[12px] text-accent-bright hover:underline"
        >
          {t("advancedVoice.voiceList")}
        </a>
      </div>
      <p className="mb-2.5 text-[12px] text-muted">
        {t("advancedVoice.googleHelp")}
      </p>

      <div className="grid gap-2.5">
        <VoiceComboField
          label={t("advancedVoice.personaVoiceLabel")}
          fallback="id-ID-Wavenet-A"
          value={settings.googleVoicePersona}
          onCommit={(v) => update({ googleVoicePersona: v })}
          voices={GOOGLE_VOICES}
          isKnown={isKnownGoogleVoice}
          onTest={(name) => checkGoogle("persona", name)}
          describe={(r) => describeGoogleCheck(r, t)}
          datalistId="google-voices-persona"
        />
        <VoiceComboField
          label={t("advancedVoice.scammerVoiceLabel")}
          fallback="id-ID-Wavenet-B"
          value={settings.googleVoiceScammer}
          onCommit={(v) => update({ googleVoiceScammer: v })}
          voices={GOOGLE_VOICES}
          isKnown={isKnownGoogleVoice}
          onTest={(name) => checkGoogle("scammer", name)}
          describe={(r) => describeGoogleCheck(r, t)}
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
      className={`rounded-md border px-2 py-0.5 font-mono text-[12px] font-bold tracking-widest ${
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
  const t = useTranslations("settings");
  if (loading && !status) {
    return (
      <div className="grid h-24 animate-pulse place-items-center text-[12px] text-muted">
        {t("backendStatus.loadingLine")}
      </div>
    );
  }
  if (!status) return null;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px] text-muted">{t("backendStatus.globalMode")}</span>
        <ModeChip mode={status.mode} />
        {status.source === "env" && (
          <span
            className="rounded-md border border-risk-med/30 bg-risk-med/10 px-1.5 py-0.5 text-[12px] text-risk-med"
            title={t("backendStatus.envFallbackTitle")}
          >
            {t("backendStatus.envFallback")}
          </span>
        )}
      </div>

      {status.modules.length > 0 && (
        <div>
          <div className="text-[12px] text-muted">{t("backendStatus.perModuleMode")}</div>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {status.modules.map((m) => (
              <span
                key={m.module}
                className="rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[12px] text-fg/80"
                title={m.adapters ? JSON.stringify(m.adapters) : undefined}
              >
                {m.module} · <ModeChip mode={m.mode} />
              </span>
            ))}
          </div>
        </div>
      )}

      <div>
        <div className="text-[12px] text-muted">{t("backendStatus.ttsProvider")}</div>
        <div className="mt-1.5 font-mono text-[12px] text-fg">
          {status.ttsProvider ?? (
            <span className="text-muted">
              {t("backendStatus.ttsProviderUnreported")}
            </span>
          )}
        </div>
      </div>

      <div>
        <div className="text-[12px] text-muted">
          {t("backendStatus.keyPresence")}{" "}
          <span className="text-muted/70">{t("backendStatus.keyPresenceHint")}</span>
        </div>
        {status.keys.length > 0 ? (
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {status.keys.map((k) => (
              <span
                key={k.provider}
                className={`rounded-md border px-2 py-0.5 font-mono text-[12px] ${
                  k.present
                    ? "border-accent/30 bg-accent/10 text-accent-bright"
                    : "border-line bg-elevated text-muted"
                }`}
              >
                {k.provider} · {k.present ? t("backendStatus.keyConfigured") : t("backendStatus.keyNotSet")}
              </span>
            ))}
          </div>
        ) : (
          <p className="mt-1 text-[12px] text-muted">
            {t("backendStatus.keysUnreported")}
          </p>
        )}
      </div>
    </div>
  );
}

/* ── Language / locale switcher ──────────────────────────────────────────── */

function LanguageCard() {
  const t = useTranslations("settings.language");
  const { locale, setLocale } = useLocale();
  const options: readonly Locale[] = ["id", "en"];
  const copy: Record<Locale, { label: string; sub: string }> = {
    id: { label: t("id.label"), sub: t("id.sub") },
    en: { label: t("en.label"), sub: t("en.sub") },
  };
  return (
    <Card title={t("cardTitle")}>
      <SegmentedControl
        legend={t("legend")}
        hint={t("hint")}
        name="locale"
        options={options}
        copy={copy}
        value={locale}
        onChange={setLocale}
      />
    </Card>
  );
}

/* ── Theme switcher — light / dark / system ──────────────────────────────── */

function ThemeCard() {
  const t = useTranslations("settings.theme");
  const { theme, setTheme } = useTheme();
  const options: readonly ThemeChoice[] = ["light", "dark", "system"];
  const copy: Record<ThemeChoice, { label: string; sub: string }> = {
    light: { label: t("light.label"), sub: t("light.sub") },
    dark: { label: t("dark.label"), sub: t("dark.sub") },
    system: { label: t("system.label"), sub: t("system.sub") },
  };
  return (
    <Card title={t("cardTitle")}>
      <SegmentedControl
        legend={t("legend")}
        hint={t("hint")}
        name="theme"
        options={options}
        copy={copy}
        value={theme}
        onChange={setTheme}
      />
    </Card>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────────── */

export default function SettingsPage() {
  const t = useTranslations("settings");
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
      <div className="mb-4 flex flex-col items-start gap-3 sm:flex-row sm:items-end sm:justify-between sm:gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">{t("title")}</h1>
          <p className="mt-2 max-w-[60ch] text-[13px] leading-relaxed text-muted">
            {t("pageLead")}
          </p>
          <p className="mt-1 max-w-[60ch] text-[12px] leading-relaxed text-muted">
            {t("subtitle")}
          </p>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          disabled={loading}
          className="h-8 flex-none rounded-lg border border-line bg-elevated px-3.5 text-[12px] font-semibold text-fg transition-colors hover:bg-fg/[.07] disabled:opacity-50"
        >
          {loading ? t("refreshing") : t("refresh")}
        </button>
      </div>

      <ThemeCard />
      <LanguageCard />

      <Card title={t("voiceCall.cardTitle")}>
        <SegmentedControl
          legend={t("voiceCall.voiceProvider.legend")}
          hint={t("voiceCall.voiceProvider.hint")}
          name="voiceProvider"
          options={VOICE_PROVIDER_SETTINGS}
          copy={voiceProviderCopy(t)}
          value={settings.voiceProvider}
          onChange={(v) => update({ voiceProvider: v })}
        />
        <SegmentedControl
          legend={t("voiceCall.callMode.legend")}
          hint={t("voiceCall.callMode.hint")}
          name="callMode"
          options={CALL_MODE_SETTINGS}
          copy={callModeCopy(t)}
          value={settings.callMode}
          onChange={(v) => update({ callMode: v })}
        />
        <SegmentedControl
          legend={t("voiceCall.sttSource.legend")}
          hint={t("voiceCall.sttSource.hint")}
          name="sttSource"
          options={STT_SOURCE_SETTINGS}
          copy={sttSourceCopy(t)}
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
          <p className="text-[12px] text-muted">
            {t("voiceCall.overridesNote")}
          </p>
          <button
            type="button"
            onClick={reset}
            className="h-8 flex-none rounded-lg border border-line bg-elevated px-3 text-[12px] font-semibold text-muted transition-colors hover:bg-fg/[.07] hover:text-fg"
          >
            {t("voiceCall.resetToDefaults")}
          </button>
        </div>
      </Card>

      <Card title={t("backendStatus.cardTitle")}>
        <BackendStatus status={status} loading={loading} />
      </Card>
    </div>
  );
}
