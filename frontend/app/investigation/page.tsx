"use client";

/**
 * Investigation screen (TAKEDOWN) — wallet search → Cytoscape transaction
 * graph → right-rail wallet detail (risk gauge, patterns, 12 features, txs)
 * → Glass Box reasoning trace. Consumes the backend API and falls back to
 * the local mock dataset when the API is unreachable.
 */

import dynamic from "next/dynamic";
import { useCallback, useEffect, useRef, useState } from "react";
import { GlassBox } from "@/components/investigation/glass-box";
import { WalletDetailCard } from "@/components/investigation/wallet-detail-card";
import { fetchWalletDetail, runInvestigation } from "@/lib/investigation/api";
import { DEFAULT_ADDRESS } from "@/lib/investigation/mock";
import type {
  DataSource,
  WalletDetail,
  WalletGraph as WalletGraphData,
} from "@/lib/investigation/types";

const WalletGraph = dynamic(
  () =>
    import("@/components/investigation/wallet-graph").then((m) => ({
      default: m.WalletGraph,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="h-[456px] animate-pulse rounded-card border border-line bg-card" />
    ),
  },
);

export default function InvestigationPage() {
  const [address, setAddress] = useState(DEFAULT_ADDRESS);
  const [graph, setGraph] = useState<WalletGraphData | null>(null);
  const [source, setSource] = useState<DataSource | null>(null);
  const [tracing, setTracing] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const detailsRef = useRef<Record<string, WalletDetail>>({});
  const [detail, setDetail] = useState<WalletDetail | null>(null);
  const traceSeq = useRef(0);

  const selectWallet = useCallback(
    async (
      id: string,
      g: WalletGraphData,
      src: DataSource,
      seq: number,
    ) => {
      setSelected(id);
      const cached = detailsRef.current[id];
      if (cached) {
        setDetail(cached);
        return;
      }
      setDetailLoading(true);
      const node = g.nodes.find((n) => n.id === id);
      const d = await fetchWalletDetail(id, node, src, g);
      if (seq !== traceSeq.current) return; // superseded by a newer trace
      detailsRef.current[id] = d;
      setDetail(d);
      setDetailLoading(false);
    },
    [],
  );

  const trace = useCallback(
    async (addr: string) => {
      const seq = ++traceSeq.current;
      setTracing(true);
      setDetail(null);
      setSelected(null);
      const result = await runInvestigation(addr);
      if (seq !== traceSeq.current) return;
      detailsRef.current = { ...result.seedDetails };
      setGraph(result.graph);
      setSource(result.source);
      setTracing(false);
      const main =
        result.graph.nodes.find((n) => n.isMain) ?? result.graph.nodes[0];
      if (main) void selectWallet(main.id, result.graph, result.source, seq);
    },
    [selectWallet],
  );

  useEffect(() => {
    void trace(DEFAULT_ADDRESS);
  }, [trace]);

  return (
    <div className="mx-auto max-w-[1200px]">
      {/* ── header ─────────────────────────────────────────────────── */}
      <div className="mb-4 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Investigation</h1>
          <p className="mt-1 text-xs text-muted">
            Trace fund flows, score wallets, and flag laundering typologies
            on-chain.{" "}
            <span className="text-accent-bright">Click any node.</span>
          </p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            className="h-8 rounded-lg border border-white/10 bg-elevated px-3.5 text-xs font-semibold text-fg transition-colors hover:bg-white/[.07]"
          >
            Export graph
          </button>
          <button
            type="button"
            className="h-8 rounded-lg bg-accent px-3.5 text-xs font-semibold text-[#04140d] shadow-[0_0_16px_rgba(16,185,129,.28)] transition-colors hover:bg-accent-bright"
          >
            Send to Action Panel →
          </button>
        </div>
      </div>

      {/* ── search bar ─────────────────────────────────────────────── */}
      <form
        className="mb-3.5 flex gap-2.5"
        onSubmit={(e) => {
          e.preventDefault();
          if (!tracing) void trace(address);
        }}
      >
        <div className="flex h-[38px] flex-1 items-center gap-2 rounded-lg border border-white/10 bg-card px-3">
          <span className="text-muted" aria-hidden>
            ⌕
          </span>
          <input
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            spellCheck={false}
            aria-label="Wallet address"
            placeholder="TRON wallet address…"
            className="min-w-0 flex-1 bg-transparent font-mono text-[12.5px] text-fg outline-none placeholder:text-muted"
          />
          <span className="rounded-md border border-line bg-elevated px-2 py-0.5 font-mono text-[10.5px] text-white/60">
            USDT-TRC20
          </span>
          {source && (
            <span
              className={`rounded-md border px-2 py-0.5 font-mono text-[10.5px] font-semibold ${
                source === "api"
                  ? "border-accent/30 bg-accent/10 text-accent-bright"
                  : "border-risk-med/30 bg-risk-med/10 text-risk-med"
              }`}
              title={
                source === "api"
                  ? "Live backend API"
                  : "Backend unreachable — rendering local demo dataset"
              }
            >
              {source === "api" ? "● live api" : "● offline · mock"}
            </span>
          )}
        </div>
        <button
          type="submit"
          disabled={tracing}
          className="h-[38px] rounded-lg bg-accent px-4 text-xs font-semibold text-[#04140d] shadow-[0_0_16px_rgba(16,185,129,.28)] transition-colors hover:bg-accent-bright disabled:opacity-50"
        >
          {tracing ? "Tracing…" : "Trace wallet"}
        </button>
      </form>

      {/* ── graph + right rail ─────────────────────────────────────── */}
      <div className="grid grid-cols-1 items-start gap-3.5 lg:grid-cols-[1fr_328px]">
        {graph && !tracing ? (
          <WalletGraph
            graph={graph}
            selectedId={selected}
            onSelect={(id) => {
              if (graph && source)
                void selectWallet(id, graph, source, traceSeq.current);
            }}
          />
        ) : (
          <div className="grid h-[456px] animate-pulse place-items-center rounded-card border border-line bg-card text-[11px] text-muted">
            {tracing ? "Ingesting transfers + scoring wallets…" : ""}
          </div>
        )}

        <WalletDetailCard detail={detail} loading={detailLoading || tracing} />
      </div>

      {/* ── Glass Box ──────────────────────────────────────────────── */}
      <GlassBox detail={detail} />

      <div className="mt-5 border-t border-line pt-3.5 text-[10.5px] leading-relaxed text-muted">
        Isolation Forest is presented as{" "}
        <b className="text-white/60">anomaly triage</b>, paired with
        deterministic typology rules for court-explainable signal · every flag
        carries confidence + reasoning (UU ITE Pasal 5).
      </div>
    </div>
  );
}
