"use client";

/**
 * Bank-account flow status (TRACE) — a READ-ONLY view of the case's tracked
 * accounts and whether each shows up in the current bridge flow. Accounts are
 * entered elsewhere (Case File → Overview, or Intake); here we only surface the
 * `in flow` signal, so there's a single place to add data and no duplicate form.
 *
 * Consumes GET /api/bridge/accounts (WatchlistedAccount + seen_in_flow).
 */

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useCases } from "@/components/cases/case-provider";
import {
  listWatchlistAccounts,
  type WatchlistedAccount,
} from "@/lib/casedata/api";

export function AccountWatchlist() {
  const t = useTranslations("bridge.accountWatchlist");
  const { activeCaseId } = useCases();
  const [items, setItems] = useState<WatchlistedAccount[]>([]);

  const refresh = useCallback(async () => {
    try {
      setItems(await listWatchlistAccounts(activeCaseId));
    } catch {
      /* unauthenticated or backend down — leave list empty */
    }
  }, [activeCaseId]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const inFlow = items.filter((a) => a.seen_in_flow).length;
  // Surface the ones that appear in the flow first — that's the useful signal.
  const sorted = [...items].sort(
    (a, b) => Number(b.seen_in_flow) - Number(a.seen_in_flow),
  );

  return (
    <div className="mt-3 rounded-card border border-line bg-card">
      <div className="flex items-center justify-between border-b border-line px-3.5 py-2.5">
        <span className="eyebrow">{t("title")}</span>
        {items.length > 0 && (
          <span
            className="rounded-md border border-line bg-elevated px-1.5 py-0.5 font-mono text-[12px] text-muted"
            title={t("inFlowTitle")}
          >
            {t("inFlowCount", { inFlow, total: items.length })}
          </span>
        )}
      </div>

      <div className="p-2">
        {items.length === 0 ? (
          <p className="px-1.5 py-2 text-[12px] leading-relaxed text-muted">
            {t.rich("empty", { b: (chunks) => <b className="text-fg">{chunks}</b> })}
          </p>
        ) : (
          <ul className="space-y-1">
            {sorted.map((a) => (
              <li
                key={a.id}
                className="flex items-center justify-between gap-2 rounded-lg bg-elevated px-2.5 py-1.5"
              >
                <div className="min-w-0">
                  <div className="truncate font-mono text-[12px] text-fg">
                    {a.bank_name} {a.account_number}
                  </div>
                  <div className="truncate text-[12px] text-muted">
                    {a.holder_name ? t("holderPrefix", { holder: a.holder_name }) : ""}
                    {a.category}
                  </div>
                </div>
                {a.seen_in_flow ? (
                  <span
                    className="flex-none rounded-md border border-risk-high/40 bg-risk-high/10 px-1.5 py-0.5 text-[12px] font-bold uppercase tracking-wide text-risk-high"
                    title={t("inFlowBadgeTitle")}
                  >
                    {t("inFlowBadge")}
                  </span>
                ) : (
                  <span
                    className="flex-none rounded-md border border-line bg-card px-1.5 py-0.5 text-[12px] uppercase tracking-wide text-muted"
                    title={t("watchBadgeTitle")}
                  >
                    {t("watchBadge")}
                  </span>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
