/**
 * Suspected on-ramps alert feed — confidence-ranked fiat↔crypto correlation
 * matches (mockup .alert rows: score · "Mule cluster → exchange" · meta).
 */

import type { OnRampAlert } from "@/lib/bridge/types";
import { confidenceColor } from "@/lib/bridge/types";

export function OnRampFeed({ alerts }: { alerts: OnRampAlert[] }) {
  return (
    <div className="mb-3.5 rounded-card border border-line bg-card">
      <div className="flex items-center justify-between border-b border-line px-3.5 py-3">
        <span className="eyebrow">Suspected on-ramps</span>
        <span className="rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[10.5px] text-white/60">
          by confidence
        </span>
      </div>

      {alerts.length ? (
        alerts.map((a) => (
          <div
            key={a.id}
            className="flex gap-2.5 border-b border-line px-3.5 py-[11px] last:border-b-0"
          >
            <div
              className="font-mono text-[13px] font-bold tnum"
              style={{ color: confidenceColor(a.confidence) }}
            >
              {a.confidence.toFixed(2)}
            </div>
            <div className="min-w-0">
              <b className="mb-0.5 block truncate text-xs">{a.title}</b>
              <small className="font-mono text-[10.5px] text-muted">
                {a.meta}
              </small>
            </div>
          </div>
        ))
      ) : (
        <div className="px-3.5 py-6 text-center text-[11px] text-muted">
          No correlated on-ramps yet — run the simulation.
        </div>
      )}
    </div>
  );
}
