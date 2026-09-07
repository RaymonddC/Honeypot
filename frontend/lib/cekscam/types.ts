/**
 * CekScam — the public (Layer 1 / B2C) check surface.
 *
 * A member of the public pastes a bank account, phone number, e-wallet or
 * crypto address and asks "is this a scammer?" before they transfer. Every
 * check and report is also intake: it seeds the honeypot intelligence database
 * the institutional modules read from.
 *
 * The verdict vocabulary is deliberately three-valued, and the third value is
 * the important one. A lookup that finds nothing must NOT read as "safe" —
 * absence of evidence about an account is not evidence it is clean, and a
 * public safety tool that blurs the two teaches people to trust an unknown
 * account. See CheckVerdict below.
 */

export type DataSource = "api" | "mock";

/** What the user pasted. Detected from the value itself — they should not have
 *  to classify it before they can ask. */
export type CheckKind =
  | "bank_account"
  | "phone"
  | "ewallet"
  | "crypto_wallet"
  | "url"
  | "unknown";

export type CheckVerdict =
  /** Reported and corroborated — treat as a scam account. */
  | "flagged"
  /** Seen, but not enough to call it: partial signals or a single report. */
  | "caution"
  /** Not in the database. NOT the same as safe — the copy must say so. */
  | "unknown";

/** One piece of why. Kept as structured data so the UI can order and translate
 *  it rather than rendering a pre-built sentence. */
export interface CheckSignal {
  /** i18n leaf under cekscam.signals.* */
  key:
    | "honeypotDisclosed"
    | "publicReports"
    | "syndicateLinked"
    | "onRampToCrypto"
    | "exchangeDeposit"
    | "seenInFlow"
    | "firstSeen";
  /** Interpolated into the message (counts, dates, names). */
  values?: Record<string, string | number>;
}

export interface CheckResult {
  /** Echo of what was looked up, normalised (spaces and dashes stripped). */
  value: string;
  kind: CheckKind;
  verdict: CheckVerdict;
  /** 0..1 — how strongly the signals point at a scam. Absent when unknown. */
  confidence?: number;
  /** Reason codes, strongest first. */
  signals: CheckSignal[];
  /** Holder / label where the database has one, e.g. "BCA · PT Maju Jaya". */
  label?: string;
  source: DataSource;
}

/** A public report — Layer 1's other half. This is what feeds INFILTRATE. */
export interface ScamReport {
  kind: CheckKind;
  value: string;
  /** Free text: what happened, in the reporter's own words. */
  story: string;
  /** Rupiah, optional — many reports come before any money moves. */
  amountIdr?: number;
  /** Optional contact so an investigator can follow up. */
  contact?: string;
}

/** Verdict → the risk colour token the UI paints with. */
export const VERDICT_TONE: Record<CheckVerdict, "high" | "med" | "muted"> = {
  flagged: "high",
  caution: "med",
  unknown: "muted",
};
