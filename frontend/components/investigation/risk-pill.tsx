"use client";

import { useTranslations } from "next-intl";
import type { RiskLevel } from "@/lib/investigation/types";
import { RISK_LABELS } from "@/lib/investigation/types";

const STYLES: Record<RiskLevel, string> = {
  high: "bg-risk-high/[.13] text-risk-high",
  medium: "bg-risk-med/[.13] text-risk-med",
  low: "bg-risk-low/[.12] text-risk-low",
  exchange: "bg-[#06b6d4]/[.13] text-[#06b6d4]",
};

export function RiskPill({
  risk,
  score,
}: {
  risk: RiskLevel;
  score?: number;
}) {
  const t = useTranslations("investigation.riskPill");
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10.5px] font-bold uppercase tracking-[.05em] ${STYLES[risk]}`}
    >
      <span
        className="h-1.5 w-1.5 rounded-full bg-current shadow-[0_0_7px_currentColor]"
        aria-hidden
      />
      {risk === "exchange" ? t("exchange") : RISK_LABELS[risk]}
      {risk !== "exchange" && score != null && (
        <span className="tnum">{score.toFixed(2)}</span>
      )}
    </span>
  );
}
