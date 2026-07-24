/**
 * Suspected on-ramps alert feed — confidence-ranked fiat↔crypto correlation
 * matches (mockup .alert rows: score · "Mule cluster → exchange" · meta).
 */

import type { OnRampAlert } from "@/lib/bridge/types";
import { confidenceColor } from "@/lib/bridge/types";

export function OnRampFeed({
  alerts,
  onTrace,
}: {
  alerts: OnRampAlert[];
  /** Trace this on-ramp's crypto wallet in Takedown. */
  onTrace?: (addr: string) => void;
}) {
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
            className="flex items-center gap-2.5 border-b border-line px-3.5 py-[11px] last:border-b-0"
          >
            <div
              className="font-mono text-[13px] font-bold tnum"
              style={{ color: confidenceColor(a.confidence) }}
            >
              {a.confidence.toFixed(2)}
            </div>
            <div className="min-w-0 flex-1">
              <b className="mb-0.5 block truncate text-xs">{a.title}</b>
              <small className="font-mono text-[10.5px] text-muted">
                {a.meta}
              </small>
            </div>
            {onTrace && a.wallet && (
              <button
                type="button"
                onClick={() => onTrace(a.wallet as string)}
                title={`Trace ${a.wallet} in Takedown`}
                className="flex-none rounded-md border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-[9.5px] font-semibold text-accent-bright transition-colors hover:bg-accent/20"
              >
                trace →
              </button>
            )}
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
