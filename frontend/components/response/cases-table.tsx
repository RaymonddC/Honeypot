/**
 * Active cases table (mockup table.cases) — case ref · crime type · funds at
 * risk · status pill (risk-colored; "Frozen" renders on the low/emerald tint).
 */

"use client";

import { useTranslations } from "next-intl";
import type { ActiveCase, CaseRisk } from "@/lib/response/types";

const PILL_STYLES: Record<CaseRisk, string> = {
  high: "bg-risk-high/[.13] text-risk-high",
  med: "bg-risk-med/[.13] text-risk-med",
  low: "bg-risk-low/[.12] text-risk-low",
};

export function CasesTable({ cases }: { cases: ActiveCase[] }) {
  const t = useTranslations("response.casesTable");
  const columns = [t("colCase"), t("colType"), t("colAtRisk"), t("colStatus")];
  return (
    <div className="rounded-card border border-line bg-card">
      <div className="border-b border-line px-3.5 py-[13px]">
        <span className="eyebrow">{t("activeCases")}</span>
      </div>

      {cases.length ? (
        <table className="w-full border-collapse text-[11.5px]">
          <thead>
            <tr>
              {columns.map((h) => (
                <th
                  key={h}
                  className="border-b border-line px-3.5 py-2.5 text-left text-[9.5px] font-bold uppercase tracking-[.07em] text-muted"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {cases.map((c, i) => (
              <tr
                // Refs can repeat (several actions on one case) — index-key
                key={`${c.ref}-${i}`}
                className="group border-b border-line last:border-b-0"
              >
                <td className="px-3.5 py-[11px] font-mono text-muted group-hover:bg-fg/[.015]">
                  {c.ref}
                </td>
                <td className="px-3.5 py-[11px] text-muted group-hover:bg-fg/[.015]">
                  {c.type}
                </td>
                <td className="px-3.5 py-[11px] font-mono tnum text-muted group-hover:bg-fg/[.015]">
                  {c.atRisk}
                </td>
                <td className="px-3.5 py-[11px] group-hover:bg-fg/[.015]">
                  <span
                    className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-[10.5px] font-bold uppercase tracking-[.05em] ${PILL_STYLES[c.risk]}`}
                  >
                    <span
                      className="h-1.5 w-1.5 rounded-full bg-current shadow-[0_0_7px_currentColor]"
                      aria-hidden
                    />
                    {c.statusLabel}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="px-3.5 py-6 text-center text-[11px] text-muted">
          {t("empty")}
        </div>
      )}
    </div>
  );
}
