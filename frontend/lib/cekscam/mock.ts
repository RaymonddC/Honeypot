/**
 * The demo intelligence index CekScam answers from.
 *
 * These are the SAME identities the rest of the app demonstrates on — the
 * golden-thread BCA account and collection wallet, the honeypot session's
 * extracted entities, the on-ramp sender and the exchange exit. That is
 * deliberate: a check here and the investigator console are looking at one
 * database, which is the whole claim of slide 05's three layers.
 *
 * Everything in this file is fixture data. lib/cekscam/api.ts is what decides
 * whether to use it, and the screen says so on the result.
 */

import { GOLDEN } from "@/lib/demo/golden-thread";
import type { CheckKind, CheckSignal } from "./types";

export interface IndexEntry {
  kind: CheckKind;
  /** Normalised (digits only for accounts/phones, case-preserved for chains). */
  value: string;
  label?: string;
  confidence: number;
  signals: CheckSignal[];
}

/** Strip the separators people paste — "5271-0384-62", "+62 812 8841 4471". */
export function normalise(raw: string): string {
  return raw.trim().replace(/[\s\-().]/g, "");
}

export const INDEX: IndexEntry[] = [
  // ── the golden thread: mule account → collection wallet ────────────────
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

  // ── the honeypot session's extracted entities ──────────────────────────
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

  // ── a caution-grade entry: one report, nothing corroborating it ────────
  {
    kind: "ewallet",
    value: "081299887766",
    label: "DANA",
    confidence: 0.34,
    signals: [{ key: "publicReports", values: { count: 1 } }, { key: "firstSeen", values: { when: "3 hari lalu" } }],
  },
];

/** Rough count shown on the page. Real enough to be honest: it is the number of
 *  entities the demo index actually holds, not an invented national figure. */
export const INDEX_SIZE = INDEX.length;
