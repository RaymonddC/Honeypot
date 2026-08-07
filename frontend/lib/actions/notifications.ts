/**
 * Dispatch Log feed — the agency "outbox": every notification ITTU has fired,
 * across cases, with its delivery status. Backs the Response dashboard's
 * Dispatch Log panel.
 *
 *   GET  /api/notifications?status=&agency_type=&case_id=  → NotificationOut[]
 *   POST /api/notifications/{id}/retry                     → NotificationOut
 *
 * Mirrors the rest of `lib/actions` / `lib/response`: on any error it falls
 * back to a local mock so the screen still renders, tagged `offline`.
 */

import { API_BASE, apiFetch } from "@/lib/http";
import type { DataSource, DispatchStatus } from "@/lib/actions/types";

export interface DispatchNotification {
  id: string;
  actionId: string;
  caseId: string;
  agency: string;
  agencyType: string;
  channel: string;
  status: DispatchStatus;
  dataMode: string;
  sentAt: string | null;
  attemptCount: number;
  lastError: string | null;
  idempotencyKey: string | null;
}

export interface NotificationFeed {
  items: DispatchNotification[];
  source: DataSource;
}

/* eslint-disable @typescript-eslint/no-explicit-any */

function normalize(n: any): DispatchNotification {
  return {
    id: String(n.id),
    actionId: String(n.action_id ?? ""),
    caseId: String(n.case_id ?? ""),
    agency: String(n.target_agency ?? "unknown"),
    agencyType: String(n.agency_type ?? "regulator"),
    channel: String(n.channel ?? ""),
    status: (n.status ?? "queued") as DispatchStatus,
    dataMode: String(n.data_mode ?? "poc"),
    sentAt: n.sent_at ?? null,
    attemptCount: Number(n.attempt_count ?? 0),
    lastError: n.last_error ?? null,
    idempotencyKey: n.idempotency_key ?? null,
  };
}

async function req<T>(path: string, init?: RequestInit, timeoutMs = 8000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await apiFetch(path, { ...init, signal: ctrl.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

export interface FeedFilters {
  status?: DispatchStatus;
  agencyType?: string;
  caseId?: string;
}

/** Fetch the dispatch log; falls back to the mock feed when the API is down. */
export async function fetchNotifications(f: FeedFilters = {}): Promise<NotificationFeed> {
  const qs = new URLSearchParams();
  if (f.status) qs.set("status", f.status);
  if (f.agencyType) qs.set("agency_type", f.agencyType);
  if (f.caseId) qs.set("case_id", f.caseId);
  const query = qs.toString() ? `?${qs.toString()}` : "";
  try {
    const raw = await req<any[]>(`${API_BASE}/api/notifications${query}`);
    return { items: (raw ?? []).map(normalize), source: "api" };
  } catch {
    let items = MOCK_FEED;
    if (f.status) items = items.filter((n) => n.status === f.status);
    if (f.agencyType) items = items.filter((n) => n.agencyType === f.agencyType);
    return { items, source: "mock" };
  }
}

/**
 * Re-dispatch a failed/queued notification (idempotent on the backend — the
 * recipient dedupes on the reused key). Returns the updated record, or the
 * unchanged one on a mock/unreachable backend.
 */
export async function retryNotification(id: string): Promise<DispatchNotification | null> {
  try {
    const raw = await req<any>(`${API_BASE}/api/notifications/${encodeURIComponent(id)}/retry`, {
      method: "POST",
    });
    return normalize(raw);
  } catch {
    return null;
  }
}

/* ── Offline mock feed (mirrors a dispatched golden-thread bundle) ────────── */
const MOCK_FEED: DispatchNotification[] = [
  {
    id: "ntf_mock01",
    actionId: "act_demo",
    caseId: "CASE-2026-0142",
    agency: "Bank BCA",
    agencyType: "bank",
    channel: "iasc",
    status: "mock",
    dataMode: "poc",
    sentAt: new Date().toISOString(),
    attemptCount: 0,
    lastError: null,
    idempotencyKey: "idem_demo01",
  },
  {
    id: "ntf_mock02",
    actionId: "act_demo",
    caseId: "CASE-2026-0142",
    agency: "PPATK",
    agencyType: "regulator",
    channel: "goaml",
    status: "mock",
    dataMode: "poc",
    sentAt: new Date().toISOString(),
    attemptCount: 0,
    lastError: null,
    idempotencyKey: "idem_demo02",
  },
  {
    id: "ntf_mock03",
    actionId: "act_demo",
    caseId: "CASE-2026-0142",
    agency: "Polri — Dittipideksus",
    agencyType: "police",
    channel: "webhook",
    status: "mock",
    dataMode: "poc",
    sentAt: new Date().toISOString(),
    attemptCount: 0,
    lastError: null,
    idempotencyKey: "idem_demo03",
  },
];
