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
import { MuleStatsCard } from "@/components/bridge/mule-stats-card";
import { OnRampFeed } from "@/components/bridge/onramp-feed";
import { StatRow } from "@/components/bridge/stat-row";
import { TraceReport } from "@/components/bridge/trace-report";
import { fetchBridgeData } from "@/lib/bridge/api";
import type { BridgeData } from "@/lib/bridge/types";

// Sankey colour key (fiat → crypto ramp) — shown under the chart.
const LEGEND: Array<[string, string]> = [
  ["#f5a524", "QRIS / fiat"],
  ["#f59e0b", "Mule accounts"],
  ["#06b6d4", "Exchange"],
  ["#0ea5e9", "USDT wallets"],
  ["#3b82f6", "Foreign"],
];

const SankeyChart = dynamic(
  () =>
    import("@/components/bridge/sankey-chart").then((m) => ({
      default: m.SankeyChart,
    })),
  {
    ssr: false,
    loading: () => <div className="h-[460px] animate-pulse rounded-lg bg-white/[.02]" />,
  },
);

export function BridgePanel({
  embedded = false,
  onOpenTakedown,
  caseTitle,
}: {
  embedded?: boolean;
  /** Handoff: score a wallet in Takedown (the top on-ramp's, or a specific one). */
  onOpenTakedown?: (addr?: string) => void;
  /** Active case name — stamped on the downloadable trace report. */
  caseTitle?: string;
}) {
  const router = useRouter();
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
        className={`mb-4 flex items-end gap-4 ${embedded ? "justify-end" : "justify-between"}`}
      >
        {!embedded && (
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              Bridge View{" "}
              <span className="font-semibold text-muted">· BridgeWatch</span>
            </h1>
            <p className="mt-1 text-xs text-muted">
              The fiat→crypto on-ramp — where dirty rupiah becomes USDT. Case
              template: PT A2Z (Rp 530 M · 4,656 accounts · 22 banks).
            </p>
          </div>
        )}
        <div className="flex items-center gap-2">
          {data && (
            <span
              className={`rounded-md border px-2 py-0.5 font-mono text-[10.5px] font-semibold ${
                data.source === "api"
                  ? "border-accent/30 bg-accent/10 text-accent-bright"
                  : "border-risk-med/30 bg-risk-med/10 text-risk-med"
              }`}
              title={
                data.source === "api"
                  ? "Live backend API"
                  : "Backend unreachable — rendering local demo dataset"
              }
            >
              {data.source === "api" ? "● live api" : "● offline · mock"}
            </span>
          )}
          <button
            type="button"
            disabled={!data}
            onClick={() => setShowReport(true)}
            title="View & download the fiat→crypto trace report"
            className="h-8 rounded-lg border border-white/10 bg-elevated px-3.5 text-xs font-semibold text-fg transition-colors hover:bg-white/[.07] disabled:opacity-50"
          >
            ⧉ View report
          </button>
          <button
            type="button"
            disabled={loading}
            onClick={() => void load(true)}
            className="h-8 rounded-lg border border-white/10 bg-elevated px-3.5 text-xs font-semibold text-fg transition-colors hover:bg-white/[.07] disabled:opacity-50"
          >
            {loading ? "Generating…" : "Regenerate feed"}
          </button>
          <button
            type="button"
            onClick={() => goTakedown(data?.alerts.find((a) => a.wallet)?.wallet)}
            title={
              data?.alerts.find((a) => a.wallet)?.wallet
                ? "Score the top on-ramp's wallet in Takedown"
                : "Score wallets in Takedown"
            }
            className="h-8 rounded-lg bg-accent px-3.5 text-xs font-semibold text-[#04140d] shadow-[0_0_16px_rgba(16,185,129,.28)] transition-colors hover:bg-accent-bright"
          >
            Score wallets in Takedown →
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
                <span className="eyebrow">Money flow · fiat → crypto</span>
                <span className="hidden text-[10px] text-muted sm:block">
                  ribbon width = volume · hover to isolate a path
                </span>
              </div>
              {/* split-screen labels: fiat │ bridge │ crypto */}
              <div className="grid grid-cols-3 px-1.5 pb-1 text-[10px] font-bold uppercase tracking-[.08em]">
                <span className="text-muted">Fiat · simulated</span>
                <span className="text-center text-risk-med">Bridge</span>
                <span className="text-right text-[#06b6d4]">
                  Crypto · real TRON
                </span>
              </div>
              <SankeyChart data={data.sankey} />
              {/* legend + interaction hint */}
              <div className="mt-1 flex flex-wrap items-center gap-x-3.5 gap-y-1 border-t border-line px-1 pt-2.5 text-[10px] text-muted">
                {LEGEND.map(([c, l]) => (
                  <span key={l} className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: c }} aria-hidden />
                    {l}
                  </span>
                ))}
                <span className="ml-auto text-muted/70">Hover a node or link to isolate a path</span>
              </div>
            </div>

            <div>
              <OnRampFeed alerts={data.alerts} onTrace={goTakedown} />
              <MuleStatsCard mules={data.mules} />
            </div>
          </div>
        </>
      ) : (
        <div className="grid h-[520px] animate-pulse place-items-center rounded-card border border-line bg-card text-[11px] text-muted">
          Correlating fiat↔crypto flows…
        </div>
      )}

      {!embedded && (
        <div className="mt-5 border-t border-line pt-3.5 text-[10.5px] leading-relaxed text-muted">
          Fiat side is <b className="text-white/60">synthetic</b> (PT A2Z params
          / PaySim) — real bank &amp; QRIS data isn&apos;t public; crypto side is{" "}
          <b className="text-white/60">real</b> TRON. The adapter swaps to a live
          bank feed post-MoU without touching this view.
        </div>
      )}

      {showReport && data && (
        <TraceReport data={data} caseTitle={caseTitle} onClose={() => setShowReport(false)} />
      )}
    </div>
  );
}
