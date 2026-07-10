/**
 * INFILTRATE API client — Honeypot console data.
 *
 * Shapes confirmed 1:1 with P4-Backend (2026-07-08, see docs/API-Contract.md
 * + docs/Data-Model.md · intel.*):
 *
 *   GET /api/sessions                      → RawSession[]
 *   GET /api/sessions/{id}/messages       → RawMessage[]  (entities INLINE)
 *   GET /api/entities?session={id}        → RawEntity[]
 *   GET /api/syndicates                   → RawSyndicate[] (label lookup)
 *
 * Base URL: NEXT_PUBLIC_API_URL (default http://localhost:8000). Any failure
 * falls back to the local mock (lib/honeypot/mock.ts) so the console stays
 * demoable standalone.
 */

import { buildMockHoneypot } from "./mock";
import type {
  CustodyInfo,
  HoneypotData,
  HpEntity,
  HpMessage,
  HpSession,
  VoiceStatus,
} from "./types";
import { chainLabel, truncateValue } from "./types";

import { apiFetch } from "@/lib/http";

async function request<T>(path: string, timeoutMs = 6000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await apiFetch(path, { signal: ctrl.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

/* ── Raw backend payloads (P4-Backend-confirmed, snake_case) ──────────── */

interface RawPersona {
  id: string;
  name: string;
  age: number | null;
  occupation?: string | null;
  region?: string | null;
}

interface RawCustody {
  messages_logged: number;
  chain_intact: boolean;
  genesis: string;
  head_sha256: string;
}

interface RawSession {
  id: string;
  persona: RawPersona;
  channel_type: "text" | "voice";
  channel: string; // "telegram"
  channel_ref: string | null; // "@ProfitMax_Andi"
  status: "active" | "escalated" | "closed";
  crime_type: string | null; // "investment_scam"
  data_mode: "poc" | "live";
  started_at: string;
  ended_at: string | null;
  message_count: number;
  entity_count: number;
  custody: RawCustody | null;
  syndicate_id: string | null;
}

interface RawEntity {
  id: string;
  session_id: string;
  message_id: string | null;
  type: "bank_account" | "crypto_wallet" | "phone" | "url";
  value: string;
  normalized_value: string | null;
  chain: string | null; // crypto_wallet only
  bank_name: string | null; // bank_account only
  context: string | null; // UI subtitle string
  method: "regex" | "llm" | "human";
  confidence: number;
  review_status: "unverified" | "confirmed" | "rejected" | "poisoned";
}

interface RawMessage {
  id: string;
  session_id: string;
  seq: number;
  direction: "inbound" | "outbound"; // inbound = scammer, outbound = persona
  content: string;
  ts: string;
  sha256: string;
  prev_sha256: string;
  entities: RawEntity[]; // extracted from THIS message
}

interface RawSyndicate {
  id: string;
  label: string;
  session_ids: string[];
}

/* ── Session ──────────────────────────────────────────────────────────── */

/** Crime-type enum → console display (mockup convention). */
const CRIME_LABELS: Record<string, string> = {
  investment_scam: "invest. scam",
  judol_deposit: "judol deposit",
  crypto_phishing: "phishing",
  romance: "romance scam",
};

const crimeLabel = (t: string | null): string =>
  t ? (CRIME_LABELS[t] ?? t.replace(/_/g, " ")) : "—";

const cap = (s: string): string =>
  s ? s.charAt(0).toUpperCase() + s.slice(1) : s;

function normalizeSession(raw: RawSession): HpSession {
  return {
    id: raw.id,
    channel: cap(raw.channel),
    persona: raw.persona.age != null
      ? `${raw.persona.name}, ${raw.persona.age}`
      : raw.persona.name,
    modeTag: raw.data_mode === "live" ? "LIVE" : "POC · replay",
    status: raw.status,
  };
}

/** Newest active session first; else newest overall (POC replays end "escalated"). */
function pickSession(sessions: RawSession[]): RawSession {
  if (!sessions.length) throw new Error("no sessions from API");
  const ordered = [...sessions].sort((a, b) =>
    (b.started_at ?? "").localeCompare(a.started_at ?? ""),
  );
  return ordered.find((s) => s.status === "active") ?? ordered[0];
}

/* ── Entities ─────────────────────────────────────────────────────────── */

function entitySubtitle(e: RawEntity): string {
  if (e.type === "crypto_wallet" && e.chain) return chainLabel(e.chain);
  if (e.type === "bank_account" && e.bank_name) {
    if (!e.context) return e.bank_name;
    // Live contexts often lead with the bank name — don't double it.
    return e.context.includes(e.bank_name)
      ? e.context
      : `${e.bank_name} · ${e.context}`;
  }
  return e.context ?? e.type.replace(/_/g, " ");
}

/** Display value: wallets truncated; phones/urls prefer normalized form. */
function entityValue(e: RawEntity): string {
  if (e.type === "crypto_wallet") return truncateValue(e.value);
  if (e.type === "phone" || e.type === "url")
    return e.normalized_value ?? e.value;
  return e.value;
}

function normalizeEntities(raw: RawEntity[]): HpEntity[] {
  return raw
    .filter(
      (e) => e.review_status !== "rejected" && e.review_status !== "poisoned",
    )
    .map(
      (e): HpEntity => ({
        id: e.id,
        type: e.type,
        value: entityValue(e),
        subtitle: entitySubtitle(e),
        confidence: Math.max(0, Math.min(1, e.confidence)),
        reviewStatus: e.review_status,
      }),
    );
}

/* ── Messages (inline entities → extraction badges) ───────────────────── */

const extractionLabel = (e: RawEntity): string =>
  e.chain ? `${e.type} (${e.chain.toUpperCase()})` : e.type;

function normalizeMessages(
  raw: RawMessage[],
  session: HpSession,
): HpMessage[] {
  const personaFirst = session.persona.split(",")[0].trim();
  return [...raw]
    .sort((a, b) => a.seq - b.seq)
    .map((m): HpMessage => {
      const isScammer = m.direction === "inbound";
      return {
        id: m.id,
        sender: isScammer ? "scammer" : "persona",
        who: isScammer ? "Scammer" : `Honeypot · ${personaFirst}`,
        text: m.content,
        extractions: (m.entities ?? []).map((e) => ({
          label: extractionLabel(e),
          confidence: Math.max(0, Math.min(1, e.confidence)),
        })),
      };
    });
}

/* ── Chain of custody (session.custody, message-derived fallback) ─────── */

function deriveCustody(
  session: RawSession,
  messages: RawMessage[],
  syndicateLabel: string | null,
): CustodyInfo {
  const logged = session.custody?.messages_logged ?? messages.length;
  const intact =
    session.custody?.chain_intact ??
    (messages.length > 0 && messages.every((m) => !!m.sha256));
  return {
    messagesLogged: `${logged}${intact ? " · hash-chained" : ""}`,
    crimeClass: crimeLabel(session.crime_type),
    syndicateLink: syndicateLabel ?? session.syndicate_id ?? "—",
    intact,
  };
}

/* ── Voice indicator (visual only — live voice lands in P4b) ──────────── */

const deriveVoice = (session: RawSession): VoiceStatus =>
  session.channel_type === "voice"
    ? { active: true, label: "Voice call · live · STT+TTS" }
    : { active: false, label: "Voice · standby · P4b" };

/* ── Public surface ───────────────────────────────────────────────────── */

/**
 * Load the full Honeypot console payload for the most relevant session.
 * Falls back to the mock dataset (mockup transcript) when the API is
 * unreachable or returns no sessions.
 */
export async function fetchHoneypotData(): Promise<HoneypotData> {
  try {
    const sessions = await request<RawSession[]>("/sessions");
    const sessionRaw = pickSession(sessions);

    const [messagesRaw, entitiesRaw, syndicates] = await Promise.all([
      request<RawMessage[]>(
        `/sessions/${encodeURIComponent(sessionRaw.id)}/messages`,
      ),
      request<RawEntity[]>(
        `/entities?session=${encodeURIComponent(sessionRaw.id)}`,
      ).catch(() => null),
      sessionRaw.syndicate_id
        ? request<RawSyndicate[]>("/syndicates").catch(() => [])
        : Promise.resolve([] as RawSyndicate[]),
    ]);

    const session = normalizeSession(sessionRaw);
    const messages = normalizeMessages(messagesRaw, session);
    if (!messages.length) throw new Error("empty transcript from API");

    // Panel entities: session-wide endpoint, else flattened from messages.
    const entities = normalizeEntities(
      entitiesRaw ?? messagesRaw.flatMap((m) => m.entities ?? []),
    );

    const syndicateLabel =
      syndicates.find((s) => s.id === sessionRaw.syndicate_id)?.label ?? null;

    return {
      session,
      messages,
      entities,
      custody: deriveCustody(sessionRaw, messagesRaw, syndicateLabel),
      voice: deriveVoice(sessionRaw),
      composerNote:
        sessionRaw.status === "escalated"
          ? "escalated · analyst takeover — human-in-the-loop engaged"
          : sessionRaw.status === "closed"
            ? "session closed · transcript sealed in custody log"
            : "agent drafting reply · human-in-the-loop armed for disclosure turn…",
      source: "api",
    };
  } catch {
    return buildMockHoneypot();
  }
}
