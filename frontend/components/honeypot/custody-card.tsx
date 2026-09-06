"use client";

/**
 * Chain-of-custody card — hash-chained message count, crime class, syndicate
 * link, and the "→ feeds Investigation" hand-off (mockup .kv rows).
 */

import { useTranslations } from "next-intl";
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
  const t = useTranslations("honeypot.custodyCard");
  return (
    <div className="rounded-card border border-line bg-card pb-1.5">
      <div className="border-b border-line px-3.5 py-3">
        <div className="flex items-center justify-between">
          <span className="eyebrow" title={t("subtitle")}>{t("title")}</span>
          <span
            className={`rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[10.5px] ${
              custody.intact ? "text-accent-bright" : "text-risk-med"
            }`}
          >
            {custody.intact ? t("intact") : t("unverified")}
          </span>
        </div>
        <p className="mt-1 text-[10.5px] leading-snug text-muted">{t("subtitle")}</p>
      </div>
      <div className="pt-1">
        <KV label={t("messagesLogged")} value={custody.messagesLogged} />
        <KV label={t("crimeClass")} value={custody.crimeClass} />
        <KV label={t("syndicateLink")} value={custody.syndicateLink} />
        <KV label={t("feedsLabel")} value={t("feedsValue")} accent />
      </div>
    </div>
  );
}
