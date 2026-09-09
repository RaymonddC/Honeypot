/**
 * CekScam lookup + report.
 *
 * There is no public backend surface yet: every /api route requires a signed-in
 * investigator (see get_current_user on the casedata router), and a member of
 * the public has no account. So this resolves against the local index and marks
 * the result `source: "mock"`, exactly as the other modules do when the API is
 * unreachable — the screen shows that state rather than hiding it.
 *
 * When the public endpoint lands (GET /api/public/check, POST /api/public/report)
 * only the two request() calls below change; the shapes already match.
 */

import { INDEX, normalise } from "./mock";
import type { Chain, CheckKind, CheckResult, ScamReport } from "./types";

/*
 * Address shapes, mirrored from backend/app/infiltrate/extraction.py so the
 * honeypot's extractor and this page agree on what counts as an address —
 * anchored here (^…$) because we are classifying one pasted value rather than
 * finding addresses inside a transcript.
 *
 * Base58 omits 0, O, I and l precisely because they are the characters people
 * misread, which is also why a mistyped address usually fails to match at all
 * rather than matching the wrong thing.
 */
const B58 = "[1-9A-HJ-NP-Za-km-z]";
const TRON_RE = new RegExp(`^T${B58}{25,40}$`);
const ETH_RE = /^0x[0-9a-fA-F]{40}$/;
const BTC_LEGACY_RE = new RegExp(`^[13]${B58}{24,38}$`);
const BTC_BECH32_RE = /^bc1[02-9ac-hj-np-z]{11,71}$/;

/** Which ledger a pasted address is on, or null if it is not an address. */
export function detectChain(raw: string): Chain | null {
  const v = normalise(raw);
  if (TRON_RE.test(v)) return "TRON";
  if (ETH_RE.test(v)) return "ETH";
  // Bech32 is defined lowercase and every explorer renders it that way, but
  // people paste from all sorts of places, so the case is not held against them.
  if (BTC_LEGACY_RE.test(v) || BTC_BECH32_RE.test(v.toLowerCase())) return "BTC";
  return null;
}

/**
 * Work out what the user pasted so they do not have to say.
 *
 * Wallets are tested first because their shapes are the most specific — a chain
 * prefix plus a long fixed-ish body. They cannot collide with the digit rules
 * below: the shortest address here is 25 characters and contains letters,
 * while the longest account number is 16 digits.
 *
 * An Indonesian mobile number and a bank account, by contrast, are both plain
 * digit strings, and the only thing separating them is the 08/62 prefix — so
 * that prefix is tested before the generic account shape. E-wallets ARE mobile
 * numbers here, so anything matching the mobile shape is reported as a phone
 * and the lookup then tries both.
 */
export function detectKind(raw: string): CheckKind {
  const v = normalise(raw);
  if (!v) return "unknown";
  if (detectChain(v)) return "crypto_wallet";
  if (/^(\+?62|0)8\d{7,12}$/.test(v)) return "phone";
  if (/^\d{8,16}$/.test(v)) return "bank_account";
  return "unknown";
}

/** Indonesian mobile numbers are written 08…, +628… and 628… interchangeably. */
function phoneVariants(v: string): string[] {
  const digits = v.replace(/^\+/, "");
  const out = new Set([digits]);
  if (digits.startsWith("0")) out.add(`62${digits.slice(1)}`);
  if (digits.startsWith("62")) out.add(`0${digits.slice(2)}`);
  return [...out];
}

/**
 * Normalise case for comparison — and ONLY where case carries no information.
 *
 * Ethereum's mixed case is an EIP-55 checksum, not identity, and bech32 is
 * defined lowercase, so both fold safely. Base58 (TRON, legacy BTC) does not:
 * two addresses differing only in case are two different addresses, and
 * folding them would silently answer for the wrong one.
 */
function foldCase(v: string): string {
  if (ETH_RE.test(v)) return v.toLowerCase();
  if (BTC_BECH32_RE.test(v.toLowerCase())) return v.toLowerCase();
  return v;
}

export async function checkValue(raw: string): Promise<CheckResult> {
  const value = normalise(raw);
  const kind = detectKind(raw);

  // A phone and an e-wallet are the same string; try every written form of it
  // before giving up, since 08…, +628… and 628… are used interchangeably.
  const candidates =
    kind === "phone" || kind === "ewallet" ? phoneVariants(value) : [value];

  const folded = candidates.map(foldCase);
  const hit = INDEX.find((e) => folded.includes(foldCase(e.value)));
  const chain = kind === "crypto_wallet" ? (detectChain(value) ?? undefined) : undefined;

  if (!hit) {
    // Deliberately NOT "safe". See CheckVerdict in ./types.
    return { value, kind, verdict: "unknown", signals: [], chain, source: "mock" };
  }

  return {
    value,
    kind: hit.kind,
    // One uncorroborated report is not a verdict — it is a reason to be careful.
    verdict: hit.confidence >= 0.6 ? "flagged" : "caution",
    confidence: hit.confidence,
    signals: hit.signals,
    label: hit.label,
    chain,
    source: "mock",
  };
}

/**
 * File a public report. Returns the reference the reporter can quote.
 *
 * Nothing is transmitted in this build — there is no endpoint to receive it, and
 * inventing a "submitted" state for a report that went nowhere would be worse
 * than saying so. The screen tells the reporter exactly that.
 */
export async function submitReport(
  report: ScamReport,
): Promise<{ ref: string; delivered: boolean }> {
  const stamp = new Date();
  const ref = `CS-${stamp.getFullYear()}${String(stamp.getMonth() + 1).padStart(2, "0")}${String(
    stamp.getDate(),
  ).padStart(2, "0")}-${Math.random().toString(36).slice(2, 6).toUpperCase()}`;
  return { ref, delivered: false };
}
