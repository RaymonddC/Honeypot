/**
 * HONEYPOT OPS API client — the outbound-calling number pool + dial campaigns
 * (docs/Voice-Honeypot-Outbound.md §6).
 *
 *   GET/POST   /api/honeypot/numbers                 pool: list / register
 *   PATCH      /api/honeypot/numbers/{id}            retire / relabel
 *   GET/POST   /api/honeypot/campaigns               list / create
 *   GET        /api/honeypot/campaigns/{id}          + per-status target counts
 *   GET/POST   /api/honeypot/campaigns/{id}/targets  list / bulk-upload
 *   POST       /api/honeypot/campaigns/{id}/start|pause
 *
 * Nothing here dials — start/pause are status transitions only (phase 3).
 * All calls carry the Bearer token via apiFetch.
 */

import { apiFetch } from "@/lib/http";

export type NumberStatus = "active" | "retired" | "rate_limited";
export type CampaignStatus = "draft" | "running" | "paused" | "completed";
export type TargetStatus =
  | "queued"
  | "dialing"
  | "no_answer"
  | "engaged"
  | "failed";

export interface HoneypotNumber {
  id: string;
  phone_number: string;
  twilio_sid: string | null;
  label: string;
  status: NumberStatus;
  data_mode: string;
  created_at: string;
  updated_at: string;
}

export interface DialCampaign {
  id: string;
  name: string;
  case_id: string | null;
  status: CampaignStatus;
  pacing_per_minute: number;
  data_mode: string;
  created_at: string;
  /** Per-status target counts; only statuses actually present are included. */
  counts: Record<string, number>;
  target_count: number;
}

export interface DialTarget {
  id: string;
  campaign_id: string;
  phone_number: string;
  status: TargetStatus;
  /**
   * Dial attempts made. Requeue never resets this — it IS the retry history.
   * There is deliberately no `session_id`: a target can be dialed many times,
   * so the call log is one-to-many and lives on the sessions themselves
   * (`scam_sessions.dial_target_id`).
   */
  attempt_count: number;
  last_error: string | null;
  data_mode: string;
  created_at: string;
  updated_at: string;
}

/** Statuses a finished target can be requeued from (never queued/dialing). */
export type RequeueableStatus = "no_answer" | "failed" | "engaged";

export interface RequeueResult {
  requeued: number;
  /** Targets skipped because they were queued or dialing (a call in flight). */
  skipped: number;
  targets: DialTarget[];
}

export type RejectReason =
  | "invalid"
  | "duplicate_in_upload"
  | "already_in_campaign";

export interface RejectedNumber {
  value: string;
  reason: RejectReason;
}

export interface UploadTargetsResult {
  added: number;
  rejected: RejectedNumber[];
  targets: DialTarget[];
}

async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await apiFetch(path, init);
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      msg = j?.error?.message ?? msg;
    } catch {
      /* keep */
    }
    throw new Error(msg);
  }
  return (await res.json()) as T;
}

const POST_JSON = (body: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

/* ── numbers ───────────────────────────────────────────────────────────── */

export function listNumbers() {
  return json<HoneypotNumber[]>("/honeypot/numbers");
}

export function registerNumber(input: {
  phone_number: string;
  twilio_sid?: string;
  label?: string;
}) {
  return json<HoneypotNumber>("/honeypot/numbers", POST_JSON(input));
}

export function updateNumber(
  id: string,
  patch: { label?: string; status?: NumberStatus },
) {
  return json<HoneypotNumber>(`/honeypot/numbers/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

/* ── campaigns ─────────────────────────────────────────────────────────── */

export function listCampaigns() {
  return json<DialCampaign[]>("/honeypot/campaigns");
}

export function createCampaign(input: {
  name: string;
  case_id?: string;
  pacing_per_minute?: number;
}) {
  return json<DialCampaign>("/honeypot/campaigns", POST_JSON(input));
}

export function getCampaign(id: string) {
  return json<DialCampaign>(`/honeypot/campaigns/${id}`);
}

export function listTargets(id: string) {
  return json<DialTarget[]>(`/honeypot/campaigns/${id}/targets`);
}

/** Bulk-add numbers: a JSON array, pasted CSV/newline text, or both. */
export function uploadTargets(
  id: string,
  input: { numbers?: string[]; text?: string },
) {
  return json<UploadTargetsResult>(
    `/honeypot/campaigns/${id}/targets`,
    POST_JSON(input),
  );
}

export function startCampaign(id: string) {
  return json<DialCampaign>(`/honeypot/campaigns/${id}/start`, POST_JSON({}));
}

export function pauseCampaign(id: string) {
  return json<DialCampaign>(`/honeypot/campaigns/${id}/pause`, POST_JSON({}));
}

/**
 * Send finished targets back to `queued` so they are dialed again — this is how
 * you call a number a second time. A campaign never holds two rows for the same
 * number, so re-calling is a state change on the existing target and
 * `attempt_count` is preserved as history.
 *
 * Pass `target_ids` for specific targets, or `statuses` to sweep (the server
 * defaults to every no_answer + failed). Targets that are queued or dialing are
 * skipped — a dialing target has a call in flight.
 */
export function requeueTargets(
  id: string,
  input: { target_ids?: string[]; statuses?: RequeueableStatus[] } = {},
) {
  return json<RequeueResult>(
    `/honeypot/campaigns/${id}/requeue`,
    POST_JSON(input),
  );
}

/* ── client-side helpers ───────────────────────────────────────────────── */

const E164 = /^\+[1-9]\d{7,14}$/;

/**
 * Mirror of the backend's `normalize_e164` so the paste box can preview what
 * will be accepted BEFORE uploading. The server re-validates — this is UX,
 * never the security boundary.
 */
export function normalizeE164(raw: string): string | null {
  let cleaned = (raw ?? "").trim().replace(/[\s\-().]/g, "");
  if (cleaned.startsWith("00")) cleaned = `+${cleaned.slice(2)}`;
  if (!cleaned.startsWith("+")) return null;
  return E164.test(cleaned) ? cleaned : null;
}

/** Split pasted text the same way the backend does: first CSV field per line. */
export function splitPasted(text: string): string[] {
  return text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => l.split(",")[0].trim().replace(/^"|"$/g, ""));
}
