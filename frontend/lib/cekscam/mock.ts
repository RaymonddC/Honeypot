/**
 * The demo intelligence index CekScam answers from.
 *
 * The first three entries are the SAME identities the rest of the app
 * demonstrates on — the golden-thread BCA account and collection wallet, the
 * on-ramp sender, the exchange exit. That is deliberate: a check here and the
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
  /** Normalised: digits only for accounts/phones, case preserved for chains. */
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
  /* ── the golden thread: mule account → collection wallet → exchange ───── */
  {
    kind: "bank_account",
    value: GOLDEN.bank.accountNumber,
    label: `${GOLDEN.bank.bankName} · ${GOLDEN.bank.holder}`,
    confidence: 0.98,
    signals: [
      { key: "honeypotDisclosed", values: { channel: "Telegram" } },
      { key: "publicReports", values: { count: 14 } },
      { key: "onRampToCrypto", values: { chain: "USDT-TRC20" } },
      { key: "syndicateLinked", values: { syndicate: "SYN-14" } },
    ],
  },
  {
    kind: "crypto_wallet",
    value: GOLDEN.wallet,
    label: "USDT-TRC20",
    confidence: 0.97,
    signals: [
      { key: "onRampToCrypto", values: { chain: "USDT-TRC20" } },
      { key: "exchangeDeposit", values: { exchange: "Indodax" } },
      { key: "syndicateLinked", values: { syndicate: "SYN-14" } },
    ],
  },
  {
    kind: "crypto_wallet",
    value: GOLDEN.exit,
    label: "USDT-TRC20 · exchange hot wallet",
    confidence: 0.42,
    signals: [{ key: "exchangeDeposit", values: { exchange: "Indodax" } }],
  },

  /* ── the honeypot session's extracted entities ────────────────────────── */
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
    label: "operator",
    confidence: 0.91,
    signals: [
      { key: "honeypotDisclosed", values: { channel: "WhatsApp" } },
      { key: "publicReports", values: { count: 9 } },
    ],
  },
  {
    kind: "url",
    value: "maju-jaya-invest.id",
    label: "phishing",
    confidence: 0.87,
    signals: [
      { key: "publicReports", values: { count: 4 } },
      { key: "syndicateLinked", values: { syndicate: "SYN-14" } },
    ],
  },

  /* ── judol (online gambling) rail: QRIS collector + its mule chain ────── */
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

  /* ── impersonation: fake bank / courier / tax officer ─────────────────── */
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
    kind: "url",
    value: "bca-verifikasi-akun.com",
    label: "phishing",
    confidence: 0.95,
    signals: [
      { key: "publicReports", values: { count: 31 } },
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

  /* ── romance / investment: newer, thinner evidence ────────────────────── */
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
    label: "DANA",
    confidence: 0.34,
    signals: [
      { key: "publicReports", values: { count: 1 } },
      { key: "firstSeen", values: { when: "3 hari lalu" } },
    ],
  },

  /* ── crypto side: an ETH launderer and a second TRON collector ────────── */
  {
    kind: "crypto_wallet",
    value: "0x7a3F5c91Db4e0A28cB6F2d1E85B7c40A9e3D6F21",
    label: "USDT-ERC20",
    confidence: 0.79,
    signals: [
      { key: "onRampToCrypto", values: { chain: "USDT-ERC20" } },
      { key: "syndicateLinked", values: { syndicate: "SYN-22" } },
    ],
  },
  {
    kind: "crypto_wallet",
    value: "TJ8kL3mNpQ7rS2tU9vW4xY6zA1bC5dE8fG",
    label: "USDT-TRC20",
    confidence: 0.51,
    signals: [{ key: "exchangeDeposit", values: { exchange: "Tokocrypto" } }],
  },
];

/** How many entities the demo index actually holds. Shown on the page so the
 *  claim is the real number, not an invented national figure. */
export const INDEX_SIZE = INDEX.length;

/**
 * A few values offered on the page as one-tap examples.
 *
 * A public tool nobody can try is a public tool nobody trusts: without these
 * you have to already know a scam account to see what the page does. One of
 * each verdict grade, so the "not in our database" wording — the state most
 * checks land on — is reachable too.
 */
export type SampleKey = "bank" | "ewallet" | "wallet" | "caution" | "unknown";

export const SAMPLES: Array<{ value: string; labelKey: SampleKey }> = [
  { value: GOLDEN.bank.accountNumber, labelKey: "bank" },
  { value: "081355720194", labelKey: "ewallet" },
  { value: GOLDEN.wallet, labelKey: "wallet" },
  { value: "3320981145", labelKey: "caution" },
  { value: "1234567890", labelKey: "unknown" },
];
