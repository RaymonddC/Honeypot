/**
 * Bridge View stat row — QRIS inflow (sim) · bridged to crypto · correlated
 * on-ramps, as three metric cards (mockup .stat-row).
 */

import type { BridgeStats, StatValue } from "@/lib/bridge/types";

function Metric({ label, stat }: { label: string; stat: StatValue }) {
  return (
    <div className="rounded-card border border-line bg-card p-[15px]">
      <div className="eyebrow">{label}</div>
      <div
        className="mt-2 font-mono text-[22px] font-extrabold leading-none tracking-tight tnum"
        style={stat.color ? { color: stat.color } : undefined}
      >
        {stat.value}
        {stat.suffix && (
          <span className="text-[13px] font-bold text-muted"> {stat.suffix}</span>
        )}
      </div>
    </div>
  );
}

export function StatRow({ stats }: { stats: BridgeStats }) {
  return (
    <div className="mb-3.5 grid grid-cols-3 gap-2.5">
      <Metric label="QRIS inflow (sim)" stat={stats.qrisInflow} />
      <Metric label="Bridged to crypto" stat={stats.bridgedToCrypto} />
      <Metric label="Correlated on-ramps" stat={stats.correlatedOnRamps} />
    </div>
  );
}
