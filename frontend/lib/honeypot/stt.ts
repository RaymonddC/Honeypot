/**
 * Operator-mic STT — browser Web Speech API `SpeechRecognition` wrapper
 * (Tier-B live call, docs/Live-Voice-Calls.md). The OPERATOR plays the
 * scammer: mic → live id-ID transcript → POST /sessions/{id}/turn.
 *
 * Mirrors the backend STTAdapter boundary: the call view depends on this
 * wrapper only, so a streaming Whisper (or any other) source later is a
 * drop-in. Handles the real-world quirks:
 *   - Chrome-only API (`webkitSpeechRecognition`) — `sttSupported()` gates the
 *     UI; Safari/Firefox get a notice + text-input fallback.
 *   - Chrome auto-stops after silence → transparent restart while running.
 *   - `onSpeechStart` fires the moment the operator is heard → barge-in
 *     (cancel persona TTS mid-line).
 *   - permission-denied surfaces as a distinct error kind.
 */

/* ── Minimal typings (SpeechRecognition is absent from lib.dom) ─────────── */

interface SpeechRecognitionAlternativeLike {
  transcript: string;
  confidence: number;
}

interface SpeechRecognitionResultLike {
  isFinal: boolean;
  readonly length: number;
  [index: number]: SpeechRecognitionAlternativeLike;
}

interface SpeechRecognitionEventLike {
  resultIndex: number;
  results: {
    readonly length: number;
    [index: number]: SpeechRecognitionResultLike;
  };
}

interface SpeechRecognitionErrorEventLike {
  error: string;
  message?: string;
}

interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  onresult: ((e: SpeechRecognitionEventLike) => void) | null;
  onerror: ((e: SpeechRecognitionErrorEventLike) => void) | null;
  onend: (() => void) | null;
  onspeechstart: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}

type SpeechRecognitionCtor = new () => SpeechRecognitionLike;

function speechRecognitionCtor(): SpeechRecognitionCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as Record<string, unknown>;
  return (w.SpeechRecognition ??
    w.webkitSpeechRecognition ??
    null) as SpeechRecognitionCtor | null;
}

/** False on Safari/Firefox → the call view shows the text-input fallback. */
export const sttSupported = (): boolean => speechRecognitionCtor() != null;

/* ── Transcriber ───────────────────────────────────────────────────────── */

export type SttErrorKind =
  | "unsupported"
  | "permission"
  | "network"
  | "audio"
  | "other";

export interface MicTranscriberOptions {
  /** BCP-47 recognition language — default "id-ID". */
  lang?: string;
  /** Rolling not-yet-final transcript ("" when it clears). */
  onInterim: (text: string) => void;
  /** A finalized utterance — one operator turn. */
  onFinal: (text: string) => void;
  /** Operator heard → barge-in hook (may fire repeatedly while talking). */
  onSpeechStart?: () => void;
  onError?: (kind: SttErrorKind, message: string) => void;
  onListeningChange?: (listening: boolean) => void;
}

export class MicTranscriber {
  private rec: SpeechRecognitionLike | null = null;
  private running = false;
  private restartTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly opts: MicTranscriberOptions) {}

  get listening(): boolean {
    return this.running;
  }

  /** Begin continuous recognition. Returns false when unsupported. */
  start(): boolean {
    const Ctor = speechRecognitionCtor();
    if (!Ctor) {
      this.opts.onError?.(
        "unsupported",
        "SpeechRecognition is not available in this browser",
      );
      return false;
    }
    if (this.running) return true;
    this.running = true;
    this.spin(Ctor);
    this.opts.onListeningChange?.(true);
    return true;
  }

  stop(): void {
    this.running = false;
    if (this.restartTimer) {
      clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    const rec = this.rec;
    this.rec = null;
    try {
      rec?.abort();
    } catch {
      /* already stopped */
    }
    this.opts.onListeningChange?.(false);
  }

  private spin(Ctor: SpeechRecognitionCtor): void {
    const rec = new Ctor();
    this.rec = rec;
    rec.lang = this.opts.lang ?? "id-ID";
    rec.continuous = true;
    rec.interimResults = true;
    rec.maxAlternatives = 1;

    rec.onspeechstart = () => this.opts.onSpeechStart?.();

    rec.onresult = (e) => {
      let interim = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const result = e.results[i];
        const text = result[0]?.transcript ?? "";
        if (result.isFinal) {
          const clean = text.trim();
          if (clean) {
            this.opts.onInterim("");
            this.opts.onFinal(clean);
          }
        } else {
          interim += text;
        }
      }
      const rolling = interim.trim();
      if (rolling) {
        // Some engines skip onspeechstart — first interim is the barge-in cue.
        this.opts.onSpeechStart?.();
        this.opts.onInterim(rolling);
      }
    };

    rec.onerror = (e) => {
      const kind: SttErrorKind =
        e.error === "not-allowed" || e.error === "service-not-allowed"
          ? "permission"
          : e.error === "network"
            ? "network"
            : e.error === "audio-capture"
              ? "audio"
              : "other";
      if (kind === "permission" || kind === "audio") {
        // Unrecoverable — stop the restart loop, surface to the UI.
        this.running = false;
        this.opts.onListeningChange?.(false);
        this.opts.onError?.(kind, e.message ?? e.error);
      } else if (e.error !== "no-speech" && e.error !== "aborted") {
        // no-speech/aborted are routine (silence, our own abort) — skip.
        this.opts.onError?.(kind, e.message ?? e.error);
      }
    };

    rec.onend = () => {
      if (this.rec !== rec) return; // superseded by stop()/restart
      this.rec = null;
      if (!this.running) {
        this.opts.onListeningChange?.(false);
        return;
      }
      // Chrome ends recognition after ~seconds of silence — keep the mic hot.
      this.restartTimer = setTimeout(() => {
        this.restartTimer = null;
        const C = speechRecognitionCtor();
        if (this.running && C) this.spin(C);
      }, 250);
    };

    try {
      rec.start();
    } catch {
      /* "already started" race — the onend restart path recovers */
    }
  }
}
