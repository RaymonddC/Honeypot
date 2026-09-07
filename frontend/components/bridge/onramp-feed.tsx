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
import { useTranslations } from "next-intl";
import { useCases } from "@/components/cases/case-provider";
import { addCryptoTransfer } from "@/lib/casedata/api";
import type { OnRampAlert } from "@/lib/bridge/types";
import { confidenceColor, formatIDR, formatMinutes } from "@/lib/bridge/types";

function AlertActions({
  a,
  onTrace,
}: {
  a: OnRampAlert;
  onTrace?: (addr: string) => void;
}) {
  const t = useTranslations("bridge.onrampFeed");
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
          <span className="text-[12px] font-semibold text-accent-bright" title={t("savedTitle")}>
            {t("inCase")}
          </span>
        ) : (
          <button
            type="button"
            onClick={save}
            disabled={state === "busy"}
            title={t("saveTitle")}
            className="rounded-full border border-accent/40 bg-accent/10 px-1.5 py-0.5 text-[12px] font-semibold text-accent-bright transition-colors hover:bg-accent/20 disabled:opacity-50"
          >
            {state === "busy" ? t("saving") : state === "err" ? t("retry") : t("addCase")}
          </button>
        ))}
      {onTrace && a.wallet && (
        <button
          type="button"
          onClick={() => onTrace(a.wallet as string)}
          title={t("traceTitle", { address: a.wallet })}
          className="rounded-md border border-line px-1.5 py-0.5 text-[12px] font-semibold text-muted transition-colors hover:text-fg"
        >
          {t("trace")}
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
  const t = useTranslations("bridge.onrampFeed");

  /**
   * The evidence line: amount · time gap · amount match. Composed HERE from
   * numbers rather than arriving as a finished string, so "amount match" is
   * translated like everything around it. Falls back to a generic label when
   * a correlation carries none of the three.
   */
  const metaOf = (a: OnRampAlert): string => {
    const parts: string[] = [];
    if (a.amountIdr != null) parts.push(formatIDR(a.amountIdr));
    if (a.deltaSeconds != null) parts.push(formatMinutes(a.deltaSeconds));
    if (a.amountMatchPct != null)
      parts.push(t("amountMatch", { pct: a.amountMatchPct.toFixed(1) }));
    return parts.join(" · ") || t("correlatedFallback");
  };

  return (
    <div className="mb-3.5 rounded-card border border-line bg-card">
      {/* The "ranked by confidence" chip used to sit here. In Indonesian it is
          "berdasarkan tingkat keyakinan" — far longer than the English — and in
          a 300px rail it forced the eyebrow to break mid-word ("DUGAAN ON-" /
          "RAMP"). It was also redundant: the rows are numbered #1..#n and each
          carries a confidence meter. It survives as the header's tooltip. */}
      <div className="border-b border-line px-3.5 py-2.5" title={t("byConfidence")}>
        <span className="eyebrow">{t("title", { count: alerts.length })}</span>
      </div>

      {alerts.length ? (
        <div className="max-h-[360px] overflow-y-auto">
          {alerts.map((a, i) => {
            const c = confidenceColor(a.confidence);
            return (
              <div
                key={a.id}
                className="border-b border-line px-3.5 py-2.5 transition-colors last:border-b-0 hover:bg-fg/[.02]"
              >
                {/* Two rows, not one. Score + title + meta used to share a line
                    with the action buttons; in a 300px rail that left the text
                    column ~86px, so `meta` (which is a sentence, not a figure:
                    "Rp 48.2M · Δt 12 min · amount match 99.1%") wrapped to three
                    lines and shoved the buttons out of alignment. Giving the
                    actions their own row lets the text use the full width. */}
                <div className="flex items-start gap-2.5">
                  {/* rank + confidence */}
                  <div className="flex w-9 flex-none flex-col items-center">
                    <div className="text-[13px] font-bold leading-none tnum" style={{ color: c }}>
                      {a.confidence.toFixed(2)}
                    </div>
                    <div className="mt-0.5 text-[8.5px] uppercase tracking-wide text-muted">
                      #{i + 1}
                    </div>
                  </div>
                  <div className="min-w-0 flex-1">
                    <b className="mb-0.5 block truncate text-[12px]" title={a.title}>
                      {a.title}
                    </b>
                    <small className="block truncate text-[12px] text-muted" title={metaOf(a)}>
                      {metaOf(a)}
                    </small>
                  </div>
                </div>
                <div className="mt-1.5 flex justify-end">
                  <AlertActions a={a} onTrace={onTrace} />
                </div>
                {/* confidence meter */}
                <div className="mt-2 h-1 overflow-hidden rounded-full bg-elevated">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{ width: `${Math.round(a.confidence * 100)}%`, background: c }}
                  />
                </div>
              </div>
            );
          })}
        </div>
      ) : (
        <div className="px-3.5 py-6 text-center text-[12px] text-muted">
          {t("empty")}
        </div>
      )}
    </div>
  );
}
