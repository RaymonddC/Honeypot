"use client";

/**
 * Bridge View stat row — QRIS inflow (sim) · bridged to crypto · correlated
 * on-ramps, as three metric cards with a colored accent + context sublabel.
 */

import { useTranslations } from "next-intl";
import type { BridgeStats, StatValue } from "@/lib/bridge/types";

type MetricMeta = { key: keyof BridgeStats; label: string; sub: string; dot: string };

function Metric({ meta, stat }: { meta: MetricMeta; stat: StatValue }) {
  return (
    <div className="group relative overflow-hidden rounded-card border border-line bg-card p-4 transition-colors hover:border-white/15">
      {/* left accent rail */}
      <span
        className="absolute inset-y-0 left-0 w-[3px]"
        style={{ background: meta.dot }}
        aria-hidden
      />
      <div className="flex items-center gap-1.5">
        <span className="h-1.5 w-1.5 rounded-full" style={{ background: meta.dot }} aria-hidden />
        <div className="eyebrow">{meta.label}</div>
      </div>
      <div
        className="mt-2 font-mono text-[24px] font-extrabold leading-none tracking-tight tnum"
        style={stat.color ? { color: stat.color } : undefined}
      >
        {stat.value}
        {stat.suffix && (
          <span className="text-[13px] font-bold text-muted"> {stat.suffix}</span>
        )}
      </div>
      <div className="mt-1.5 text-[10.5px] text-muted">{meta.sub}</div>
    </div>
  );
}

export function StatRow({ stats }: { stats: BridgeStats }) {
  const t = useTranslations("bridge.statRow");
  const METRICS: MetricMeta[] = [
    { key: "qrisInflow", label: t("qrisInflowLabel"), sub: t("qrisInflowSub"), dot: "#f5a524" },
    { key: "bridgedToCrypto", label: t("bridgedToCryptoLabel"), sub: t("bridgedToCryptoSub"), dot: "#06b6d4" },
    { key: "correlatedOnRamps", label: t("correlatedOnRampsLabel"), sub: t("correlatedOnRampsSub"), dot: "#34d399" },
  ];
  return (
    <div className="mb-3.5 grid grid-cols-3 gap-2.5">
      {METRICS.map((m) => (
        <Metric key={m.key} meta={m} stat={stats[m.key]} />
      ))}
    </div>
  );
}
