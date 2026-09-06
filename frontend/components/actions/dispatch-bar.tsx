"use client";

/**
 * Human-gated dispatch card (mockup .dispatch footer) — "Confirm & dispatch"
 * is a two-step control (arm → confirm) so an outward-facing, irreversible
 * action never fires on a single click. Shows the bundle evidence hash and
 * the POC-mode explainer.
 */

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import type { ActionBundle } from "@/lib/actions/types";
import { DispatchReceipt } from "@/components/actions/dispatch-receipt";

export function DispatchBar({
  bundle,
  dispatching,
  onDispatch,
}: {
  bundle: ActionBundle;
  dispatching: boolean;
  onDispatch: () => void;
}) {
  const t = useTranslations("actions.dispatchBar");
  const [armed, setArmed] = useState(false);
  const [showReceipt, setShowReceipt] = useState(false);

  // Pop the receipt automatically the moment a dispatch completes.
  const wasDispatched = useRef(bundle.dispatched);
  useEffect(() => {
    if (bundle.dispatched && !wasDispatched.current) setShowReceipt(true);
    wasDispatched.current = bundle.dispatched;
  }, [bundle.dispatched]);

  return (
    <div className="mt-3.5 rounded-card border border-line bg-card">
      <div className="flex items-center justify-between gap-3 border-b border-line px-3.5 py-3">
        <span className="eyebrow">{t("dispatchHumanGated")}</span>
        <div className="flex items-center gap-2">
          {bundle.dispatched && (
            <button
              type="button"
              onClick={() => setShowReceipt(true)}
              className="h-7 rounded-full border border-accent/30 bg-accent/10 px-3 text-[11px] font-semibold text-accent-bright transition-colors hover:bg-accent/20"
            >
              ⧉ {t("receipt")}
            </button>
          )}
          {armed && !bundle.dispatched && (
            <button
              type="button"
              onClick={() => setArmed(false)}
              className="h-7 rounded-lg border border-line bg-elevated px-3 text-[11px] font-semibold text-muted transition-colors hover:bg-fg/[.07]"
            >
              {t("cancel")}
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
                : "bg-accent text-[#090909] shadow-[0_0_16px_rgba(255, 255, 255,.28)] hover:bg-accent-bright"
            }`}
          >
            {bundle.dispatched
              ? t("dispatchedMockSink")
              : dispatching
                ? t("dispatching")
                : armed
                  ? t("confirmDispatchTo", { count: bundle.targets.length })
                  : t("confirmAndDispatch")}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3.5 py-3 text-[11px] text-muted">
        <span>
          {t.rich("pocModeExplainer", {
            b: (chunks) => <b className="text-fg">{chunks}</b>,
          })}
        </span>
        <span className="ml-auto flex-none font-mono text-[10.5px]">
          {t("evidenceSha256")}{" "}
          <b className="text-accent-bright">{bundle.evidenceHash}</b>
        </span>
      </div>

      {showReceipt && (
        <DispatchReceipt bundle={bundle} onClose={() => setShowReceipt(false)} />
      )}
    </div>
  );
}
