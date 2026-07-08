/**
 * Local fallback demo data — ported verbatim from the approved Honeypot
 * mockup (ittu-mockup artifact · #hp section). Used whenever the backend API
 * is unreachable so the console always renders standalone.
 *
 * Session template: Telegram · persona "Bu Sari, 54" · investment scam →
 * syndicate SYN-14 · extracted wallet feeds the Investigation graph.
 */

import type {
  CustodyInfo,
  HoneypotData,
  HpEntity,
  HpMessage,
  HpSession,
  VoiceStatus,
} from "./types";

export const MOCK_SESSION: HpSession = {
  id: "hp-session-0417",
  channel: "Telegram",
  persona: "Bu Sari, 54",
  modeTag: "POC · replay",
  status: "active",
};

/* ── Transcript (mockup verbatim, incl. inline extraction badges) ──────── */

export const MOCK_MESSAGES: HpMessage[] = [
  {
    id: "m1",
    sender: "scammer",
    who: "Scammer",
    text: "Selamat sore Bu, ini admin resmi investasi. Ibu sudah bisa mulai deposit hari ini, dijamin profit 30%.",
    extractions: [],
  },
  {
    id: "m2",
    sender: "persona",
    who: "Honeypot · Bu Sari",
    text: "oh iya pak.. tapi saya gaptek 🙏 caranya gimana ya? transfer kemana?",
    extractions: [],
  },
  {
    id: "m3",
    sender: "scammer",
    who: "Scammer",
    text: "Gampang bu. Transfer ke rekening BCA 4881207734 a/n PT Maju Jaya, nanti saya bantu proses.",
    extractions: [{ label: "bank_account", confidence: 0.98 }],
  },
  {
    id: "m4",
    sender: "persona",
    who: "Honeypot · Bu Sari",
    text: "kalau saya adanya di dana bisa pak? atau usdt? anak saya punya",
    extractions: [],
  },
  {
    id: "m5",
    sender: "scammer",
    who: "Scammer",
    text: "Bisa bu! kirim USDT ke TХ9dQpR7mK2vN8fLbY3wZaQ4pJ6 (TRC20). Screenshot ya kalau sudah.",
    extractions: [{ label: "crypto_wallet (TRON)", confidence: 0.99 }],
  },
];

/* ── Extracted-entities panel (icon · value · context · confidence) ────── */

export const MOCK_ENTITIES: HpEntity[] = [
  {
    id: "e1",
    type: "bank_account",
    value: "4881207734",
    subtitle: "BCA · PT Maju Jaya",
    confidence: 0.98,
    reviewStatus: "confirmed",
  },
  {
    id: "e2",
    type: "crypto_wallet",
    value: "TХ9dQp…aQ4pJ6",
    subtitle: "USDT-TRC20",
    confidence: 0.99,
    reviewStatus: "confirmed",
  },
  {
    id: "e3",
    type: "phone",
    value: "+62 812-8841-·····",
    subtitle: "operator",
    confidence: 0.94,
    reviewStatus: "confirmed",
  },
  {
    id: "e4",
    type: "url",
    value: "maju-jaya-invest·id",
    subtitle: "phishing",
    confidence: 0.87,
    reviewStatus: "confirmed",
  },
];

/* ── Chain of custody ──────────────────────────────────────────────────── */

export const MOCK_CUSTODY: CustodyInfo = {
  messagesLogged: "5 · hash-chained",
  crimeClass: "invest. scam",
  syndicateLink: "SYN-14",
  intact: true,
};

export const MOCK_VOICE: VoiceStatus = {
  active: true,
  label: "Voice call · live · STT+TTS",
};

export function buildMockHoneypot(): HoneypotData {
  return {
    session: MOCK_SESSION,
    messages: MOCK_MESSAGES,
    entities: MOCK_ENTITIES,
    custody: MOCK_CUSTODY,
    voice: MOCK_VOICE,
    composerNote:
      "agent drafting reply · human-in-the-loop armed for disclosure turn…",
    source: "mock",
  };
}
