"use client";

/**
 * Suspected on-ramps alert feed — confidence-ranked fiat↔crypto correlation
 * matches. Each row is a real crypto leg (launderer wallet → exchange hot
 * wallet), so inside a case you can:
 *   · + case  — save it as a case transfer (both wallets land in Takedown)
 *   · trace → — jump straight to Takedown on the launderer wallet
 * That's what makes Trace's findings usable in Takedown.
 */

import { useState } from "react";
import { useCases } from "@/components/cases/case-provider";
import { addCryptoTransfer } from "@/lib/casedata/api";
import type { OnRampAlert } from "@/lib/bridge/types";
import { confidenceColor } from "@/lib/bridge/types";

function AlertActions({
  a,
  onTrace,
}: {
  a: OnRampAlert;
  onTrace?: (addr: string) => void;
}) {
  const { activeCaseId } = useCases();
  const [state, setState] = useState<"idle" | "busy" | "done" | "err">("idle");
  const canSave =
    Boolean(activeCaseId) &&
    Boolean(a.wallet && a.toAddr) &&
    (a.valueUsdt ?? 0) > 0;

  const save = async () => {
    if (!canSave) return;
    setState("busy");
    try {
      await addCryptoTransfer({
        from_addr: a.wallet as string,
        to_addr: a.toAddr as string,
        value: a.valueUsdt as number,
        ts: a.ts ?? new Date().toISOString(),
        chain: "tron",
        tx_hash: a.txHash ?? undefined,
        category: "suspect",
        case_id: activeCaseId,
      });
      setState("done");
    } catch {
      setState("err");
    }
  };

  return (
    <div className="flex flex-none items-center gap-1.5">
      {canSave &&
        (state === "done" ? (
          <span className="text-[9.5px] font-semibold text-accent-bright" title="Saved as a case transfer → Takedown">
            ✓ in case
          </span>
        ) : (
          <button
            type="button"
            onClick={save}
            disabled={state === "busy"}
            title="Save this on-ramp as a case transfer (feeds Takedown)"
            className="rounded-md border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-[9.5px] font-semibold text-accent-bright transition-colors hover:bg-accent/20 disabled:opacity-50"
          >
            {state === "busy" ? "…" : state === "err" ? "retry" : "+ case"}
          </button>
        ))}
      {onTrace && a.wallet && (
        <button
          type="button"
          onClick={() => onTrace(a.wallet as string)}
          title={`Trace ${a.wallet} in Takedown`}
          className="rounded-md border border-line px-1.5 py-0.5 text-[9.5px] font-semibold text-muted transition-colors hover:text-fg"
        >
          trace →
        </button>
      )}
    </div>
  );
}

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
            <AlertActions a={a} onTrace={onTrace} />
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
