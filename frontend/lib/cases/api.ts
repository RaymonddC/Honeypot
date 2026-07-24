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

export interface CaseRollup {
  case: Case;
  bank_accounts: Array<Record<string, unknown>>;
  crypto_transfers: Array<Record<string, unknown>>;
  counts: { bank_accounts: number; crypto_transfers: number };
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
