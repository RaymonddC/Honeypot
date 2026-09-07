/**
 * INFILTRATE / Honeypot console — frontend-canonical types.
 *
 * The API layer (lib/honeypot/api.ts) normalizes the backend payloads
 * (docs/API-Contract.md · INFILTRATE endpoints, docs/Data-Model.md ·
 * intel.scam_sessions / intel.messages / intel.entities) into these shapes;
 * the mock fallback (lib/honeypot/mock.ts) produces them directly, ported
 * from the approved mockup's Honeypot section.
 */

export type DataSource = "api" | "mock";

/* ── Session header ────────────────────────────────────────────────────── */

export interface HpSession {
  id: string;
  /** Channel display, e.g. "Telegram". */
  channel: string;
  /** Persona display, e.g. "Bu Sari, 54". */
  persona: string;
  /** Mode tag, e.g. "POC · replay" | "LIVE". */
  modeTag: string;
  /** active | escalated | closed */
  status: string;
}

/* ── Chat transcript ───────────────────────────────────────────────────── */

export type MessageSender = "scammer" | "persona";

/** Inline `◇ extracted · <type> · conf 0.xx` badge under a message. */
export interface MessageExtraction {
  /** Badge label, e.g. "bank_account" | "crypto_wallet (TRON)". */
  label: string;
  /** 0..1 */
  confidence: number;
}

export interface HpMessage {
  id: string;
  sender: MessageSender;
  /** Bubble byline: "Scammer" | "Honeypot · Bu Sari". */
  who: string;
  text: string;
  extractions: MessageExtraction[];
}

/* ── Extracted-entities panel ──────────────────────────────────────────── */

export type EntityType =
  | "bank_account"
  | "crypto_wallet"
  | "phone"
  | "url"
  | "person"
  | "org"
  | "alias";

export interface HpEntity {
  id: string;
  type: EntityType;
  /** Display value (wallets pre-truncated, e.g. "TХ9dQp…aQ4pJ6"). */
  value: string;
  /** Full untruncated value — used to promote the entity into the case. */
  rawValue?: string;
  /** Bank name (bank_account only) — for promoting to a tracked account. */
  bankName?: string;
  /** Chain (crypto_wallet only), e.g. "tron". */
  chain?: string;
  /** Context line, e.g. "BCA · PT Maju Jaya" | "USDT-TRC20" | "phishing". */
  subtitle: string;
  /** 0..1 */
  confidence: number;
  /** unverified | confirmed | rejected | poisoned */
  reviewStatus: string;
}

/* ── Chain-of-custody card ─────────────────────────────────────────────── */

export type ComposerNoteKey = "drafting" | "escalated" | "closed";

export interface CustodyInfo {
  /** Count only, e.g. "5". The "· hash-chained" suffix is added by the card
   *  from `intact` — it is a LABEL, so it belongs in i18n, not baked in here. */
  messagesLogged: string;
  /**
   * Crime typology KEY (e.g. "investment_scam"), not a label. CustodyCard
   * resolves the wording; the data layer used to emit English ("invest. scam")
   * which then rendered untranslated inside an Indonesian panel.
   * Unknown values pass through and are shown verbatim.
   */
  crimeClass: string;
  /** e.g. "SYN-14". */
  syndicateLink: string;
  /** Hash chain verified end-to-end. */
  intact: boolean;
}

/* ── Voice-call indicator (visual only — P4b) ──────────────────────────── */

export interface VoiceStatus {
  active: boolean;
  /** e.g. "Voice call · live · STT+TTS". */
  label: string;
}

/* ── Aggregate screen payload ──────────────────────────────────────────── */

export interface HoneypotData {
  session: HpSession;
  messages: HpMessage[];
  entities: HpEntity[];
  custody: CustodyInfo;
  voice: VoiceStatus;
  /** Which composer status line to show. A KEY, not text: this used to be
   *  an English sentence built in the data layer, which rendered untranslated
   *  under an otherwise Indonesian transcript. */
  composerNote: ComposerNoteKey;
  source: DataSource;
}

/* ── Entity display helpers (mockup conventions) ───────────────────────── */

// Geometric marks rather than emoji: these render inside a bordered well in
// the UI face and must take the surrounding text colour.
export const ENTITY_ICONS: Record<string, string> = {
  bank_account: "▣",
  crypto_wallet: "⛓",
  phone: "☎",
  url: "↗",
  person: "◍",
  org: "▤",
  alias: "◇",
};

export const entityIcon = (type: string): string =>
  ENTITY_ICONS[type] ?? "◇";

/** Truncate long values (wallet addresses) mockup-style: "TХ9dQp…aQ4pJ6". */
export function truncateValue(v: string, head = 6, tail = 6): string {
  return v.length > head + tail + 1 ? `${v.slice(0, head)}…${v.slice(-tail)}` : v;
}

/** Chain display: tron → "USDT-TRC20" (project convention), else upper. */
export function chainLabel(chain: string): string {
  const c = chain.toLowerCase();
  if (c === "tron" || c === "trc20" || c === "usdt-trc20") return "USDT-TRC20";
  return chain.toUpperCase();
}

export const formatConf = (c: number): string =>
  (Math.max(0, Math.min(1, c))).toFixed(2);
