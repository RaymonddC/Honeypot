/**
 * The demo intelligence index CekScam answers from.
 *
 * Bank accounts, phone numbers and e-wallets only — what a member of the public
 * is actually about to transfer to. Crypto addresses are the investigator
 * console's job (TAKEDOWN scores them against the chain); offering them here
 * would imply a check this surface cannot honestly make.
 *
 * The golden-thread BCA account is first and deliberately: a check here and the
 * investigator console are looking at one database, which is the whole claim of
 * slide 05's three layers. The rest are additional fixtures so every input type
 * and both verdict grades can actually be exercised.
 *
 * Everything here is fixture data. lib/cekscam/api.ts decides whether to use it
 * and the screen says so on the result.
 */

import { GOLDEN } from "@/lib/demo/golden-thread";
import type { CheckKind, CheckSignal } from "./types";

export interface IndexEntry {
  kind: CheckKind;
  /** Normalised: digits only, separators stripped. */
  value: string;
  label?: string;
  /** ≥ 0.6 reads as "flagged", below as "caution" — see checkValue(). */
  confidence: number;
  signals: CheckSignal[];
}

/** Strip the separators people paste — "5271-0384-62", "+62 812 8841 4471". */
export function normalise(raw: string): string {
  return raw.trim().replace(/[\s\-().]/g, "");
}

export const INDEX: IndexEntry[] = [
  /* ── the golden thread: the mule account the honeypot surfaced ─────────── */
  {
    kind: "bank_account",
    value: GOLDEN.bank.accountNumber,
    label: `${GOLDEN.bank.bankName} · ${GOLDEN.bank.holder}`,
    confidence: 0.98,
    signals: [
      { key: "honeypotDisclosed", values: { channel: "Telegram" } },
      { key: "publicReports", values: { count: 14 } },
      { key: "seenInFlow" },
      { key: "syndicateLinked", values: { syndicate: "SYN-14" } },
    ],
  },
  {
    kind: "bank_account",
    value: "4881207734",
    label: "BCA · PT Maju Jaya",
    confidence: 0.96,
    signals: [
      { key: "honeypotDisclosed", values: { channel: "Telegram" } },
      { key: "publicReports", values: { count: 6 } },
      { key: "seenInFlow" },
    ],
  },
  {
    kind: "phone",
    value: "6281288414471",
    label: "nomor operator",
    confidence: 0.91,
    signals: [
      { key: "honeypotDisclosed", values: { channel: "WhatsApp" } },
      { key: "publicReports", values: { count: 9 } },
    ],
  },

  /* ── judol (online gambling) rail: collector account + its e-wallet ────── */
  {
    kind: "bank_account",
    value: "7710455823",
    label: "Mandiri · CV Sinar Abadi",
    confidence: 0.94,
    signals: [
      { key: "publicReports", values: { count: 22 } },
      { key: "seenInFlow" },
      { key: "syndicateLinked", values: { syndicate: "SYN-07" } },
    ],
  },
  {
    kind: "ewallet",
    value: "081355720194",
    label: "OVO",
    confidence: 0.88,
    signals: [
      { key: "publicReports", values: { count: 11 } },
      { key: "syndicateLinked", values: { syndicate: "SYN-07" } },
    ],
  },
  {
    kind: "bank_account",
    value: "1290047731",
    label: "BRI · Andi Prasetyo",
    confidence: 0.72,
    signals: [
      { key: "publicReports", values: { count: 3 } },
      { key: "seenInFlow" },
    ],
  },

  /* ── impersonation: fake bank officer, fake courier ────────────────────── */
  {
    kind: "phone",
    value: "6281130092255",
    label: "mengaku petugas bank",
    confidence: 0.83,
    signals: [
      { key: "publicReports", values: { count: 17 } },
      { key: "honeypotDisclosed", values: { channel: "WhatsApp" } },
    ],
  },
  {
    kind: "phone",
    value: "6285770041188",
    label: "mengaku kurir paket",
    confidence: 0.77,
    signals: [
      { key: "publicReports", values: { count: 12 } },
      { key: "syndicateLinked", values: { syndicate: "SYN-22" } },
    ],
  },
  {
    kind: "ewallet",
    value: "085811203344",
    label: "DANA",
    confidence: 0.66,
    signals: [
      { key: "publicReports", values: { count: 5 } },
      { key: "firstSeen", values: { when: "11 hari lalu" } },
    ],
  },

  /* ── newer, thinner evidence: lands as "caution", not "flagged" ────────── */
  {
    kind: "bank_account",
    value: "3320981145",
    label: "BNI · Siti Rahayu",
    confidence: 0.38,
    signals: [
      { key: "publicReports", values: { count: 1 } },
      { key: "firstSeen", values: { when: "2 hari lalu" } },
    ],
  },
  {
    kind: "phone",
    value: "6287865512033",
    label: "profil asmara",
    confidence: 0.29,
    signals: [{ key: "publicReports", values: { count: 1 } }],
  },
  {
    kind: "ewallet",
    value: "081299887766",
    label: "GoPay",
    confidence: 0.34,
    signals: [
      { key: "publicReports", values: { count: 1 } },
      { key: "firstSeen", values: { when: "3 hari lalu" } },
    ],
  },
  {
    kind: "bank_account",
    value: "5540118822",
    label: "CIMB Niaga · Budi Santoso",
    confidence: 0.45,
    signals: [
      { key: "publicReports", values: { count: 2 } },
      { key: "firstSeen", values: { when: "6 hari lalu" } },
    ],
  },
];

/** How many entities the demo index actually holds. Shown on the page so the
 *  claim is the real number, not an invented national figure. */
export const INDEX_SIZE = INDEX.length;

export type SampleKey = "bank" | "phone" | "ewallet" | "caution" | "unknown";

/**
 * Values offered on the page as one-tap examples.
 *
 * A public tool nobody can try is a public tool nobody trusts: without these
 * you have to already know a scam account to see what the page does. Each chip
 * names what it is, and one is the "no record" state — that is where most real
 * checks land, so it should be the easiest one to reach.
 */
export const SAMPLES: Array<{ value: string; labelKey: SampleKey }> = [
  { value: GOLDEN.bank.accountNumber, labelKey: "bank" },
  { value: "081130092255", labelKey: "phone" },
  { value: "081355720194", labelKey: "ewallet" },
  { value: "3320981145", labelKey: "caution" },
  { value: "1234567890", labelKey: "unknown" },
];
