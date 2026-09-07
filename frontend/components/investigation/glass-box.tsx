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
    <div className="flex items-baseline gap-2.5 border-b border-line px-3.5 py-[9px] text-[12px] last:border-b-0">
      <span className="grid h-[18px] w-[18px] flex-none translate-y-0.5 place-items-center self-center rounded-[5px] bg-accent/10 text-[12px] font-bold text-accent-bright">
        {s.step}
      </span>
      <span className="flex-none text-[12px] text-accent-bright">
        {s.tool}
      </span>
      <span className="min-w-0 text-muted">
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
      <span className="ml-auto flex-none text-[12px] tnum text-muted">
        {s.duration ?? "—"}
      </span>
    </div>
  );
}

export function GlassBox({ detail }: { detail: WalletDetail | null }) {
  const t = useTranslations("investigation.glassBox");
  return (
    <section className="mt-3.5 rounded-card border border-line bg-card">
      <div className="border-b border-line px-3.5 py-3">
        <div className="flex items-center justify-between">
          <span className="eyebrow text-accent-bright" style={{ color: "#0099ff" }}>
            {t("eyebrow")}
          </span>
          {detail && (
            <span className="rounded-md border border-line bg-elevated px-2 py-0.5 text-[12px] tnum text-muted">
              {t("confidence", { confidence: detail.confidence.toFixed(2) })}
            </span>
          )}
        </div>
        <p className="mt-1 text-[12px] leading-snug text-muted">{t("eyebrowHint")}</p>
      </div>
      {detail && detail.reasoning.length > 0 ? (
        detail.reasoning.map((s) => <Step key={s.step} s={s} />)
      ) : (
        <div className="px-3.5 py-6 text-center text-[12px] text-muted">
          {t("empty")}
        </div>
      )}
    </section>
  );
}
