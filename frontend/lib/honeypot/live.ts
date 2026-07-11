/**
 * Tier-B live-mic call client (docs/Live-Voice-Calls.md · "fully free, no
 * telephony"). The OPERATOR plays the scammer over the mic; the AI persona
 * answers in voice — same agent loop in the middle:
 *
 *   startLiveCall()             POST /api/sessions
 *                                 {channel_type:"voice", interactive:true}
 *                               → RawSession (+ optional persona greeting via
 *                                 GET /sessions/{id}/messages)
 *   postLiveTurn(id, text)      POST /api/sessions/{id}/turn {text}
 *                               → operator echo + persona reply (+ entities)
 *
 * Shapes are normalized defensively (pending LiveVoice-Backend confirmation;
 * aligned 1:1 during the live field-alignment pass). Every call degrades to a
 * LOCAL persona (`mockLiveReply` — rule-based Bu Sari with real regex entity
 * extraction) so the live-mic demo runs standalone, exactly like the other
 * mock fallbacks.
 */

import { apiFetch } from "@/lib/http";
import {
  crimeLabel,
  deriveCustody,
  entitySubtitle,
  entityValue,
  extractionLabel,
  normalizeSession,
  type RawEntity,
  type RawSession,
} from "./api";
import { MOCK_VOICE_CALLER } from "./mock";
import type { CustodyInfo, DataSource } from "./types";
import { truncateValue } from "./types";
import {
  estimateDurationSec,
  normalizeLines,
  type RawVoiceMessage,
  type VoiceEntity,
  type VoiceCallSession,
  type VoiceLine,
} from "./voice";

/* ── Fetch plumbing (same pattern as voice.ts) ─────────────────────────── */

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

/* ── Start an interactive session ──────────────────────────────────────── */

/**
 * Start an INTERACTIVE voice session (backend `interactive` flag — the agent
 * loop replies turn-by-turn instead of pre-running the scripted replay).
 * Falls back to a local mock session when the backend is unreachable or has
 * no interactive support yet.
 */
export async function startLiveCall(): Promise<VoiceCallSession> {
  try {
    const raw = await request<RawSession>(
      "/sessions",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel_type: "voice", interactive: true }),
      },
      20000,
    );
    if (raw.channel_type !== "voice")
      throw new Error("backend has no voice channel");
    // A backend that ignores `interactive` pre-runs the whole scripted replay
    // (~8 messages). An interactive session starts empty or with a greeting.
    if (raw.message_count > 2)
      throw new Error("backend ignored the interactive flag (scripted run)");

    const messagesRaw = await request<RawVoiceMessage[]>(
      `/sessions/${encodeURIComponent(raw.id)}/messages`,
    ).catch(() => [] as RawVoiceMessage[]);

    const session = normalizeSession(raw);
    const lines = normalizeLines(messagesRaw, session.persona);
    const last = lines[lines.length - 1];
    return {
      id: raw.id,
      callerId: raw.channel_ref ?? "live mic · operator",
      persona: session.persona,
      modeTag: `${session.modeTag} · interactive`,
      status: session.status,
      lines,
      entities: [],
      custody: deriveCustody(raw, messagesRaw, null),
      disclosureIndex: -1,
      totalDurationSec: last ? Math.round(last.offsetSec + last.durationSec) : 0,
      source: "api",
    };
  } catch {
    return buildMockLiveCall();
  }
}

/* ── Turn round-trip ───────────────────────────────────────────────────── */

export interface LiveTurnResult {
  /** The operator's turn as logged by the backend (echo) — null if local. */
  operator: VoiceLine | null;
  /** The persona's spoken reply. */
  persona: VoiceLine;
  /** Entities extracted from this turn (panel additions). */
  entities: VoiceEntity[];
  custody: CustodyInfo | null;
  source: DataSource;
}

/* eslint-disable @typescript-eslint/no-explicit-any */

/** Pull message-shaped objects out of whatever the /turn endpoint returns. */
function collectTurnMessages(raw: any): RawVoiceMessage[] {
  const looksLikeMessage = (m: any): m is RawVoiceMessage =>
    m && typeof m === "object" && typeof m.content === "string";
  if (Array.isArray(raw)) return raw.filter(looksLikeMessage);
  if (Array.isArray(raw?.messages)) return raw.messages.filter(looksLikeMessage);
  return [
    raw?.turn,
    raw?.operator_message,
    raw?.message,
    raw?.reply,
    raw?.persona_message,
  ].filter(looksLikeMessage);
}

/**
 * POST the operator's utterance; get the persona's reply. The backend runs
 * STT-passthrough → agent loop → extraction → custody on this turn. Throws
 * on failure — the call view then falls back to the local mock persona so
 * the conversation never dies mid-demo.
 */
export async function postLiveTurn(
  sessionId: string,
  personaDisplay: string,
  text: string,
  atOffsetSec: number,
): Promise<LiveTurnResult> {
  // The agent loop + extraction run inline on this request — allow it time.
  const raw = await request<any>(
    `/sessions/${encodeURIComponent(sessionId)}/turn`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    },
    30000,
  );

  const messages = collectTurnMessages(raw);
  let lines = normalizeLines(messages, personaDisplay);
  // Plain-string reply shape ({reply: "..."}) — synthesize the persona line.
  if (!lines.some((l) => l.speaker === "persona") && typeof raw?.reply === "string") {
    lines = [
      ...lines,
      {
        id: `turn-${sessionId}-${Date.now()}`,
        seq: (messages[messages.length - 1]?.seq ?? 0) + 1,
        speaker: "persona",
        who: `Honeypot · ${personaDisplay.split(",")[0].trim()}`,
        text: raw.reply,
        durationSec: estimateDurationSec(raw.reply),
        offsetSec: 0,
        extractions: [],
        disclosure: false,
      },
    ];
  }
  const persona = [...lines].reverse().find((l) => l.speaker === "persona");
  if (!persona) throw new Error("turn response carried no persona reply");
  const operator = lines.find((l) => l.speaker === "scammer") ?? null;

  // Rebase offsets onto the running call clock.
  let cursor = atOffsetSec;
  for (const line of lines) {
    line.offsetSec = cursor;
    cursor += line.durationSec;
  }

  // Entities: response-level list + inline message entities, deduped.
  const rawEntities: RawEntity[] = [
    ...(Array.isArray(raw?.entities) ? raw.entities : []),
    ...messages.flatMap((m) => m.entities ?? []),
  ];
  const seen = new Set<string>();
  const entities: VoiceEntity[] = rawEntities
    .filter((e) => e && typeof e === "object" && typeof e.value === "string")
    .filter((e) => e.review_status !== "rejected" && e.review_status !== "poisoned")
    .filter((e) => (seen.has(e.id ?? e.value) ? false : (seen.add(e.id ?? e.value), true)))
    .map((e) => ({
      id: e.id ?? `live-${e.type}-${e.value}`,
      type: e.type,
      value: entityValue(e),
      subtitle: entitySubtitle(e),
      confidence: Math.max(0, Math.min(1, e.confidence ?? 0.9)),
      reviewStatus: e.review_status ?? "unverified",
      revealAtLine: 0, // rebased by the caller to the appended line index
    }));

  // Extraction badges on the operator line (regex hits land on the inbound turn).
  if (operator && !operator.extractions.length) {
    operator.extractions = rawEntities
      .filter((e) => messages.some((m) => m.id === e.message_id && m.direction === "inbound"))
      .map((e) => ({
        label: extractionLabel(e),
        confidence: Math.max(0, Math.min(1, e.confidence ?? 0.9)),
      }));
  }

  const custodyRaw = raw?.custody ?? raw?.session?.custody ?? null;
  const custody: CustodyInfo | null = custodyRaw
    ? {
        messagesLogged: `${custodyRaw.messages_logged ?? "—"}${custodyRaw.chain_intact === false ? "" : " · hash-chained"}`,
        // Per-turn classification lights up the crime class as the scammer talks.
        crimeClass: crimeLabel(raw?.classification?.crime_type ?? null),
        syndicateLink: "—",
        intact: custodyRaw.chain_intact !== false,
      }
    : null;

  return { operator, persona, entities, custody, source: "api" };
}

/* ── Local mock persona (offline / poc fallback) ───────────────────────── */

const MOCK_LIVE_GREETING =
  "Halo, selamat siang… dengan Ibu Sari di sini. Ini siapa ya? Suaranya kurang jelas…";

export function buildMockLiveCall(): VoiceCallSession {
  const greeting: VoiceLine = {
    id: "live-greet",
    seq: 1,
    speaker: "persona",
    who: "Honeypot · Bu Sari",
    text: MOCK_LIVE_GREETING,
    durationSec: estimateDurationSec(MOCK_LIVE_GREETING),
    offsetSec: 0,
    extractions: [],
    disclosure: false,
  };
  return {
    id: "hp-live-local",
    callerId: MOCK_VOICE_CALLER,
    persona: "Bu Sari, 54",
    modeTag: "POC · interactive",
    status: "active",
    lines: [greeting],
    entities: [],
    custody: {
      messagesLogged: "1 · hash-chained",
      crimeClass: "invest. scam",
      syndicateLink: "—",
      intact: true,
    },
    disclosureIndex: -1,
    totalDurationSec: Math.round(greeting.durationSec),
    source: "mock",
  };
}

/** Rule-based Bu Sari — keeps the demo conversational with zero backend. */
const STALL_REPLIES = [
  "Oh begitu ya Pak… maaf, saya kurang paham soal begituan. Bisa dijelaskan pelan-pelan?",
  "Iya Pak, saya dengar… terus saya harus bagaimana ya?",
  "Sebentar Pak, saya ambil kacamata dulu… iya, silakan dilanjut.",
  "Aduh, anak saya biasanya yang urus begini… tapi coba Bapak jelaskan dulu.",
];

interface MockExtraction {
  type: VoiceEntity["type"];
  value: string;
  subtitle: string;
  confidence: number;
  label: string;
}

function mockExtract(text: string): MockExtraction[] {
  const found: MockExtraction[] = [];
  const wallet = text.match(/\bT[1-9A-HJ-NP-Za-km-z]{20,40}\b/)?.[0];
  if (wallet)
    found.push({
      type: "crypto_wallet",
      value: truncateValue(wallet),
      subtitle: "USDT-TRC20",
      confidence: 0.99,
      label: "crypto_wallet (TRON)",
    });
  const phone = text.replace(/[\s.\-]/g, "").match(/(?:\+?62|0)8\d{8,11}/)?.[0];
  if (phone)
    found.push({
      type: "phone",
      value: phone,
      subtitle: "mentioned on call",
      confidence: 0.92,
      label: "phone",
    });
  if (!wallet && !phone) {
    const digits = text.replace(/[\s.\-]/g, "").match(/\b\d{8,16}\b/)?.[0];
    if (digits)
      found.push({
        type: "bank_account",
        value: digits,
        subtitle: "account read out on call",
        confidence: 0.95,
        label: "bank_account",
      });
  }
  return found;
}

/**
 * Local persona turn: extracts entities from the operator's words with the
 * same regex family the backend uses, then replies in character (gaptek
 * read-back beat when something was disclosed; stalling otherwise).
 */
export function mockLiveReply(
  text: string,
  turnIndex: number,
): { reply: string; extractions: MockExtraction[] } {
  const extractions = mockExtract(text);
  const lower = text.toLowerCase();

  if (extractions.some((e) => e.type === "bank_account")) {
    const acc = extractions.find((e) => e.type === "bank_account")!;
    const grouped = acc.value.replace(/(\d{4})(?=\d)/g, "$1… ");
    return {
      reply: `Sebentar Pak, saya catat dulu ya… ${grouped}… betul begitu? Atas nama siapa ya Pak rekeningnya?`,
      extractions,
    };
  }
  if (extractions.some((e) => e.type === "crypto_wallet"))
    return {
      reply:
        "Aduh, panjang sekali Pak alamatnya… nanti saya minta tolong anak saya kirim ke situ ya. Jaringannya apa tadi Pak?",
      extractions,
    };
  if (extractions.some((e) => e.type === "phone"))
    return {
      reply:
        "Oh iya, nomor itu ya Pak yang bisa saya hubungi lagi? Saya simpan dulu…",
      extractions,
    };
  if (/(transfer|rekening|deposit|setor|kirim uang)/.test(lower))
    return {
      reply:
        "Transfernya ke mana ya Pak? Tolong disebutkan pelan-pelan nomor rekeningnya, saya tulis dulu…",
      extractions,
    };
  if (/(usdt|kripto|crypto|dompet|wallet|bitcoin)/.test(lower))
    return {
      reply:
        "Kripto itu anak saya yang paham Pak… alamat dompetnya bagaimana? Biar saya teruskan ke dia.",
      extractions,
    };
  if (/(investasi|profit|untung|bunga|persen)/.test(lower))
    return {
      reply:
        "Wah, profitnya beneran bisa cair tiap hari Pak? Terus caranya bagaimana, saya harus transfer ke mana?",
      extractions,
    };
  return { reply: STALL_REPLIES[turnIndex % STALL_REPLIES.length], extractions };
}
