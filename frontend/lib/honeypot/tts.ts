/**
 * Voice playback engine — the `VoiceProvider` abstraction (P4b).
 *
 * The call view depends on this INTERFACE only, never on `speechSynthesis`
 * directly, so upgrading from the free browser voice to a paid natural one
 * (Google / Higgsfield / ElevenLabs served by the backend) is an env flip +
 * one provider implementation — the captions/sync/UI are untouched:
 *
 *   NEXT_PUBLIC_VOICE_PROVIDER=browser  → BrowserTTSProvider (Web Speech API)
 *   NEXT_PUBLIC_VOICE_PROVIDER=backend  → BackendAudioProvider
 *                                          (GET /api/sessions/{id}/audio/{seq})
 *
 * Browsers require a user gesture before audio — the call view's "Start call"
 * button provides it.
 */

import { API_BASE, apiFetch } from "@/lib/http";

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
export class BackendAudioProvider implements VoiceProvider {
  readonly name = "backend";
  private timer = new LineTimer();
  private audio: HTMLAudioElement | null = null;

  constructor(private readonly sessionId: string) {}

  async speak(line: SpeakableLine): Promise<void> {
    let durationSec = line.durationSec;
    try {
      const res = await apiFetch(
        `/sessions/${encodeURIComponent(this.sessionId)}/audio/${line.seq}`,
      );
      const type = res.headers.get("content-type") ?? "";
      if (res.ok && res.status !== 204) {
        if (type.startsWith("audio/")) {
          // Provider streams raw audio bytes.
          const blob = await res.blob();
          await this.play(URL.createObjectURL(blob));
          return;
        }
        if (type.includes("json")) {
          const marks = (await res.json()) as VoiceMarks;
          if (marks.audio_url) {
            // LIVE: marks point at the synthesized audio.
            const url = /^https?:\/\//.test(marks.audio_url)
              ? marks.audio_url
              : `${API_BASE}${marks.audio_url}`;
            await this.play(url);
            return;
          }
          if (marks.duration_seconds > 0) durationSec = marks.duration_seconds;
        }
      }
    } catch {
      /* backend unreachable — fall through to the timer */
    }
    // POC: no audio bytes yet → keep the call timeline via duration marks.
    await this.timer.run(durationSec * 1000);
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
    this.timer.pause();
  }

  resume(): void {
    void this.audio?.play().catch(() => undefined);
    this.timer.resume();
  }

  cancel(): void {
    if (this.audio) {
      const audio = this.audio;
      audio.onended?.(new Event("ended")); // resolve the in-flight speak()
      audio.pause();
      audio.src = "";
      this.audio = null;
    }
    this.timer.cancel();
  }
}

/* ── Provider selection (env-driven — the swap point) ───────────────────── */

export type VoiceProviderKind = "browser" | "backend";

/** Which provider the build is configured for (badge/debug display). */
export function voiceProviderKind(): VoiceProviderKind {
  return (process.env.NEXT_PUBLIC_VOICE_PROVIDER ?? "browser").toLowerCase() ===
    "backend"
    ? "backend"
    : "browser";
}

/**
 * Create the configured VoiceProvider for a session.
 * Default `browser` (free Web Speech API); `backend` streams provider audio
 * from `GET /api/sessions/{id}/audio/{seq}` (LIVE Google/Higgsfield/ElevenLabs).
 */
export function createVoiceProvider(sessionId: string): VoiceProvider {
  return voiceProviderKind() === "backend"
    ? new BackendAudioProvider(sessionId)
    : new BrowserTTSProvider();
}
