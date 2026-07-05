"use client";

/**
 * Right-rail wallet detail card: risk gauge, KV rows, and the
 * Overview (patterns + 12 features) / Transactions tabs.
 */

import { useState } from "react";
import type { WalletDetail } from "@/lib/investigation/types";
import { RISK_COLORS } from "@/lib/investigation/types";
import { RiskPill } from "./risk-pill";

type Tab = "overview" | "transactions";

function gaugeFill(d: WalletDetail): { width: string; background: string } {
  if (d.risk === "exchange")
    return { width: "100%", background: RISK_COLORS.exchange };
  if (d.score > 0.7)
    return {
      width: `${d.score * 100}%`,
      background: `linear-gradient(90deg, ${RISK_COLORS.medium}, ${RISK_COLORS.high})`,
    };
  return {
    width: `${d.score * 100}%`,
    background: d.score > 0.4 ? RISK_COLORS.medium : RISK_COLORS.low,
  };
}

function KV({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div className="flex justify-between px-3.5 py-[7px] text-[11.5px]">
      <span className="text-muted">{label}</span>
      <span className="font-mono tnum text-fg" style={color ? { color } : undefined}>
        {value}
      </span>
    </div>
  );
}

export function WalletDetailCard({
  detail,
  loading,
}: {
  detail: WalletDetail | null;
  loading?: boolean;
}) {
  const [tab, setTab] = useState<Tab>("overview");

  if (!detail) {
    return (
      <div className="rounded-card border border-line bg-card">
        <div className="flex items-center justify-between border-b border-line px-3.5 py-3">
          <span className="eyebrow">Selected wallet</span>
        </div>
        <div className={`px-3.5 py-8 text-center text-[11px] text-muted ${loading ? "animate-pulse" : ""}`}>
          {loading ? "Scoring wallet…" : "Click a node in the graph to inspect it."}
        </div>
      </div>
    );
  }

  const color = RISK_COLORS[detail.risk];
  const fill = gaugeFill(detail);

  return (
    <div className={`rounded-card border border-line bg-card ${loading ? "opacity-60" : ""}`}>
      {/* header */}
      <div className="flex items-center justify-between border-b border-line px-3.5 py-3">
        <span className="eyebrow">Selected wallet</span>
        <RiskPill risk={detail.risk} score={detail.score} />
      </div>

      {/* risk gauge */}
      <div className="flex flex-col items-center px-3.5 pb-2.5 pt-4">
        <div
          className="font-mono text-[34px] font-extrabold leading-none tracking-tight tnum"
          style={{ color }}
        >
          {detail.risk === "exchange" ? "—" : detail.score.toFixed(2)}
        </div>
        <div className="mt-1.5 text-[10px] uppercase tracking-[.04em] text-muted">
          {detail.method}
        </div>
        <div className="mt-3 h-1.5 w-full overflow-hidden rounded bg-elevated">
          <i
            className="block h-full rounded transition-all duration-300"
            style={fill}
          />
        </div>
      </div>

      {/* key/value rows */}
      <KV label="Address" value={detail.shortAddress} />
      <KV label="USDT volume" value={detail.volume} />
      <KV label="Counterparties" value={detail.counterparties} />
      <KV label="First seen" value={detail.firstSeen} />
      <KV
        label="Tags"
        value={detail.tags}
        color={detail.tags !== "—" ? RISK_COLORS[detail.tagRisk] : undefined}
      />

      {/* tabs */}
      <div className="flex gap-0.5 border-b border-line px-2.5 pt-2" role="tablist">
        {(
          [
            ["overview", "Overview"],
            ["transactions", "Transactions"],
          ] as const
        ).map(([key, label]) => (
          <button
            key={key}
            type="button"
            role="tab"
            aria-selected={tab === key}
            onClick={() => setTab(key)}
            className={`flex-1 border-b-2 px-2 py-2 text-center text-[11px] font-semibold transition-colors ${
              tab === key
                ? "border-accent text-accent-bright"
                : "border-transparent text-muted hover:text-white/60"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "overview" ? (
        <div>
          <div className="eyebrow px-3.5 pb-0.5 pt-3">Flagged patterns</div>
          {detail.patterns && detail.patterns.length > 0 ? (
            detail.patterns.map((p) => (
              <div
                key={p.name}
                className="flex gap-2.5 border-b border-line px-3.5 py-2.5 last:border-b-0"
              >
                <div
                  className={`grid h-[26px] w-[26px] flex-none place-items-center rounded-lg text-[13px] ${
                    p.severity === "high"
                      ? "bg-risk-high/[.13] text-risk-high"
                      : "bg-risk-med/[.13] text-risk-med"
                  }`}
                  aria-hidden
                >
                  {p.icon ?? "◆"}
                </div>
                <div className="min-w-0">
                  <b className="block text-xs">{p.name}</b>
                  <small className="text-[10.5px] text-muted">{p.evidence}</small>
                </div>
              </div>
            ))
          ) : (
            <div className="px-3.5 py-5 text-center text-[11px] text-muted">
              {detail.patterns === null
                ? "Not applicable — attributed exchange."
                : "No typology patterns fired."}
            </div>
          )}

          {detail.features && (
            <>
              <div className="eyebrow px-3.5 pb-0.5 pt-2">
                Features · 12 indicators
              </div>
              <div className="grid grid-cols-[1fr_auto] gap-x-2.5 gap-y-1.5 px-3.5 py-3">
                {detail.features.map((f) => (
                  <div key={f.name} className="contents">
                    <span className="self-center text-[10.5px] text-muted">
                      {f.name}
                    </span>
                    <span
                      className="h-1 min-w-20 self-center overflow-hidden rounded bg-elevated"
                      title={`${f.percentile}th percentile`}
                    >
                      <i
                        className="block h-full rounded transition-all duration-300"
                        style={{
                          width: `${f.percentile}%`,
                          background:
                            "linear-gradient(90deg, #14b8a6, #34d399)",
                        }}
                      />
                    </span>
                  </div>
                ))}
              </div>
            </>
          )}
        </div>
      ) : (
        <div>
          {detail.transactions.length ? (
            detail.transactions.map((t, i) => (
              <div
                key={i}
                className="flex items-center gap-2.5 border-b border-line px-3.5 py-[9px] text-[11px] last:border-b-0"
              >
                <span
                  className={`rounded px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-[.04em] ${
                    t.direction === "out"
                      ? "bg-risk-high/[.13] text-risk-high"
                      : "bg-risk-low/[.12] text-risk-low"
                  }`}
                >
                  {t.direction}
                </span>
                <span className="font-mono font-semibold tnum">{t.amount}</span>
                <span className="truncate font-mono text-[10.5px] text-muted">
                  {t.counterparty}
                </span>
                <span className="ml-auto font-mono text-[10px] tnum text-muted">
                  {t.time}
                </span>
              </div>
            ))
          ) : (
            <div className="px-3.5 py-5 text-center text-[11px] text-muted">
              No transactions loaded.
            </div>
          )}
        </div>
      )}
    </div>
  );
}
