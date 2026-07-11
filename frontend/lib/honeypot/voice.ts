/**
 * INFILTRATE voice-call client — P4b.
 *
 * fetchVoiceCall():
 *   POST /api/sessions {channel_type:"voice"}  → RawSession (voice-framed run)
 *   GET  /api/sessions/{id}/messages           → RawMessage[] + meta voice marks
 *                                                 {speaker, duration_seconds,
 *                                                  offset_seconds}
 *   GET  /api/entities?session={id}            → RawEntity[]
 *
 * normalized into ordered `VoiceLine`s with per-line timing. Any failure —
 * backend unreachable OR no voice channel yet — falls back to the local
 * voice-framed mock transcript, mirroring lib/honeypot/api.ts, so the call
 * view always renders standalone (`● live api` vs `● offline · mock` badge).
 */

import { apiFetch } from "@/lib/http";
import {
  deriveCustody,
  entitySubtitle,
  entityValue,
  extractionLabel,
  normalizeSession,
  type RawEntity,
  type RawMessage,
  type RawSession,
  type RawSyndicate,
} from "./api";
import { buildMockVoiceCall } from "./mock";
import type { SpeakableLine } from "./tts";
import type {
  CustodyInfo,
  DataSource,
  HpEntity,
  MessageExtraction,
} from "./types";

/* ── Voice types (frontend-canonical) ──────────────────────────────────── */

/** One spoken call line — directly speakable by any `VoiceProvider`. */
export interface VoiceLine extends SpeakableLine {
  id: string;
  /** Caption byline: "Scammer" | "Honeypot · Bu Sari". */
  who: string;
  /** Seconds from call start when this line begins. */
  offsetSec: number;
  /** Inline `◇ extracted …` badges, revealed as the line is heard. */
  extractions: MessageExtraction[];
  /** Wallet/account disclosure beat — arms the analyst "Take over" control. */
  disclosure: boolean;
}

/** Panel entity + the line index at which it is "heard" on the call. */
export interface VoiceEntity extends HpEntity {
  revealAtLine: number;
}

export interface VoiceCallSession {
  id: string;
  /** Caller ID (channel_ref), e.g. "+62 812-8841-4471". */
  callerId: string;
  /** Persona display, e.g. "Bu Sari, 54". */
  persona: string;
  /** Mode tag, e.g. "POC · replay" | "LIVE". */
  modeTag: string;
  /** active | escalated | closed */
  status: string;
  lines: VoiceLine[];
  entities: VoiceEntity[];
  custody: CustodyInfo;
  /** Index of the first disclosure line (-1 = none). */
  disclosureIndex: number;
  totalDurationSec: number;
  source: DataSource;
}

/* ── Raw voice meta (MessageOut.meta for channel_type="voice") ─────────── */

export interface RawVoiceMeta {
  speaker?: string;
  duration_seconds?: number;
  offset_seconds?: number;
  disclosure?: boolean;
}

export type RawVoiceMessage = RawMessage & { meta?: RawVoiceMeta | null };

/* ── Fetch plumbing (same pattern as api.ts request) ───────────────────── */

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 8000,
): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await apiFetch(path, { ...init, signal: ctrl.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

/* ── Normalization ─────────────────────────────────────────────────────── */

/** Rough spoken-Bahasa pace (~2.3 words/s) when the backend sends no marks. */
export const estimateDurationSec = (text: string): number =>
  Math.min(20, Math.max(2.4, text.trim().split(/\s+/).length / 2.3));

export function normalizeLines(
  raw: RawVoiceMessage[],
  personaDisplay: string,
): VoiceLine[] {
  const personaFirst = personaDisplay.split(",")[0].trim();
  let runningOffset = 0;

  return [...raw]
    .sort((a, b) => a.seq - b.seq)
    .map((m): VoiceLine => {
      const metaSpeaker = m.meta?.speaker;
      const speaker =
        metaSpeaker === "scammer" || metaSpeaker === "persona"
          ? metaSpeaker
          : m.direction === "inbound"
            ? "scammer"
            : "persona";

      const durationSec =
        typeof m.meta?.duration_seconds === "number" &&
        m.meta.duration_seconds > 0
          ? m.meta.duration_seconds
          : estimateDurationSec(m.content);
      const offsetSec =
        typeof m.meta?.offset_seconds === "number"
          ? m.meta.offset_seconds
          : runningOffset;
      runningOffset = offsetSec + durationSec;

      const entities = m.entities ?? [];
      return {
        id: m.id,
        seq: m.seq,
        speaker,
        who: speaker === "scammer" ? "Scammer" : `Honeypot · ${personaFirst}`,
        text: m.content,
        durationSec,
        offsetSec,
        extractions: entities.map((e) => ({
          label: extractionLabel(e),
          confidence: Math.max(0, Math.min(1, e.confidence)),
        })),
        disclosure:
          m.meta?.disclosure === true ||
          entities.some((e) => e.type === "crypto_wallet"),
      };
    });
}

export function normalizeVoiceEntities(
  raw: RawEntity[],
  lines: VoiceLine[],
): VoiceEntity[] {
  const lineIndexByMessageId = new Map<string, number>(
    lines.map((l, i) => [l.id, i]),
  );
  return raw
    .filter(
      (e) => e.review_status !== "rejected" && e.review_status !== "poisoned",
    )
    .map(
      (e): VoiceEntity => ({
        id: e.id,
        type: e.type,
        value: entityValue(e),
        subtitle: entitySubtitle(e),
        confidence: Math.max(0, Math.min(1, e.confidence)),
        reviewStatus: e.review_status,
        revealAtLine: e.message_id
          ? (lineIndexByMessageId.get(e.message_id) ?? 0)
          : 0,
      }),
    );
}

/** First wallet-disclosure line; first extraction line as fallback. */
function findDisclosureIndex(lines: VoiceLine[]): number {
  const wallet = lines.findIndex((l) => l.disclosure);
  if (wallet >= 0) return wallet;
  return lines.findIndex((l) => l.extractions.length > 0);
}

/* ── Public surface ────────────────────────────────────────────────────── */

/**
 * Start a voice honeypot session on demand and load the full call payload.
 * Falls back to the mock voice call when the API is unreachable or the
 * backend has no voice channel yet.
 */
export async function fetchVoiceCall(): Promise<VoiceCallSession> {
  try {
    // POST runs the whole scripted agent loop server-side — allow it time.
    const raw = await request<RawSession>(
      "/sessions",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel_type: "voice" }),
      },
      20000,
    );
    if (raw.channel_type !== "voice")
      throw new Error("backend has no voice channel yet");

    const [messagesRaw, entitiesRaw, syndicates] = await Promise.all([
      request<RawVoiceMessage[]>(
        `/sessions/${encodeURIComponent(raw.id)}/messages`,
      ),
      request<RawEntity[]>(
        `/entities?session=${encodeURIComponent(raw.id)}`,
      ).catch(() => null),
      raw.syndicate_id
        ? request<RawSyndicate[]>("/syndicates").catch(
            () => [] as RawSyndicate[],
          )
        : Promise.resolve([] as RawSyndicate[]),
    ]);
    if (!messagesRaw.length) throw new Error("empty voice transcript");

    const session = normalizeSession(raw);
    const lines = normalizeLines(messagesRaw, session.persona);
    const entities = normalizeVoiceEntities(
      entitiesRaw ?? messagesRaw.flatMap((m) => m.entities ?? []),
      lines,
    );
    const syndicateLabel =
      syndicates.find((s) => s.id === raw.syndicate_id)?.label ?? null;
    const last = lines[lines.length - 1];

    return {
      id: raw.id,
      callerId: raw.channel_ref ?? "+62 ··· unknown caller",
      persona: session.persona,
      modeTag: session.modeTag,
      status: session.status,
      lines,
      entities,
      custody: deriveCustody(raw, messagesRaw, syndicateLabel),
      disclosureIndex: findDisclosureIndex(lines),
      totalDurationSec: Math.round(last.offsetSec + last.durationSec),
      source: "api",
    };
  } catch {
    return buildMockVoiceCall();
  }
}
