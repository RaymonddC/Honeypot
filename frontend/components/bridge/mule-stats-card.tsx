/**
 * Mule network stats card — Louvain clusters, mule accounts, shell merchants,
 * correlation window, as a compact 2×2 tile grid.
 */

import type { MuleNetworkStats } from "@/lib/bridge/types";

export function MuleStatsCard({ mules }: { mules: MuleNetworkStats }) {
  const tiles: { label: string; value: string }[] = [
    { label: "Clusters", value: mules.clusters },
    { label: "Mule accounts", value: mules.muleAccounts },
    { label: "Shell merchants", value: mules.shellMerchants },
    { label: "Corr. window", value: mules.correlationWindow },
  ];
  return (
    <div className="rounded-card border border-line bg-card">
      <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
        <span className="eyebrow">Mule network</span>
        <span className="rounded-md border border-line bg-elevated px-1.5 py-0.5 text-[9.5px] uppercase tracking-wide text-muted">
          Louvain
        </span>
      </div>
      <div className="grid grid-cols-2 gap-px bg-line">
        {tiles.map((t) => (
          <div key={t.label} className="bg-card px-3.5 py-2.5">
            <div className="font-mono text-[19px] font-bold leading-none tnum text-fg">
              {t.value}
            </div>
            <div className="mt-1 text-[10px] uppercase tracking-wide text-muted">
              {t.label}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
