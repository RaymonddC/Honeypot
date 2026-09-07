"use client";

/**
 * Response Dashboard screen — "from days to minutes", on real case data.
 * Five metric tiles (cases · avg time-to-freeze · funds at risk · funds
 * frozen · freeze rate) → time-to-freeze trend
 * sparkline + active-cases table. Consumes GET /api/metrics/response?range=
 * and falls back to the local mock dataset when unreachable.
 *
 * Rendered both as the standalone /response page and embedded in the Case
 * File's Response tab (pass ``embedded`` to drop the page chrome).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { CasesTable } from "@/components/response/cases-table";
import { DispatchLog } from "@/components/response/dispatch-log";
import { MetricTiles } from "@/components/response/metric-tiles";
import { TrendSparkline } from "@/components/response/trend-sparkline";
import { fetchResponseMetrics } from "@/lib/response/api";
import type { RangeKey, ResponseMetrics } from "@/lib/response/types";

const RANGES: RangeKey[] = ["7d", "30d", "all"];

export function ResponsePanel({ embedded = false }: { embedded?: boolean }) {
  const t = useTranslations("response.panel");
  // Ops labels live in i18n, keyed by OpsStat.key (the data layer sends no text).
  const tOps = useTranslations("response.ops");
  const [data, setData] = useState<ResponseMetrics | null>(null);
  const [range, setRange] = useState<RangeKey>("30d");
  const [loading, setLoading] = useState(true);
  const loadSeq = useRef(0);

  const load = useCallback(async (r: RangeKey) => {
    const seq = ++loadSeq.current;
    setLoading(true);
    const result = await fetchResponseMetrics(r);
    if (seq !== loadSeq.current) return; // superseded
    setData(result);
    setLoading(false);
  }, []);

  useEffect(() => {
    void load(range);
  }, [load, range]);

  return (
    <div className={embedded ? "" : "mx-auto max-w-[1200px]"}>
      {/* ── header ─────────────────────────────────────────────────── */}
      <div
        className={`mb-5 flex flex-col items-start gap-3 sm:flex-row sm:items-start sm:gap-4 ${embedded ? "sm:justify-end" : "sm:justify-between"}`}
      >
        {!embedded && (
          <div>
            <h1 className="text-2xl font-bold tracking-tight">
              {t("title")} <span className="text-base font-semibold text-muted">· {t("titleModule")}</span>
            </h1>
            <p className="mt-1.5 max-w-[62ch] text-[13px] leading-relaxed text-muted">
              {t("subtitle")}
            </p>
          </div>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {/* data-source is plumbing — de-emphasized so the hero metric and
              tiles below keep the visual weight */}
          {data && (
            <span
              className={`rounded-md border px-1.5 py-0.5 text-[12px] ${
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
          <div className="flex overflow-hidden rounded-lg border border-line bg-card">
            {RANGES.map((r) => (
              <button
                key={r}
                type="button"
                disabled={loading}
                onClick={() => setRange(r)}
                className={`h-[26px] px-3 text-[12px] font-semibold transition-colors disabled:opacity-60 ${
                  r === range
                    ? "bg-accent/10 text-accent-bright"
                    : "text-muted hover:bg-fg/[.03] hover:text-fg"
                }`}
                aria-pressed={r === range}
              >
                {t(`range.${r}`)}
              </button>
            ))}
          </div>
        </div>
      </div>

      {data && !loading ? (
        <>
          {/* ── hero: response-time improvement vs manual ──────────── */}
          {data.improvement && (
            <div className="mb-3.5 flex items-center gap-3.5 rounded-card border border-accent/25 bg-accent/[.06] px-4 py-3">
              <span className="text-[30px] font-extrabold leading-none tracking-tight tnum text-accent-bright">
                {data.improvement}
              </span>
              <div className="min-w-0">
                <div className="text-[13.5px] font-semibold text-fg">
                  {t("heroFasterSuffix")}
                </div>
                <div className="text-[12px] text-muted">
                  {t("heroBaseline", { trendNow: data.trendNow })}
                </div>
              </div>
              <span className="ml-auto hidden flex-none rounded-full border border-accent/30 bg-accent/10 px-2 py-1 text-[12px] font-semibold text-accent-bright sm:block">
                {data.trendTag}
              </span>
            </div>
          )}

          {/* ── headline metric tiles ──────────────────────────────── */}
          <MetricTiles tiles={data.tiles} />

          {/* ── operations pipeline ────────────────────────────────── */}
          <div className="mb-3.5">
            <div className="eyebrow mb-2">{t("opsPipelineEyebrow", { range: t(`range.${range}`).toLowerCase() })}</div>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-6">
              {data.ops.map((o) => (
                <div key={o.key} className="rounded-card border border-line bg-card p-3">
                  <div className="flex items-center gap-1.5 text-muted">
                    <span className="text-[12px]" aria-hidden>{o.glyph}</span>
                    <span className="text-[12px] uppercase tracking-wide">
                      {tOps(`${o.key}.label`)}
                    </span>
                  </div>
                  <div
                    className="mt-1.5 text-[20px] font-bold leading-none tnum"
                    style={o.color ? { color: o.color } : undefined}
                  >
                    {o.value}
                  </div>
                  <div className="mt-1 text-[12px] text-muted">{tOps(`${o.key}.sub`)}</div>
                </div>
              ))}
            </div>
          </div>

          {/* ── trend + cases table ────────────────────────────────── */}
          <div className="grid grid-cols-1 items-start gap-3.5 lg:grid-cols-[1.4fr_1fr]">
            <div className="rounded-card border border-line bg-card">
              <div className="flex items-center justify-between border-b border-line px-3.5 py-[13px]">
                <span className="eyebrow">{t("trendEyebrow")}</span>
                <span className="rounded-md border border-line bg-elevated px-2 py-0.5 text-[12px] text-accent-bright">
                  {data.trendTag}
                </span>
              </div>
              <div className="p-3.5">
                <TrendSparkline data={data.trend} nowLabel={data.trendNow} />
              </div>
            </div>

            <CasesTable cases={data.cases} />
          </div>

          {/* ── dispatch log (agency outbox) ───────────────────────── */}
          <div className="mt-3.5">
            <DispatchLog />
          </div>
        </>
      ) : (
        <div className="grid h-[420px] animate-pulse place-items-center rounded-card border border-line bg-card text-[12px] text-muted">
          {t("loadingState")}
        </div>
      )}

      {!embedded && (
        <div className="mt-5 border-t border-line pt-3.5 text-[12px] leading-relaxed text-muted">
          {t.rich("footerNote", {
            b: (chunks) => <b className="text-fg">{chunks}</b>,
          })}
        </div>
      )}
    </div>
  );
}
