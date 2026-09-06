"use client";

/**
 * Bridge View screen (TRACE / BridgeWatch) — the fiat→crypto on-ramp.
 * Stat row → split-screen Sankey (fiat · sim │ bridge │ crypto · real TRON)
 * → confidence-ranked suspected-on-ramp feed + mule network stats.
 * Consumes the backend API (POST /bridge/simulate + GET sankey/correlations/
 * mules) and falls back to the local mock dataset when unreachable.
 *
 * Rendered both as the standalone /bridge page and embedded in the Case
 * File's Bridge tab (pass ``embedded`` to drop the page chrome).
 */

import dynamic from "next/dynamic";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { MuleStatsCard } from "@/components/bridge/mule-stats-card";
import { OnRampFeed } from "@/components/bridge/onramp-feed";
import { StatRow } from "@/components/bridge/stat-row";
import { TraceReport } from "@/components/bridge/trace-report";
import { fetchBridgeData } from "@/lib/bridge/api";
import type { BridgeData } from "@/lib/bridge/types";
import type { CaseBridge } from "@/lib/demo/golden-thread";
import { idrShort, usdtShort } from "@/lib/demo/golden-thread";

const SankeyChart = dynamic(
  () =>
    import("@/components/bridge/sankey-chart").then((m) => ({
      default: m.SankeyChart,
    })),
  {
    ssr: false,
    loading: () => <div className="h-[460px] animate-pulse rounded-lg bg-fg/[.02]" />,
  },
);

export function BridgePanel({
  embedded = false,
  onOpenTakedown,
  caseTitle,
  caseBridge,
}: {
  embedded?: boolean;
  /** Handoff: score a wallet in Takedown (the top on-ramp's, or a specific one). */
  onOpenTakedown?: (addr?: string) => void;
  /** Active case name — stamped on the downloadable trace report. */
  caseTitle?: string;
  /** The case's own fiat→crypto on-ramp edge (bank account → collection wallet). */
  caseBridge?: CaseBridge | null;
}) {
  const t = useTranslations("bridge.panel");
  const router = useRouter();
  // Sankey colour key (fiat → crypto ramp) — shown under the chart.
  const legend: Array<[string, string]> = [
    ["#7a7f87", t("legend.qrisFiat")],
    ["#9aa0a8", t("legend.muleAccounts")],
    ["#0088e6", t("legend.exchange")],
    ["#0099ff", t("legend.usdtWallets")],
    ["#4b5563", t("legend.foreign")],
  ];
  const [data, setData] = useState<BridgeData | null>(null);
  const [loading, setLoading] = useState(true);
  const [showReport, setShowReport] = useState(false);
  const loadSeq = useRef(0);

  // Hand a specific wallet to Takedown: in-case via the callback, else route out.
  const goTakedown = useCallback(
    (addr?: string) => {
      if (onOpenTakedown) onOpenTakedown(addr);
      else
        router.push(
          addr ? `/investigation?address=${encodeURIComponent(addr)}` : "/investigation",
        );
    },
    [onOpenTakedown, router],
  );

  const load = useCallback(async (simulate: boolean) => {
    const seq = ++loadSeq.current;
    setLoading(true);
    const result = await fetchBridgeData({ simulate });
    if (seq !== loadSeq.current) return; // superseded
    setData(result);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load(false);
  }, [load]);

  return (
    <div className={embedded ? "" : "mx-auto max-w-[1200px]"}>
      {/* ── header ─────────────────────────────────────────────────── */}
      <div
        className={`mb-5 flex flex-col items-start gap-3 sm:flex-row sm:items-start sm:gap-4 ${embedded ? "sm:justify-end" : "sm:justify-between"}`}
      >
        {!embedded && (
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              {t("title")}{" "}
              <span className="text-base font-semibold text-muted">· {t("titleModule")}</span>
            </h1>
            <p className="mt-1.5 max-w-[65ch] text-[13px] leading-relaxed text-muted">
              {t("pageLead")}
            </p>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {/* data-source is plumbing — kept small/muted so it doesn't compete
              with the stat tiles and Sankey below */}
          {data && (
            <span
              className={`rounded-md border px-1.5 py-0.5 font-mono text-[9.5px] ${
                data.source === "api"
                  ? "border-line bg-elevated text-muted"
                  : "border-risk-med/30 bg-risk-med/10 text-risk-med"
              }`}
              title={
                data.source === "api"
                  ? t("liveApiTitle")
                  : t("offlineMockTitle")
              }
            >
              {data.source === "api" ? t("liveApi") : t("offlineMock")}
            </span>
          )}
          <button
            type="button"
            disabled={!data}
            onClick={() => setShowReport(true)}
            title={t("viewReportTitle")}
            className="h-8 rounded-lg border border-line bg-elevated px-3.5 text-xs font-semibold text-fg transition-colors hover:bg-fg/[.07] disabled:opacity-50"
          >
            {t("viewReport")}
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={() => void load(true)}
            className="h-8 rounded-lg border border-line bg-elevated px-3.5 text-xs font-semibold text-fg transition-colors hover:bg-fg/[.07] disabled:opacity-50"
          >
            {loading ? t("generating") : t("regenerateFeed")}
          </button>
          <button
            type="button"
            onClick={() => goTakedown(data?.alerts.find((a) => a.wallet)?.wallet)}
            title={
              data?.alerts.find((a) => a.wallet)?.wallet
                ? t("scoreTopOnRampTitle")
                : t("scoreWalletsTitle")
            }
            className="h-8 rounded-full bg-accent px-3.5 text-xs font-semibold text-[#090909] shadow-[0_0_16px_rgba(255, 255, 255,.28)] transition-colors hover:bg-accent-bright"
          >
            {t("scoreWallets")}
          </button>
        </div>
      </div>

      {data && !loading ? (
        <>
          {/* ── stat row ───────────────────────────────────────────── */}
          <StatRow stats={data.stats} />

          {/* ── sankey + right rail ────────────────────────────────── */}
          <div className="grid grid-cols-1 items-start gap-3.5 lg:grid-cols-[1fr_300px]">
            <div className="rounded-card border border-line bg-card px-4 pb-3 pt-3.5">
              {/* card header — what the diagram shows + how to read it */}
              <div className="mb-2.5 flex items-baseline justify-between gap-3 border-b border-line px-1.5 pb-2.5">
                <span className="eyebrow">{t("moneyFlowEyebrow")}</span>
                <span className="hidden text-[10px] text-muted sm:block">
                  {t("ribbonHint")}
                </span>
              </div>
              {/* split-screen labels: fiat │ bridge │ crypto */}
              <div className="grid grid-cols-3 px-1.5 pb-1 text-[10px] font-bold uppercase tracking-[.08em]">
                <span className="text-muted">{t("fiatSimulated")}</span>
                <span className="text-center text-risk-med">{t("bridgeLabel")}</span>
                <span className="text-right text-[#0099ff]">
                  {t("cryptoRealTron")}
                </span>
              </div>
              <SankeyChart data={data.sankey} />
              {/* legend + interaction hint */}
              <div className="mt-1 flex flex-wrap items-center gap-x-3.5 gap-y-1 border-t border-line px-1 pt-2.5 text-[10px] text-muted">
                {legend.map(([c, l]) => (
                  <span key={l} className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} aria-hidden />
                    {l}
                  </span>
                ))}
                <span className="ml-auto text-muted/70">{t("hoverIsolateHint")}</span>
              </div>
            </div>

            <div>
              {caseBridge && (
                <div className="mb-3.5 rounded-card border border-accent/30 bg-accent/[.06]">
                  <div className="flex items-center justify-between border-b border-accent/20 px-3.5 py-2.5">
                    <span className="eyebrow text-accent-bright">{t("caseOnRamp")}</span>
                    <span className="rounded-full border border-accent/30 bg-accent/10 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-accent-bright">
                      conf {caseBridge.confidence.toFixed(2)}
                    </span>
                  </div>
                  <div className="px-3.5 py-3">
                    {/* fiat account → crypto wallet, the bridge the honeypot surfaced */}
                    <div className="flex items-center gap-2 text-[11px]">
                      <span className="rounded-md bg-[#8b93a1]/15 px-1.5 py-0.5 font-mono text-[10.5px] text-[#8b93a1]">
                        {caseBridge.bankLabel}
                      </span>
                      <span className="text-muted" aria-hidden>→</span>
                      <span className="min-w-0 flex-1 truncate rounded-md bg-[#0099ff]/15 px-1.5 py-0.5 font-mono text-[10.5px] text-[#33adff]">
                        {caseBridge.wallet}
                      </span>
                    </div>
                    {caseBridge.bankHolder && (
                      <div className="mt-1 text-[10px] text-muted">{t("bankHolderPrefix", { holder: caseBridge.bankHolder })}</div>
                    )}
                    {caseBridge.amountUsdt > 0 && (
                      <div className="mt-2 font-mono text-[11px] text-fg">
                        {idrShort(caseBridge.amountIdr)}{" "}
                        <span className="text-muted">≈</span>{" "}
                        <b className="text-accent-bright">{usdtShort(caseBridge.amountUsdt)}</b>
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={() => goTakedown(caseBridge.wallet)}
                      className="mt-2.5 h-7 w-full rounded-full bg-accent px-3 text-[11px] font-semibold text-[#090909] transition-colors hover:bg-accent-bright"
                    >
                      {t("traceThisWallet")}
                    </button>
                  </div>
                </div>
              )}
              <OnRampFeed alerts={data.alerts} onTrace={goTakedown} />
              <MuleStatsCard mules={data.mules} />
            </div>
          </div>
        </>
      ) : (
        <div className="grid h-[520px] animate-pulse place-items-center rounded-card border border-line bg-card text-[11px] text-muted">
          {t("loadingState")}
        </div>
      )}

      {!embedded && (
        <div className="mt-5 border-t border-line pt-3.5 text-[10.5px] leading-relaxed text-muted">
          {t.rich("footerNote", {
            b: (chunks) => <b className="text-fg">{chunks}</b>,
          })}
        </div>
      )}

      {showReport && data && (
        <TraceReport data={data} caseTitle={caseTitle} onClose={() => setShowReport(false)} />
      )}
    </div>
  );
}
