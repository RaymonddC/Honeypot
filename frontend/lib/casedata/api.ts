/**
 * CASEDATA API client — analyst-entered records that feed the engines.
 *
 *   POST /api/casedata/crypto-transfers → merged into the Investigation graph
 *   POST /api/casedata/bank-accounts    → surfaced on the Bridge watchlist
 *   GET  /api/casedata/bank-accounts    → list tracked accounts
 *   GET  /api/bridge/accounts           → tracked accounts + seen_in_flow flag
 *
 * All calls carry the Bearer token via apiFetch (writes require auth).
 */

import { apiFetch } from "@/lib/http";

export interface CryptoTxInput {
  from_addr: string;
  to_addr: string;
  value: number;
  ts: string; // ISO
  chain?: string;
  /** On-chain tx hash (optional — the backend mints one when absent). */
  tx_hash?: string | null;
  category?: string;
  note?: string;
  case_id?: string | null;
}

export interface BankAccountInput {
  bank_name: string;
  account_number: string;
  holder_name?: string;
  category?: string;
  note?: string;
  case_id?: string | null;
}

export interface WatchlistedAccount {
  id: string;
  bank_name: string;
  account_number: string;
  holder_name: string | null;
  category: string;
  note: string;
  seen_in_flow: boolean;
  created_at: string;
}

async function postJSON<T>(path: string, body: unknown): Promise<T> {
  const res = await apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const j = await res.json();
      detail = j?.error?.message ?? j?.detail?.[0]?.msg ?? detail;
    } catch {
      /* keep default */
    }
    throw new Error(detail);
  }
  return (await res.json()) as T;
}

export function addCryptoTransfer(input: CryptoTxInput) {
  return postJSON("/casedata/crypto-transfers", input);
}

export function addBankAccount(input: BankAccountInput) {
  return postJSON("/casedata/bank-accounts", input);
}

export async function listWatchlistAccounts(
  caseId?: string | null,
): Promise<WatchlistedAccount[]> {
  const q = caseId ? `?case=${encodeURIComponent(caseId)}` : "";
  const res = await apiFetch(`/bridge/accounts${q}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const j = await res.json();
  return (j?.items ?? []) as WatchlistedAccount[];
}
