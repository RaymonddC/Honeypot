/**
 * Mule network stats card — Louvain clusters, mule accounts, shell merchants,
 * correlation window (mockup .kv rows).
 */

import type { MuleNetworkStats } from "@/lib/bridge/types";

function KV({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between px-3.5 py-[7px] text-[11.5px]">
      <span className="text-muted">{label}</span>
      <span className="font-mono tnum text-fg">{value}</span>
    </div>
  );
}

export function MuleStatsCard({ mules }: { mules: MuleNetworkStats }) {
  return (
    <div className="rounded-card border border-line bg-card pb-1.5">
      <div className="border-b border-line px-3.5 py-3">
        <span className="eyebrow">Mule network</span>
      </div>
      <div className="pt-1">
        <KV label="Clusters (Louvain)" value={mules.clusters} />
        <KV label="Mule accounts" value={mules.muleAccounts} />
        <KV label="Shell merchants" value={mules.shellMerchants} />
        <KV label="Correlation window" value={mules.correlationWindow} />
      </div>
    </div>
  );
}
