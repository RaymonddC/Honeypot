"use client";

/**
 * Chain-of-custody card — hash-chained message count, crime class, syndicate
 * link, and the "→ feeds Investigation" hand-off (mockup .kv rows).
 */

import { useTranslations } from "next-intl";
import type { CustodyInfo } from "@/lib/honeypot/types";

/** One key/value row. `tabular` opts a row into tabular numerals so digits
 *  line up down the card; word values (crime class, hand-off target) leave it
 *  off. */
function KV({
  label,
  value,
  accent,
  tabular,
}: {
  label: string;
  value: React.ReactNode;
  accent?: boolean;
  tabular?: boolean;
}) {
  return (
    <div className="flex justify-between gap-3 px-3.5 py-[7px] text-[12px]">
      <span className="flex-none text-muted">{label}</span>
      <span
        className={`min-w-0 truncate text-right ${tabular ? "tnum" : ""} ${
          accent ? "text-accent-bright" : "text-fg"
        }`}
      >
        {value}
      </span>
    </div>
  );
}

/**
 * Crime typology key → label. Unknown keys are shown verbatim (de-underscored)
 * rather than dropped: a classification the UI doesn't recognise is still
 * information, and inventing "—" for it would hide what the backend said.
 */
function crimeClassLabel(
  key: string,
  t: ReturnType<typeof useTranslations>,
): string {
  if (!key || key === "—") return "—";
  const known = ["investment_scam", "judol_deposit", "crypto_phishing", "romance"];
  return known.includes(key) ? t(`crimeTypes.${key}`) : key.replace(/_/g, " ");
}

export function CustodyCard({ custody }: { custody: CustodyInfo }) {
  const t = useTranslations("honeypot.custodyCard");
  return (
    <div className="rounded-card border border-line bg-card pb-1.5">
      <div className="border-b border-line px-3.5 py-3">
        <div className="flex items-center justify-between">
          <span className="eyebrow" title={t("subtitle")}>{t("title")}</span>
          {/* A status word, not data — same treatment as every other status
              chip in the app (mode badge, data-source, dispatch log). */}
          <span
            className={`rounded-md border border-line bg-elevated px-2 py-0.5 text-[12px] ${
              custody.intact ? "text-accent-bright" : "text-risk-med"
            }`}
          >
            {custody.intact ? t("intact") : t("unverified")}
          </span>
        </div>
        <p className="mt-1 text-[12px] leading-snug text-muted">{t("subtitle")}</p>
      </div>
      <div className="pt-1">
        {/* the count is the figure; "hash-chained" is a label beside it */}
        <KV
          label={t("messagesLogged")}
          value={
            <>
              <span className="tnum">{custody.messagesLogged}</span>
              {custody.intact && <span className="text-muted"> · {t("hashChained")}</span>}
            </>
          }
        />
        <KV label={t("crimeClass")} value={crimeClassLabel(custody.crimeClass, t)} />
        <KV label={t("syndicateLink")} value={custody.syndicateLink} tabular />
        <KV label={t("feedsLabel")} value={t("feedsValue")} accent />
      </div>
    </div>
  );
}
