"use client";

/**
 * Human-gated dispatch card (mockup .dispatch footer) — "Confirm & dispatch"
 * is a two-step control (arm → confirm) so an outward-facing, irreversible
 * action never fires on a single click. Shows the bundle evidence hash and
 * the POC-mode explainer.
 */

import { useState } from "react";
import type { ActionBundle } from "@/lib/actions/types";

export function DispatchBar({
  bundle,
  dispatching,
  onDispatch,
}: {
  bundle: ActionBundle;
  dispatching: boolean;
  onDispatch: () => void;
}) {
  const [armed, setArmed] = useState(false);

  return (
    <div className="mt-3.5 rounded-card border border-line bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-line px-3.5 py-3">
        <span className="eyebrow">Dispatch · human-gated</span>
        <div className="flex items-center gap-2">
          {armed && !bundle.dispatched && (
            <button
              type="button"
              onClick={() => setArmed(false)}
              className="h-7 rounded-lg border border-line bg-elevated px-3 text-[11px] font-semibold text-white/60 transition-colors hover:bg-white/[.07]"
            >
              Cancel
            </button>
          )}
          <button
            type="button"
            disabled={dispatching || bundle.dispatched}
            onClick={() => {
              if (!armed) {
                setArmed(true);
                return;
              }
              setArmed(false);
              onDispatch();
            }}
            className={`h-7 rounded-lg px-3.5 text-[11px] font-semibold transition-colors disabled:opacity-60 ${
              armed
                ? "bg-risk-high text-white hover:bg-risk-high/90"
                : "bg-accent text-[#04140d] shadow-[0_0_16px_rgba(16,185,129,.28)] hover:bg-accent-bright"
            }`}
          >
            {bundle.dispatched
              ? "✓ Dispatched (mock sink)"
              : dispatching
                ? "Dispatching…"
                : armed
                  ? `Confirm — dispatch to ${bundle.targets.length} targets`
                  : "Confirm & dispatch"}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3.5 py-3 text-[11px] text-muted">
        <span>
          In <b className="text-white/60">POC mode</b> nothing leaves the
          system — LIVE mode routes to real channels + goAML + IASC freeze.
          Sending requires explicit confirmation.
        </span>
        <span className="ml-auto flex-none font-mono text-[10.5px]">
          evidence SHA-256{" "}
          <b className="text-accent-bright">{bundle.evidenceHash}</b>
        </span>
      </div>
    </div>
  );
}
