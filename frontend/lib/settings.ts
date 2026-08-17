"use client";

/**
 * Control Panel — client-side settings (localStorage) + backend config status.
 *
 * Settings are ANALYST-LOCAL (persisted to `ittu.settings`) and OVERRIDE the
 * NEXT_PUBLIC_* build defaults; secrets never live here — API keys stay
 * server-side and GET /api/config only exposes *presence* booleans:
 *
 *   voiceProvider  browser | elevenlabs | gemini | google
 *                    browser        → BrowserTTSProvider (free Web Speech API)
 *                    elevenlabs/gemini/google → BackendAudioProvider
 *                                     (GET /api/sessions/{id}/audio/{seq})
 *   callMode       scripted | live-mic
 *                    scripted → P4b replay (agent loop pre-run server-side)
 *                    live-mic → Tier-B interactive call (operator plays the
 *                               scammer over the mic — docs/Live-Voice-Calls.md)
 *   sttSource      web-speech (only source today — browser SpeechRecognition)
 *
 * `useSettings()` is the reactive read/write hook (Control Panel UI);
 * `getSettings()` is the plain read used by lib/honeypot/tts.ts + the call
 * view at speak-time. Changes broadcast via a window event so every mounted
 * consumer stays in sync (and across tabs via `storage`).
 */

import { useSyncExternalStore } from "react";
import { apiFetch } from "@/lib/http";
import { asMode, normalizeModules } from "@/lib/auth/api";
import type { Mode, ModuleMode } from "@/lib/auth/types";

/* ── Settings shape ────────────────────────────────────────────────────── */

export const VOICE_PROVIDER_SETTINGS = [
  "browser",
  "elevenlabs",
  "gemini",
  "google",
] as const;
export type VoiceProviderSetting = (typeof VOICE_PROVIDER_SETTINGS)[number];

export const CALL_MODE_SETTINGS = ["scripted", "live-mic"] as const;
export type CallModeSetting = (typeof CALL_MODE_SETTINGS)[number];

export const STT_SOURCE_SETTINGS = ["web-speech"] as const;
export type SttSourceSetting = (typeof STT_SOURCE_SETTINGS)[number];

export interface ClientSettings {
  voiceProvider: VoiceProviderSetting;
  callMode: CallModeSetting;
  sttSource: SttSourceSetting;
  // Advanced voice (ElevenLabs) — per-operator overrides passed to the backend
  // per request; "" = use the server default (env). No restart needed.
  ttsModel: string;
  ttsVoicePersona: string;
  ttsVoiceScammer: string;
  // Advanced voice (Gemini) — per-role prebuilt voice name (e.g. Sulafat,
  // Charon). "" = use the server default. Sent only when provider is gemini.
  geminiVoicePersona: string;
  geminiVoiceScammer: string;
  // Advanced voice (Google) — per-role id-ID voice (e.g. id-ID-Wavenet-A).
  // "" = use the server default. Sent only when provider is google.
  googleVoicePersona: string;
  googleVoiceScammer: string;
}

const STORAGE_KEY = "ittu.settings";
/** Fired on window whenever settings change (same tab). */
export const SETTINGS_EVENT = "ittu:settings-changed";

const isVoiceProvider = (v: unknown): v is VoiceProviderSetting =>
  VOICE_PROVIDER_SETTINGS.includes(v as VoiceProviderSetting);
const isCallMode = (v: unknown): v is CallModeSetting =>
  CALL_MODE_SETTINGS.includes(v as CallModeSetting);

/** Build-time defaults — what a fresh browser (no localStorage) gets. */
export function envDefaults(): ClientSettings {
  const rawProvider = (
    process.env.NEXT_PUBLIC_VOICE_PROVIDER ?? "browser"
  ).toLowerCase();
  const voiceProvider: VoiceProviderSetting = isVoiceProvider(rawProvider)
    ? rawProvider
    : rawProvider === "backend"
      ? "elevenlabs" // legacy env value — any non-browser routes to backend audio
      : "browser";
  const rawMode = (process.env.NEXT_PUBLIC_CALL_MODE ?? "scripted").toLowerCase();
  return {
    voiceProvider,
    callMode: isCallMode(rawMode) ? rawMode : "scripted",
    sttSource: "web-speech",
    ttsModel: "",
    ttsVoicePersona: "",
    ttsVoiceScammer: "",
    geminiVoicePersona: "",
    geminiVoiceScammer: "",
    googleVoicePersona: "",
    googleVoiceScammer: "",
  };
}

/** Stable server snapshot for useSyncExternalStore (SSR render). */
const SERVER_DEFAULTS: ClientSettings = envDefaults();

/* ── Store (localStorage + window events) ──────────────────────────────── */

let cache: ClientSettings | null = null;

function readStored(): Partial<ClientSettings> {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return {};
    const parsed: unknown = JSON.parse(raw);
    return parsed && typeof parsed === "object"
      ? (parsed as Partial<ClientSettings>)
      : {};
  } catch {
    return {}; // storage unavailable / corrupted JSON → env defaults
  }
}

/** Current effective settings: localStorage overrides NEXT_PUBLIC defaults. */
export function getSettings(): ClientSettings {
  if (typeof window === "undefined") return SERVER_DEFAULTS;
  if (!cache) {
    const d = envDefaults();
    const s = readStored();
    cache = {
      voiceProvider: isVoiceProvider(s.voiceProvider)
        ? s.voiceProvider
        : d.voiceProvider,
      callMode: isCallMode(s.callMode) ? s.callMode : d.callMode,
      sttSource: "web-speech",
      ttsModel: typeof s.ttsModel === "string" ? s.ttsModel : d.ttsModel,
      ttsVoicePersona:
        typeof s.ttsVoicePersona === "string" ? s.ttsVoicePersona : d.ttsVoicePersona,
      ttsVoiceScammer:
        typeof s.ttsVoiceScammer === "string" ? s.ttsVoiceScammer : d.ttsVoiceScammer,
      geminiVoicePersona:
        typeof s.geminiVoicePersona === "string"
          ? s.geminiVoicePersona
          : d.geminiVoicePersona,
      geminiVoiceScammer:
        typeof s.geminiVoiceScammer === "string"
          ? s.geminiVoiceScammer
          : d.geminiVoiceScammer,
      googleVoicePersona:
        typeof s.googleVoicePersona === "string"
          ? s.googleVoicePersona
          : d.googleVoicePersona,
      googleVoiceScammer:
        typeof s.googleVoiceScammer === "string"
          ? s.googleVoiceScammer
          : d.googleVoiceScammer,
    };
  }
  return cache;
}

function broadcast(): void {
  cache = null;
  window.dispatchEvent(new CustomEvent(SETTINGS_EVENT));
}

export function updateSettings(patch: Partial<ClientSettings>): void {
  if (typeof window === "undefined") return;
  const next = { ...getSettings(), ...patch };
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  } catch {
    cache = next; // storage unavailable (private mode) — in-memory only
    window.dispatchEvent(new CustomEvent(SETTINGS_EVENT));
    return;
  }
  broadcast();
}

export function resetSettings(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(STORAGE_KEY);
  } catch {
    /* ignore */
  }
  broadcast();
}

function subscribe(onChange: () => void): () => void {
  const bump = () => {
    cache = null;
    onChange();
  };
  const onStorage = (e: StorageEvent) => {
    if (!e.key || e.key === STORAGE_KEY) bump();
  };
  window.addEventListener(SETTINGS_EVENT, bump);
  window.addEventListener("storage", onStorage);
  return () => {
    window.removeEventListener(SETTINGS_EVENT, bump);
    window.removeEventListener("storage", onStorage);
  };
}

/** Reactive settings hook — re-renders on any change (this tab or another). */
export function useSettings(): {
  settings: ClientSettings;
  update: (patch: Partial<ClientSettings>) => void;
  reset: () => void;
} {
  const settings = useSyncExternalStore(
    subscribe,
    getSettings,
    () => SERVER_DEFAULTS,
  );
  return { settings, update: updateSettings, reset: resetSettings };
}

/* ── Backend config status (READ-ONLY panel — GET /api/config) ─────────── */

export interface BackendKeyPresence {
  /** Provider slug, e.g. "elevenlabs" | "google". */
  provider: string;
  /** True when the key is configured SERVER-SIDE (value never exposed). */
  present: boolean;
}

export interface BackendConfigStatus {
  mode: Mode;
  modules: ModuleMode[];
  /** Effective server TTS provider (ITTU_TTS_PROVIDER), null if unknown. */
  ttsProvider: string | null;
  keys: BackendKeyPresence[];
  /**
   * Whether starting a campaign actually hands its numbers to the dialer.
   * Needs BOTH `ITTU_DIAL_ENQUEUE_ON_START` and Postgres persistence; either
   * missing makes Start a pure status flip. Both fail SILENTLY server-side
   * (the flag is read at boot; enqueue errors are logged, not raised), so the
   * UI has to be told rather than infer it. `null` = the API didn't say.
   */
  dialingEnabled: boolean | null;
  source: "api" | "env";
}

/* eslint-disable @typescript-eslint/no-explicit-any */
const first = (...vals: unknown[]): any =>
  vals.find((v) => v !== undefined && v !== null);

/**
 * Key presence, defensively: accepts a `{elevenlabs: true}`-style dict under
 * several names AND any top-level `*_key_present` / `*_key` boolean —
 * whatever the backend ships, only booleans ever reach the browser.
 */
function normalizeKeys(c: any): BackendKeyPresence[] {
  const found = new Map<string, boolean>();
  const put = (name: string, present: unknown) => {
    const provider = name
      .toLowerCase()
      .replace(/_?(api_?key|key)(_present|_configured|_set)?$/, "")
      .replace(/_+$/, "");
    if (provider) found.set(provider, Boolean(present));
  };
  const dict = [c?.live_keys, c?.keys, c?.key_present, c?.tts_keys].find(
    (v) => v && typeof v === "object" && !Array.isArray(v),
  );
  if (dict)
    for (const [k, v] of Object.entries(dict))
      if (typeof v === "boolean") put(k, v);
  for (const [k, v] of Object.entries(c ?? {}))
    if (typeof v === "boolean" && /key(_present|_configured|_set)?$/.test(k))
      put(k, v);
  return [...found].map(([provider, present]) => ({ provider, present }));
}

/**
 * GET /api/config for the Control Panel's read-only backend section — the
 * richer sibling of lib/auth/api.ts fetchConfig() (which feeds the shell
 * badge): also surfaces tts_provider + live-key presence. Falls back to
 * NEXT_PUBLIC_ITTU_MODE (source: "env") when the backend is unreachable.
 */
export async function fetchBackendConfig(): Promise<BackendConfigStatus> {
  try {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 5000);
    let raw: any;
    try {
      const res = await apiFetch("/config", { signal: ctrl.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      raw = await res.json();
    } finally {
      clearTimeout(timer);
    }
    const c = first(raw?.config, raw?.data, raw) ?? {};
    const modules = normalizeModules(c);
    return {
      mode: asMode(
        first(
          c?.mode,
          c?.effective_mode,
          c?.global_mode,
          c?.data_mode,
          modules.some((m) => m.mode === "LIVE") ? "live" : "poc",
        ),
      ),
      modules,
      ttsProvider:
        first(c?.tts_provider, c?.voice?.tts_provider, c?.adapters?.tts) !=
        null
          ? String(first(c?.tts_provider, c?.voice?.tts_provider, c?.adapters?.tts))
          : null,
      keys: normalizeKeys(c),
      dialingEnabled:
        typeof c?.dialing?.enabled === "boolean" ? c.dialing.enabled : null,
      source: "api",
    };
  } catch {
    return {
      mode: asMode(process.env.NEXT_PUBLIC_ITTU_MODE ?? "poc"),
      modules: [],
      ttsProvider: null,
      keys: [],
      dialingEnabled: null,
      source: "env",
    };
  }
}
