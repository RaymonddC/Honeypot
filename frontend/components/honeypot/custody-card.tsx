/**
 * Chain-of-custody card — hash-chained message count, crime class, syndicate
 * link, and the "→ feeds Investigation" hand-off (mockup .kv rows).
 */

import type { CustodyInfo } from "@/lib/honeypot/types";

function KV({
  label,
  value,
  accent,
}: {
  label: string;
  value: string;
  accent?: boolean;
}) {
  return (
    <div className="flex justify-between px-3.5 py-[7px] text-[11.5px]">
      <span className="text-muted">{label}</span>
      <span
        className={`font-mono tnum ${accent ? "text-accent-bright" : "text-fg"}`}
      >
        {value}
      </span>
    </div>
  );
}

export function CustodyCard({ custody }: { custody: CustodyInfo }) {
  return (
    <div className="rounded-card border border-line bg-card pb-1.5">
      <div className="flex items-center justify-between border-b border-line px-3.5 py-3">
        <span className="eyebrow">Chain of custody</span>
        <span
          className={`rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[10.5px] ${
            custody.intact ? "text-accent-bright" : "text-risk-med"
          }`}
        >
          {custody.intact ? "◇ intact" : "◇ unverified"}
        </span>
      </div>
      <div className="pt-1">
        <KV label="Messages logged" value={custody.messagesLogged} />
        <KV label="Crime class" value={custody.crimeClass} />
        <KV label="Syndicate link" value={custody.syndicateLink} />
        <KV label="→ feeds" value="Investigation" accent />
      </div>
    </div>
  );
}
