"use client";

/**
 * Right-rail wallet detail card: risk gauge, KV rows, and the
 * Overview (patterns + 12 features) / Transactions tabs.
 */

import { useEffect, useState } from "react";
import type { WalletDetail } from "@/lib/investigation/types";
import { RISK_COLORS, RISK_LABELS } from "@/lib/investigation/types";
import { RiskPill } from "./risk-pill";

type Tab = "overview" | "transactions";

// Plain-language meaning of each of the 12 features (hover tooltip).
const FACTOR_HELP: Record<string, string> = {
  "Rapid-relay rate": "Share of incoming funds forwarded out within ~5 minutes — pass-through/relay behaviour.",
  "In/out ratio": "Value out vs in (~1.0 = pure pass-through, typical of a mule).",
  "Tx velocity": "Transactions per active day — higher = busier / more automated.",
  "Unique counterparties": "Number of distinct wallets it transacts with.",
  "Round-number %": "Share of round-number amounts — a structuring / smurfing signature.",
  "Account age (inv.)": "How new the wallet is (inverted) — fresh wallets score higher.",
  "Fan-in/out ratio": "Senders vs receivers — high fan-out means dispersal to many wallets.",
  "Time-dist. entropy": "How spread the timing is across the day — low = bursty / automated.",
  "Chain depth": "Hops from the wallet you traced — deeper = further down the laundering chain.",
  "Volume (total)": "Total USDT moved through the wallet.",
  "Max tx size": "Largest single transfer.",
  "Self-loop count": "Transfers back to itself — an obfuscation tactic.",
};

/** Animate a 0..1 value up from 0 (respects reduced-motion). */
function useCountUp(target: number, ms = 650): number {
  const [v, setV] = useState(0);
  useEffect(() => {
    if (
      typeof window !== "undefined" &&
      window.matchMedia?.("(prefers-reduced-motion: reduce)").matches
    ) {
      setV(target);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / ms);
      const eased = 1 - Math.pow(1 - t, 3); // easeOutCubic
      setV(target * eased);
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

// Radial risk gauge — the headline "calculated risk" figure.
function RiskGauge({ detail }: { detail: WalletDetail }) {
  const exchange = detail.risk === "exchange";
  const color = RISK_COLORS[detail.risk];
  const target = exchange ? 1 : Math.max(0, Math.min(1, detail.score));
  const pct = useCountUp(target);
  const R = 48;
  const C = 2 * Math.PI * R;
  return (
    <div className="relative h-[128px] w-[128px]">
      <svg viewBox="0 0 128 128" className="h-full w-full -rotate-90">
        <circle cx={64} cy={64} r={R} fill="none" stroke="rgba(255,255,255,.06)" strokeWidth={9} />
        <circle
          cx={64}
          cy={64}
          r={R}
          fill="none"
          stroke={color}
          strokeWidth={9}
          strokeLinecap="round"
          strokeDasharray={C}
          strokeDashoffset={C * (1 - pct)}
          style={{ filter: `drop-shadow(0 0 6px ${color}66)` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <div className="font-mono text-[30px] font-extrabold leading-none tracking-tight tnum" style={{ color }}>
          {exchange ? "—" : pct.toFixed(2)}
        </div>
        <div className="mt-1 text-[9.5px] font-bold uppercase tracking-[.08em]" style={{ color }}>
          {exchange ? "Exchange" : `${RISK_LABELS[detail.risk]} risk`}
        </div>
      </div>
    </div>
  );
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
  const [hoverFactor, setHoverFactor] = useState<string | null>(null);

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

  return (
    <div className={`rounded-card border border-line bg-card ${loading ? "opacity-60" : ""}`}>
      {/* header */}
      <div className="flex items-center justify-between border-b border-line px-3.5 py-3">
        <span className="eyebrow">Calculated risk</span>
        <RiskPill risk={detail.risk} score={detail.score} />
      </div>

      {/* radial risk gauge — the highlighted verdict */}
      <div className="flex flex-col items-center px-3.5 pb-3 pt-4">
        <RiskGauge detail={detail} />
        <div className="mt-2 text-[9.5px] uppercase tracking-[.05em] text-muted">
          {detail.method}
        </div>
        {detail.risk !== "exchange" && (
          <div className="mt-2.5 flex w-full items-center gap-2">
            <span className="text-[9.5px] uppercase tracking-wide text-muted">Confidence</span>
            <span className="h-1 flex-1 overflow-hidden rounded-full bg-elevated">
              <i
                className="block h-full rounded-full bg-accent transition-all duration-300"
                style={{ width: `${Math.round(detail.confidence * 100)}%` }}
              />
            </span>
            <span className="font-mono text-[10px] tnum text-fg/80">
              {detail.confidence.toFixed(2)}
            </span>
          </div>
        )}
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
          <div className="eyebrow px-3.5 pb-0.5 pt-3">
            Flagged typologies
            {detail.patterns && detail.patterns.length > 0 && (
              <span className="ml-1.5 rounded bg-risk-high/15 px-1.5 py-px text-[9px] font-bold text-risk-high">
                {detail.patterns.length} fired
              </span>
            )}
          </div>
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
              <div className="flex items-baseline justify-between px-3.5 pb-1 pt-2">
                <span className="eyebrow">Risk factors · 12 indicators</span>
                <span className="text-[9px] text-muted/70">percentile · highest first</span>
              </div>
              <div className="space-y-1.5 px-3.5 py-2.5">
                {[...detail.features]
                  .sort((a, b) => b.percentile - a.percentile)
                  .map((f) => {
                    const band =
                      f.percentile >= 70
                        ? "#ef4444"
                        : f.percentile >= 40
                          ? "#f5a524"
                          : "#10b981";
                    const on = hoverFactor === f.name;
                    return (
                      <div
                        key={f.name}
                        className={`flex cursor-help items-center gap-2 rounded transition-colors ${on ? "bg-white/[.04]" : ""}`}
                        onMouseEnter={() => setHoverFactor(f.name)}
                        onMouseLeave={() => setHoverFactor(null)}
                      >
                        <span className={`w-[40%] flex-none truncate text-[10.5px] ${on ? "text-fg" : "text-muted"}`}>
                          {f.name}
                        </span>
                        <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-elevated">
                          <i
                            className="block h-full rounded-full transition-all duration-300"
                            style={{ width: `${f.percentile}%`, background: band }}
                          />
                        </span>
                        <span className="w-6 flex-none text-right font-mono text-[9.5px] tnum" style={{ color: band }}>
                          {f.percentile}
                        </span>
                      </div>
                    );
                  })}
              </div>
              {/* plain-language meaning of the hovered factor */}
              <div className="mx-3.5 mb-3 min-h-[34px] rounded-lg border border-line bg-elevated px-2.5 py-1.5 text-[10.5px] leading-snug text-muted">
                {hoverFactor ? (
                  <>
                    <b className="text-fg/80">{hoverFactor}</b> — {FACTOR_HELP[hoverFactor] ?? "—"}
                  </>
                ) : (
                  <span className="text-muted/70">Hover a factor for its meaning.</span>
                )}
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
