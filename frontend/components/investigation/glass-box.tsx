"use client";

/**
 * Glass Box — stepped tool-call reasoning trace (pattern ported from ELSA's
 * ReasoningPanel). Renders the risk endpoint's `reasoning` for the selected
 * wallet: step number, tool call, detail, duration — with a colored verdict
 * on the final assess() step.
 */

import { useTranslations } from "next-intl";
import type { ReasoningStep, WalletDetail } from "@/lib/investigation/types";
import { RISK_COLORS } from "@/lib/investigation/types";

const VERDICT_TEXT: Record<string, string> = {
  low: "LOW",
  medium: "MEDIUM",
  high: "HIGH",
  exchange: "EXCHANGE",
};

function Step({ s }: { s: ReasoningStep }) {
  return (
    <div className="flex items-baseline gap-2.5 border-b border-line px-3.5 py-[9px] text-[11.5px] last:border-b-0">
      <span className="grid h-[18px] w-[18px] flex-none translate-y-0.5 place-items-center self-center rounded-[5px] bg-accent/10 font-mono text-[10px] font-bold text-accent-bright">
        {s.step}
      </span>
      <span className="flex-none font-mono text-[11px] text-accent-bright">
        {s.tool}
      </span>
      <span className="min-w-0 text-white/60">
        ·{" "}
        {s.verdict && (
          <b
            className="font-bold"
            style={{ color: RISK_COLORS[s.verdict] }}
          >
            {VERDICT_TEXT[s.verdict]}
          </b>
        )}
        {s.verdict ? " — " : ""}
        {s.detail}
      </span>
      <span className="ml-auto flex-none font-mono text-[10px] tnum text-muted">
        {s.duration ?? "—"}
      </span>
    </div>
  );
}

export function GlassBox({ detail }: { detail: WalletDetail | null }) {
  const t = useTranslations("investigation.glassBox");
  return (
    <section className="mt-3.5 rounded-card border border-line bg-card">
      <div className="flex items-center justify-between border-b border-line px-3.5 py-3">
        <span className="eyebrow text-accent-bright" style={{ color: "#34d399" }}>
          {t("eyebrow")}
        </span>
        {detail && (
          <span className="rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[10.5px] tnum text-white/60">
            {t("confidence", { confidence: detail.confidence.toFixed(2) })}
          </span>
        )}
      </div>
      {detail && detail.reasoning.length > 0 ? (
        detail.reasoning.map((s) => <Step key={s.step} s={s} />)
      ) : (
        <div className="px-3.5 py-6 text-center text-[11px] text-muted">
          {t("empty")}
        </div>
      )}
    </section>
  );
}
