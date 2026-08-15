/**
 * Voice playback engine — the `VoiceProvider` abstraction (P4b).
 *
 * The call view depends on this INTERFACE only, never on `speechSynthesis`
 * directly, so upgrading from the free browser voice to a paid natural one
 * (Google / Higgsfield / ElevenLabs served by the backend) is a settings flip +
 * one provider implementation — the captions/sync/UI are untouched.
 *
 * Provider selection (Control Panel `voiceProvider`, localStorage override of
 * the NEXT_PUBLIC_VOICE_PROVIDER build default — lib/settings.ts):
 *
 *   browser            → BrowserTTSProvider (free Web Speech API)
 *   elevenlabs|google  → BackendAudioProvider
 *                         (GET /api/sessions/{id}/audio/{seq} — real audio
 *                          when the backend TTS adapter is LIVE; degrades to
 *                          the duration-timer path on poc voice-marks)
 *
 * Browsers require a user gesture before audio — the call view's "Start call"
 * button provides it.
 */

import { API_BASE, apiFetch } from "@/lib/http";
import { getSettings, type VoiceProviderSetting } from "@/lib/settings";

/* ── Contract ──────────────────────────────────────────────────────────── */

export type VoiceSpeaker = "scammer" | "persona";

/** The minimum a provider needs to voice one call line. */
export interface SpeakableLine {
  /** Backend message seq — keys `GET /sessions/{id}/audio/{seq}` (LIVE). */
  seq: number;
  speaker: VoiceSpeaker;
  text: string;
  /** Backend-estimated spoken duration — drives the timer fallback. */
  durationSec: number;
}

export interface VoiceProvider {
  readonly name: string;
  /** The provider that actually voiced the most recent `speak()` —
   * "elevenlabs" | "gemini" | "google" | "browser". Lets the UI show whether a
   * line was the real provider voice or the browser fallback. */
  readonly lastProvider: string;
  /** Speak one line; resolves when the line has finished playing. */
  speak(line: SpeakableLine): Promise<void>;
  pause(): void;
  resume(): void;
  /** Stop playback immediately; any in-flight speak() resolves. */
  cancel(): void;
}

/* ── Pausable line timer (fallback when no real audio is available) ─────── */

class LineTimer {
  private timer: ReturnType<typeof setTimeout> | null = null;
  private resolveFn: (() => void) | null = null;
  private remainingMs = 0;
  private startedAt = 0;

  run(ms: number): Promise<void> {
    this.cancel(); // resolve any previous line first
    return new Promise<void>((resolve) => {
      this.resolveFn = resolve;
      this.remainingMs = Math.max(250, ms);
      this.arm();
    });
  }

  private arm(): void {
    this.startedAt = Date.now();
    this.timer = setTimeout(() => this.finish(), this.remainingMs);
  }

  private finish(): void {
    if (this.timer) clearTimeout(this.timer);
    this.timer = null;
    const resolve = this.resolveFn;
    this.resolveFn = null;
    resolve?.();
  }

  pause(): void {
    if (!this.timer) return;
    clearTimeout(this.timer);
    this.timer = null;
    this.remainingMs = Math.max(0, this.remainingMs - (Date.now() - this.startedAt));
  }

  resume(): void {
    if (this.timer || !this.resolveFn) return;
    this.arm();
  }

  cancel(): void {
    this.finish();
  }
}

/* ── BrowserTTSProvider — Web Speech API (POC, free, offline) ───────────── */

/**
 * Speaks lines with `window.speechSynthesis`: distinct scammer vs persona
 * voices via pitch/rate, `id-ID` voice when installed (default otherwise).
 * Resolves on the utterance `onend`; falls back to a duration timer when
 * speechSynthesis is unavailable, plus a generous safety timeout so a
 * never-firing `onend` (headless/voiceless engines) can't hang the call.
 */
export class BrowserTTSProvider implements VoiceProvider {
  readonly name = "browser";
  readonly lastProvider = "browser"; // always speaks via the browser
  private timer = new LineTimer();
  private pending: (() => void) | null = null;
  private usingSynth = false;

  constructor() {
    // Prime the voice list — many engines return [] until `voiceschanged`.
    const synth = this.synth;
    if (synth) {
      synth.getVoices();
      synth.onvoiceschanged = () => synth.getVoices();
    }
  }

  private get synth(): SpeechSynthesis | null {
    return typeof window !== "undefined" && "speechSynthesis" in window
      ? window.speechSynthesis
      : null;
  }

  private pickVoice(): SpeechSynthesisVoice | null {
    const voices = this.synth?.getVoices() ?? [];
    return (
      voices.find((v) => v.lang?.toLowerCase().startsWith("id")) ??
      voices.find((v) => v.default) ??
      voices[0] ??
      null
    );
  }

  speak(line: SpeakableLine): Promise<void> {
    const synth = this.synth;
    if (!synth || typeof SpeechSynthesisUtterance === "undefined") {
      // No Web Speech API → honor the backend's per-line timing instead.
      this.usingSynth = false;
      return this.timer.run(line.durationSec * 1000);
    }

    this.usingSynth = true;
    return new Promise<void>((resolve) => {
      const utterance = new SpeechSynthesisUtterance(line.text);
      const voice = this.pickVoice();
      if (voice) utterance.voice = voice;
      utterance.lang = voice?.lang ?? "id-ID";
      // Distinct voices from one engine: scammer low & pushy, persona higher & slower.
      if (line.speaker === "scammer") {
        utterance.pitch = 0.7;
        utterance.rate = 1.04;
      } else {
        utterance.pitch = 1.25;
        utterance.rate = 0.94;
      }

      let done = false;
      const safety = setTimeout(
        () => finish(),
        (line.durationSec * 3 + 5) * 1000,
      );
      const finish = () => {
        if (done) return;
        done = true;
        clearTimeout(safety);
        this.pending = null;
        resolve();
      };
      this.pending = finish;
      utterance.onend = finish;
      utterance.onerror = finish;
      synth.speak(utterance);
    });
  }

  pause(): void {
    if (this.usingSynth) this.synth?.pause();
    else this.timer.pause();
  }

  resume(): void {
    if (this.usingSynth) this.synth?.resume();
    else this.timer.resume();
  }

  cancel(): void {
    this.timer.cancel();
    const pending = this.pending;
    this.pending = null;
    this.synth?.cancel();
    pending?.();
  }
}

/* ── BackendAudioProvider — LIVE path stub (Google/Higgsfield/ElevenLabs) ── */

/** `GET /sessions/{id}/audio/{seq}` payload (backend `VoiceMarkOut`). */
interface VoiceMarks {
  session_id: string;
  seq: number;
  speaker: string;
  text: string;
  duration_seconds: number;
  offset_seconds: number;
  /** LIVE providers return the synthesized audio location; POC → null. */
  audio_url: string | null;
  provider: string;
}

/**
 * Plays real synthesized audio served by the backend `TTSAdapter`:
 * `GET /api/sessions/{id}/audio/{seq}`. Handles all three response shapes —
 * raw `audio/*` bytes, JSON voice marks with an `audio_url` (LIVE
 * Google/Higgsfield/ElevenLabs), and POC marks with `audio_url: null` (no
 * real audio yet → per-line duration timer). So the env flip is safe today
 * and simply starts playing real audio the moment a LIVE TTS adapter is
 * configured server-side.
 */
/** Per-request voice config overrides (Control Panel "Advanced voice"). */
export interface VoiceOverrides {
  model?: string;
  voicePersona?: string;
  voiceScammer?: string;
}

export class BackendAudioProvider implements VoiceProvider {
  readonly name = "backend";
  // The provider that voiced the most recent line — set per outcome in speak().
  lastProvider = "browser";
  private audio: HTMLAudioElement | null = null;
  // Speaks any line the backend can't voice (POC marks, or a LIVE provider that
  // failed / has no key) so the call is NEVER silent — this is the fallback.
  private readonly fallback = new BrowserTTSProvider();
  private usingFallback = false;

  constructor(
    private readonly sessionId: string,
    private readonly provider?: string,
    private readonly overrides?: VoiceOverrides,
  ) {}

  async speak(line: SpeakableLine): Promise<void> {
    this.usingFallback = false;
    try {
      // ?provider (+ optional model/voice overrides) lets the backend A/B the
      // real voice per request (no restart), so Control Panel changes take
      // effect on the next line.
      const params = new URLSearchParams();
      if (this.provider) params.set("provider", this.provider);
      if (this.overrides?.model) params.set("model", this.overrides.model);
      if (this.overrides?.voicePersona)
        params.set("voice_persona", this.overrides.voicePersona);
      if (this.overrides?.voiceScammer)
        params.set("voice_scammer", this.overrides.voiceScammer);
      const qs = params.toString();
      const q = qs ? `?${qs}` : "";
      const res = await apiFetch(
        `/sessions/${encodeURIComponent(this.sessionId)}/audio/${line.seq}${q}`,
      );
      const type = res.headers.get("content-type") ?? "";
      if (res.ok && res.status !== 204) {
        if (type.startsWith("audio/")) {
          // Provider streams raw audio bytes.
          this.lastProvider =
            res.headers.get("x-tts-provider") || this.provider || "backend";
          const blob = await res.blob();
          await this.play(URL.createObjectURL(blob));
          return;
        }
        if (type.includes("json")) {
          const marks = (await res.json()) as VoiceMarks;
          if (marks.audio_url) {
            // LIVE: marks point at the synthesized audio.
            this.lastProvider = marks.provider || "backend";
            const url = /^https?:\/\//.test(marks.audio_url)
              ? marks.audio_url
              : `${API_BASE}${marks.audio_url}`;
            await this.play(url);
            return;
          }
        }
      }
    } catch {
      /* backend unreachable — fall through to browser speech below */
    }
    // No backend audio (POC marks, a failed/unkeyed LIVE provider, or 204) →
    // SPEAK via the browser so the line is never silent.
    this.usingFallback = true;
    this.lastProvider = "browser";
    await this.fallback.speak(line);
  }

  private play(url: string): Promise<void> {
    return new Promise<void>((resolve) => {
      const audio = new Audio(url);
      this.audio = audio;
      let done = false;
      const finish = () => {
        if (done) return;
        done = true;
        URL.revokeObjectURL(url);
        if (this.audio === audio) this.audio = null;
        resolve();
      };
      audio.onended = finish;
      audio.onerror = finish;
      void audio.play().catch(finish);
    });
  }

  pause(): void {
    this.audio?.pause();
    if (this.usingFallback) this.fallback.pause();
  }

  resume(): void {
    void this.audio?.play().catch(() => undefined);
    if (this.usingFallback) this.fallback.resume();
  }

  cancel(): void {
    if (this.audio) {
      const audio = this.audio;
      audio.onended?.(new Event("ended")); // resolve the in-flight speak()
      audio.pause();
      audio.src = "";
      this.audio = null;
    }
    if (this.usingFallback) this.fallback.cancel();
  }
}

/* ── Provider selection (settings-driven — the swap point) ──────────────── */

export type VoiceProviderKind = "browser" | "backend";

/** The analyst's Control Panel choice (localStorage over env default). */
export function voiceProviderSetting(): VoiceProviderSetting {
  return getSettings().voiceProvider;
}

/** Which playback path is active (badge/debug display). */
export function voiceProviderKind(): VoiceProviderKind {
  return voiceProviderSetting() === "browser" ? "browser" : "backend";
}

/**
 * Create the configured VoiceProvider for a session — read at call start so
 * a Control Panel change applies to the next call, no rebuild needed.
 * `browser` → free Web Speech API; `elevenlabs`/`google` → backend-served
 * audio from `GET /api/sessions/{id}/audio/{seq}` (which itself degrades to
 * duration-timer voice-marks while the server adapter is still poc).
 */
export function createVoiceProvider(sessionId: string): VoiceProvider {
  if (voiceProviderKind() !== "backend") return new BrowserTTSProvider();
  const s = getSettings();
  const provider = voiceProviderSetting();
  // `model` + the voice IDs are ElevenLabs-specific settings in the Control
  // Panel. Only forward them when ElevenLabs is the selected provider — sending
  // an ElevenLabs model id (e.g. "eleven_flash_v2_5") to Gemini/Google is
  // meaningless (Gemini's model comes from ITTU_GEMINI_TTS_MODEL; Google has no
  // model param) and just produces noisy "ignoring override" backend logs.
  const elevenlabs = provider === "elevenlabs";
  return new BackendAudioProvider(sessionId, provider, {
    model: elevenlabs ? s.ttsModel : undefined,
    voicePersona: elevenlabs ? s.ttsVoicePersona : undefined,
    voiceScammer: elevenlabs ? s.ttsVoiceScammer : undefined,
  });
}
