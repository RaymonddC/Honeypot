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
import type { CheckKind, CheckResult, ScamReport } from "./types";

/**
 * Work out what the user pasted so they do not have to say.
 *
 * An Indonesian mobile number and a bank account are both digit strings, and
 * the only thing separating them is the 08/62 prefix — so the prefix is tested
 * first. E-wallets ARE mobile numbers here, so anything matching the mobile
 * shape is reported as a phone and the lookup then tries both.
 */
export function detectKind(raw: string): CheckKind {
  const v = normalise(raw);
  if (!v) return "unknown";
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

export async function checkValue(raw: string): Promise<CheckResult> {
  const value = normalise(raw);
  const kind = detectKind(raw);

  // A phone and an e-wallet are the same string; try every written form of it
  // before giving up, since 08…, +628… and 628… are used interchangeably.
  const candidates =
    kind === "phone" || kind === "ewallet" ? phoneVariants(value) : [value];

  const hit = INDEX.find((e) => candidates.some((c) => c === e.value));

  if (!hit) {
    // Deliberately NOT "safe". See CheckVerdict in ./types.
    return { value, kind, verdict: "unknown", signals: [], source: "mock" };
  }

  return {
    value,
    kind: hit.kind,
    // One uncorroborated report is not a verdict — it is a reason to be careful.
    verdict: hit.confidence >= 0.6 ? "flagged" : "caution",
    confidence: hit.confidence,
    signals: hit.signals,
    label: hit.label,
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
