"use client";

/**
 * Response Dashboard screen — "from days to minutes", on real case data.
 * Five metric tiles (cases · avg time-to-freeze · funds at risk · funds
 * frozen · recovery rate vs 4.76% baseline) → time-to-freeze trend
 * sparkline + active-cases table. Consumes GET /api/metrics/response?range=
 * and falls back to the local mock dataset when unreachable.
 *
 * Rendered both as the standalone /response page and embedded in the Case
 * File's Response tab (pass ``embedded`` to drop the page chrome).
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { CasesTable } from "@/components/response/cases-table";
import { MetricTiles } from "@/components/response/metric-tiles";
import { TrendSparkline } from "@/components/response/trend-sparkline";
import { fetchResponseMetrics } from "@/lib/response/api";
import type { RangeKey, ResponseMetrics } from "@/lib/response/types";
import { RANGE_LABELS } from "@/lib/response/types";

const RANGES: RangeKey[] = ["7d", "30d", "all"];

export function ResponsePanel({ embedded = false }: { embedded?: boolean }) {
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
        className={`mb-4 flex items-end gap-4 ${embedded ? "justify-end" : "justify-between"}`}
      >
        {!embedded && (
          <div>
            <h1 className="text-xl font-bold tracking-tight">
              Command Center <span className="font-semibold text-muted">· metrics</span>
            </h1>
            <p className="mt-1 text-xs text-muted">
              Agency-wide operational impact across all cases — from days to
              minutes, on real data.
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
          <div className="flex overflow-hidden rounded-lg border border-line bg-card">
            {RANGES.map((r) => (
              <button
                key={r}
                type="button"
                disabled={loading}
                onClick={() => setRange(r)}
                className={`h-[26px] px-3 text-[11px] font-semibold transition-colors disabled:opacity-60 ${
                  r === range
                    ? "bg-accent/10 text-accent-bright"
                    : "text-white/60 hover:bg-white/[.03] hover:text-fg"
                }`}
                aria-pressed={r === range}
              >
                {RANGE_LABELS[r]}
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
              <span className="font-mono text-[30px] font-extrabold leading-none tracking-tight tnum text-accent-bright">
                {data.improvement}
              </span>
              <div className="min-w-0">
                <div className="text-[13.5px] font-semibold text-fg">
                  faster than the manual freeze workflow
                </div>
                <div className="text-[11px] text-muted">
                  avg time-to-freeze vs the &gt;12h manual baseline · {data.trendNow} now
                </div>
              </div>
              <span className="ml-auto hidden flex-none rounded-md border border-accent/30 bg-accent/10 px-2 py-1 font-mono text-[11px] font-semibold text-accent-bright sm:block">
                {data.trendTag}
              </span>
            </div>
          )}

          {/* ── headline metric tiles ──────────────────────────────── */}
          <MetricTiles tiles={data.tiles} />

          {/* ── operations pipeline ────────────────────────────────── */}
          <div className="mb-3.5">
            <div className="eyebrow mb-2">Operations pipeline · {RANGE_LABELS[range].toLowerCase()}</div>
            <div className="grid grid-cols-2 gap-2.5 sm:grid-cols-3 xl:grid-cols-6">
              {data.ops.map((o) => (
                <div key={o.label} className="rounded-card border border-line bg-card p-3">
                  <div className="flex items-center gap-1.5 text-muted">
                    <span className="text-[12px]" aria-hidden>{o.glyph}</span>
                    <span className="text-[9px] uppercase tracking-wide">{o.label}</span>
                  </div>
                  <div
                    className="mt-1.5 font-mono text-[20px] font-bold leading-none tnum"
                    style={o.color ? { color: o.color } : undefined}
                  >
                    {o.value}
                  </div>
                  {o.sub && <div className="mt-1 text-[9.5px] text-muted">{o.sub}</div>}
                </div>
              ))}
            </div>
          </div>

          {/* ── trend + cases table ────────────────────────────────── */}
          <div className="grid grid-cols-1 items-start gap-3.5 lg:grid-cols-[1.4fr_1fr]">
            <div className="rounded-card border border-line bg-card">
              <div className="flex items-center justify-between border-b border-line px-3.5 py-[13px]">
                <span className="eyebrow">Time-to-freeze · trend</span>
                <span className="rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[10.5px] text-accent-bright">
                  {data.trendTag}
                </span>
              </div>
              <div className="p-3.5">
                <TrendSparkline data={data.trend} nowLabel={data.trendNow} />
              </div>
            </div>

            <CasesTable cases={data.cases} />
          </div>
        </>
      ) : (
        <div className="grid h-[420px] animate-pulse place-items-center rounded-card border border-line bg-card text-[11px] text-muted">
          Aggregating case · freeze · notification read-model…
        </div>
      )}

      {!embedded && (
        <div className="mt-5 border-t border-line pt-3.5 text-[10.5px] leading-relaxed text-muted">
          All figures are computed from real{" "}
          <b className="text-white/60">cases · action_documents · notifications</b>{" "}
          rows — no vanity numbers. POC data flows through the same pipeline, so
          the demo run populates this dashboard itself. Recovery rate is
          benchmarked against the <b className="text-white/60">4.76% IASC baseline</b>;
          time-to-freeze against the &gt;12h manual workflow.
        </div>
      )}
    </div>
  );
}
