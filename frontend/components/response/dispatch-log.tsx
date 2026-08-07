"use client";

/**
 * Dispatch Log — the agency "outbox" on the Response dashboard: every
 * notification ITTU has fired, across cases, with its delivery status. Reads
 * GET /api/notifications and lets an operator retry a failed one
 * (POST /api/notifications/{id}/retry). Falls back to the mock feed offline.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchNotifications,
  retryNotification,
  type DispatchNotification,
} from "@/lib/actions/notifications";
import { STATUS_COLORS, STATUS_LABELS } from "@/lib/actions/types";

const AGENCY_GLYPH: Record<string, string> = {
  bank: "🏦",
  exchange: "💱",
  regulator: "🏛️",
  police: "🚓",
};

function StatusPill({ status }: { status: DispatchNotification["status"] }) {
  const color = STATUS_COLORS[status] ?? "rgba(255,255,255,.5)";
  return (
    <span
      className="rounded-md border px-1.5 py-0.5 font-mono text-[10px] font-semibold"
      style={{ color, borderColor: `${color}44`, background: `${color}14` }}
    >
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

export function DispatchLog() {
  const [items, setItems] = useState<DispatchNotification[] | null>(null);
  const [source, setSource] = useState<"api" | "mock">("api");
  const [retrying, setRetrying] = useState<string | null>(null);
  const seq = useRef(0);

  const load = useCallback(async () => {
    const s = ++seq.current;
    const feed = await fetchNotifications();
    if (s !== seq.current) return;
    setItems(feed.items);
    setSource(feed.source);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const onRetry = useCallback(
    async (id: string) => {
      setRetrying(id);
      await retryNotification(id);
      await load();
      setRetrying(null);
    },
    [load],
  );

  return (
    <div className="rounded-card border border-line bg-card">
      <div className="flex items-center justify-between border-b border-line px-3.5 py-[13px]">
        <div className="flex items-center gap-2">
          <span className="eyebrow">Dispatch log · agency outbox</span>
          <span
            className={`rounded-md border px-1.5 py-0.5 font-mono text-[9.5px] font-semibold ${
              source === "api"
                ? "border-accent/30 bg-accent/10 text-accent-bright"
                : "border-risk-med/30 bg-risk-med/10 text-risk-med"
            }`}
          >
            {source === "api" ? "● live api" : "● offline · mock"}
          </span>
        </div>
        <span className="font-mono text-[10.5px] text-muted">
          {items?.length ?? 0} dispatched
        </span>
      </div>

      {items === null ? (
        <div className="grid h-[180px] animate-pulse place-items-center text-[11px] text-muted">
          Loading dispatch records…
        </div>
      ) : items.length === 0 ? (
        <div className="grid h-[120px] place-items-center px-4 text-center text-[11px] text-muted">
          No notifications dispatched yet — generate an action bundle and
          dispatch it to fire the multi-agency alerts.
        </div>
      ) : (
        <div className="max-h-[340px] overflow-y-auto">
          <table className="w-full border-collapse text-[11.5px]">
            <thead>
              <tr className="sticky top-0 bg-card text-left text-[9px] uppercase tracking-wide text-muted">
                <th className="px-3.5 py-2 font-medium">Agency</th>
                <th className="px-2 py-2 font-medium">Channel</th>
                <th className="px-2 py-2 font-medium">Status</th>
                <th className="px-2 py-2 font-medium">Case</th>
                <th className="px-3.5 py-2 text-right font-medium">Delivery</th>
              </tr>
            </thead>
            <tbody>
              {items.map((n) => (
                <tr key={n.id} className="border-t border-line/60 align-middle">
                  <td className="px-3.5 py-2">
                    <div className="flex items-center gap-1.5">
                      <span aria-hidden>{AGENCY_GLYPH[n.agencyType] ?? "📡"}</span>
                      <span className="font-medium text-fg">{n.agency}</span>
                    </div>
                  </td>
                  <td className="px-2 py-2 font-mono text-[10.5px] text-muted">
                    {n.channel || "—"}
                  </td>
                  <td className="px-2 py-2">
                    <StatusPill status={n.status} />
                    {n.lastError && (
                      <span
                        className="ml-1.5 font-mono text-[9.5px] text-risk-high"
                        title={n.lastError}
                      >
                        {n.lastError}
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-2 font-mono text-[10px] text-muted">{n.caseId}</td>
                  <td className="px-3.5 py-2 text-right">
                    {n.status === "failed" ? (
                      <button
                        type="button"
                        disabled={retrying === n.id}
                        onClick={() => onRetry(n.id)}
                        className="rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[10px] font-semibold text-accent-bright transition-colors hover:bg-white/[.04] disabled:opacity-50"
                      >
                        {retrying === n.id ? "retrying…" : "↻ retry"}
                      </button>
                    ) : (
                      <span className="font-mono text-[10px] text-muted">
                        {n.attemptCount > 0 ? `${n.attemptCount}×` : "—"}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
