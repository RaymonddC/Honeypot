/**
 * CASES API client — the case-file spine.
 *
 *   POST  /api/cases            create
 *   GET   /api/cases            list (newest first)
 *   PATCH /api/cases/{id}       advance stage / edit
 *   GET   /api/cases/{id}/rollup case + attached case-data
 *
 * All calls carry the Bearer token via apiFetch.
 */

import { apiFetch } from "@/lib/http";

export const CASE_STAGES = [
  "intake",
  "freeze",
  "trace",
  "takedown",
  "report",
  "recovery",
  "closed",
] as const;

export type CaseStage = (typeof CASE_STAGES)[number];

export interface Case {
  id: string;
  title: string;
  status: "open" | "active" | "closed" | "archived";
  stage: CaseStage;
  crime_type: string | null;
  summary: string | null;
  created_at: string;
  updated_at: string;
}

export interface CaseSessionSummary {
  id: string;
  channel: string;
  /** text | voice — a phone call vs a chat (backend-provided, not guessed). */
  channel_type?: string;
  channel_ref: string;
  crime_type: string | null;
  status: string;
  entity_count: number;
  started_at: string;
}

export interface CaseDocumentSummary {
  id: string;
  status: string;
  crime_type: string;
  document_count: number;
  created_at: string;
}

export interface CaseRollup {
  case: Case;
  bank_accounts: Array<Record<string, unknown>>;
  crypto_transfers: Array<Record<string, unknown>>;
  sessions: CaseSessionSummary[];
  documents: CaseDocumentSummary[];
  counts: {
    bank_accounts: number;
    crypto_transfers: number;
    sessions: number;
    documents: number;
  };
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

export function listCases() {
  return json<Case[]>("/cases");
}

export function createCase(input: {
  title: string;
  crime_type?: string;
  summary?: string;
}) {
  return json<Case>("/cases", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
}

export function updateCase(
  id: string,
  patch: Partial<Pick<Case, "title" | "crime_type" | "summary" | "stage" | "status">>,
) {
  return json<Case>(`/cases/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
}

export function fetchRollup(id: string) {
  return json<CaseRollup>(`/cases/${id}/rollup`);
}

/* ── Audit trail (GET /api/audit) ────────────────────────────────────────── */

export interface AuditEntry {
  seq: number;
  action: string;
  actor_user_id: string | null;
  target_type: string | null;
  target_id: string | null;
  detail: Record<string, unknown>;
  ts: string;
  sha256: string;
  prev_sha256: string;
}

export interface AuditFeed {
  entries: AuditEntry[];
  /** Every hash links to its predecessor — recomputed server-side on each read. */
  chain_ok: boolean;
  /** First entry that fails verification, if any. */
  broken_at_seq: number | null;
}

/** This agency's audit trail, newest first, with the chain verified on read. */
export function fetchAuditFeed(limit = 100) {
  return json<AuditFeed>(`/audit?limit=${limit}`);
}
