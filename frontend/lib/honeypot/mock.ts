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
// Type-only import — erased at compile time, so no runtime cycle with
// voice.ts (which imports buildMockVoiceCall from here).
import type { VoiceCallSession, VoiceEntity, VoiceLine } from "./voice";

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

/* ══ P4b — voice-call fallback (phone-framed scam, spoken Bahasa cadence) ══
 *
 * Discloses the P1 fixture wallet TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6 + the BCA
 * mule account so the demo still links honeypot-call → Investigation, and
 * includes the persona's read-back confirmation turn (natural voice beat).
 */

export const MOCK_VOICE_CALLER = "+62 812-8841-4471";

const P1_WALLET = "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6";

/** Raw beats: [speaker, text, durationSec, extractions, disclosure]. */
const VOICE_BEATS: Array<
  [
    VoiceLine["speaker"],
    string,
    number,
    VoiceLine["extractions"],
    boolean,
  ]
> = [
  [
    "scammer",
    "Halo, selamat siang, dengan Ibu Sari? Saya Andi dari divisi investasi resmi, terdaftar OJK. Ibu terpilih untuk program profit harian tiga puluh persen, slotnya terbatas hari ini saja.",
    11,
    [],
    false,
  ],
  [
    "persona",
    "Oh iya halo Pak… maaf ya suara saya kecil, saya lagi di dapur. Program apa ya Pak? Saya kurang paham soal begituan…",
    9,
    [],
    false,
  ],
  [
    "scammer",
    "Gampang sekali Bu. Ibu catat ya — transfer dana awal ke rekening BCA, empat delapan delapan satu, dua nol tujuh, tujuh tiga empat, atas nama PT Maju Jaya. Nanti saya yang proses.",
    12,
    [{ label: "bank_account", confidence: 0.97 }],
    false,
  ],
  [
    "persona",
    "Sebentar Pak, saya ambil pulpen dulu… BCA… empat delapan delapan satu… dua nol tujuh… tujuh tiga empat, atas nama PT Maju Jaya. Betul ya Pak?",
    11,
    [],
    false,
  ],
  [
    "scammer",
    "Betul sekali Bu, pintar. Atau kalau anak Ibu punya kripto, lebih cepat — kirim USDT ke dompet saya, jaringan TRC dua puluh: T X t R sembilan d Q p R tujuh m K dua v N delapan f L b Y tiga w Z a Q empat p J enam.",
    14,
    [{ label: "crypto_wallet (TRON)", confidence: 0.99 }],
    true,
  ],
  [
    "persona",
    "Aduh panjang sekali Pak… nanti saya minta tolong anak saya ya. Nomor Bapak yang ini kan yang bisa saya hubungi lagi?",
    9,
    [],
    false,
  ],
  [
    "scammer",
    "Iya Bu, nomor ini saja, jangan ke nomor lain. Kalau sudah transfer langsung kabari, profitnya saya cairkan hari ini juga.",
    9,
    [],
    false,
  ],
];

export const MOCK_VOICE_LINES: VoiceLine[] = (() => {
  let offset = 0;
  return VOICE_BEATS.map(
    ([speaker, text, durationSec, extractions, disclosure], i) => {
      const line: VoiceLine = {
        id: `vl${i + 1}`,
        seq: i + 1,
        speaker,
        who: speaker === "scammer" ? "Scammer" : "Honeypot · Bu Sari",
        text,
        durationSec,
        offsetSec: offset,
        extractions,
        disclosure,
      };
      offset += durationSec;
      return line;
    },
  );
})();

export const MOCK_VOICE_ENTITIES: VoiceEntity[] = [
  {
    id: "ve1",
    type: "phone",
    value: MOCK_VOICE_CALLER,
    subtitle: "caller ID · operator",
    confidence: 0.95,
    reviewStatus: "confirmed",
    revealAtLine: 0,
  },
  {
    id: "ve2",
    type: "bank_account",
    value: "4881207734",
    subtitle: "BCA · PT Maju Jaya (mule)",
    confidence: 0.97,
    reviewStatus: "confirmed",
    revealAtLine: 2,
  },
  {
    id: "ve3",
    type: "crypto_wallet",
    value: `${P1_WALLET.slice(0, 6)}…${P1_WALLET.slice(-6)}`,
    subtitle: "USDT-TRC20",
    confidence: 0.99,
    reviewStatus: "confirmed",
    revealAtLine: 4,
  },
];

export function buildMockVoiceCall(): VoiceCallSession {
  const last = MOCK_VOICE_LINES[MOCK_VOICE_LINES.length - 1];
  return {
    id: "hp-voice-0417",
    callerId: MOCK_VOICE_CALLER,
    persona: "Bu Sari, 54",
    modeTag: "POC · replay",
    status: "active",
    lines: MOCK_VOICE_LINES,
    entities: MOCK_VOICE_ENTITIES,
    custody: {
      messagesLogged: `${MOCK_VOICE_LINES.length} · hash-chained`,
      crimeClass: "invest. scam",
      syndicateLink: "SYN-14",
      intact: true,
    },
    disclosureIndex: MOCK_VOICE_LINES.findIndex((l) => l.disclosure),
    totalDurationSec: Math.round(last.offsetSec + last.durationSec),
    source: "mock",
  };
}
