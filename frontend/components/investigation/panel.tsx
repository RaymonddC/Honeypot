"use client";

/**
 * Investigation screen (TAKEDOWN) — wallet search → Cytoscape transaction
 * graph → right-rail wallet detail (risk gauge, patterns, 12 features, txs)
 * → Glass Box reasoning trace. Consumes the backend API and falls back to
 * the local mock dataset when the API is unreachable.
 *
 * Rendered both as the standalone /investigation page and embedded in the
 * Case File's Investigation tab (pass ``embedded`` + optional
 * ``initialAddress`` to auto-trace the case's wallet).
 */

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { AddTransaction } from "@/components/investigation/add-transaction";
import { GlassBox } from "@/components/investigation/glass-box";
import { WalletDetailCard } from "@/components/investigation/wallet-detail-card";
import { fetchWalletDetail, runInvestigation } from "@/lib/investigation/api";
import type { TraceStatus } from "@/lib/investigation/api";
import { useAuth } from "@/components/auth/auth-provider";
import { DEFAULT_ADDRESS } from "@/lib/investigation/mock";
import type {
  DataSource,
  WalletDetail,
  WalletGraph as WalletGraphData,
} from "@/lib/investigation/types";
import { RISK_COLORS, RISK_LABELS, shortAddr } from "@/lib/investigation/types";

// Status → search-bar badge classnames. LIVE states are honest (no "mock"
// unless POC/offline). Labels/titles come from i18n (see `statusBadge` below).
const STATUS_BADGE_CLS: Record<TraceStatus, string> = {
  idle: "border-accent/30 bg-accent/10 text-accent-bright",
  ok: "border-accent/30 bg-accent/10 text-accent-bright",
  mock: "border-risk-med/30 bg-risk-med/10 text-risk-med",
  empty: "border-line bg-fg/[.05] text-muted",
  rate_limited: "border-risk-med/30 bg-risk-med/10 text-risk-med",
  error: "border-risk-high/30 bg-risk-high/10 text-risk-high",
};

const WalletGraph = dynamic(
  () =>
    import("@/components/investigation/wallet-graph").then((m) => ({
      default: m.WalletGraph,
    })),
  {
    ssr: false,
    loading: () => (
      <div className="h-[540px] animate-pulse rounded-card border border-line bg-card" />
    ),
  },
);

export function InvestigationPanel({
  embedded = false,
  initialAddress,
  caseWallets,
  onSendToActions,
}: {
  embedded?: boolean;
  /** When embedded in a case, auto-trace this wallet on first load. */
  initialAddress?: string;
  /** The case's own wallets — rendered as one-click "trace" chips. */
  caseWallets?: string[];
  /** Handoff: take the scored wallet to the Action Panel (freeze / STR). */
  onSendToActions?: (address: string) => void;
}) {
  const t = useTranslations("investigation.panel");
  const { config } = useAuth();
  const [address, setAddress] = useState(DEFAULT_ADDRESS);
  const [graph, setGraph] = useState<WalletGraphData | null>(null);
  const [source, setSource] = useState<DataSource | null>(null);
  const [status, setStatus] = useState<TraceStatus | null>(null);
  const [tracing, setTracing] = useState(false);
  const [selected, setSelected] = useState<string | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const detailsRef = useRef<Record<string, WalletDetail>>({});
  const [detail, setDetail] = useState<WalletDetail | null>(null);
  const traceSeq = useRef(0);
  const selectSeq = useRef(0); // bumps on every wallet selection (not just new traces)

  // TAKEDOWN is LIVE when its module (or the global default) is LIVE. In LIVE a
  // failed trace shows an honest state instead of fabricated mock data.
  const liveRef = useRef(false);
  liveRef.current =
    (config?.modules.find((m) => m.module === "takedown")?.mode ??
      config?.mode) === "LIVE";

  const selectWallet = useCallback(
    async (
      id: string,
      g: WalletGraphData,
      src: DataSource,
      seq: number,
    ) => {
      const sel = ++selectSeq.current;
      setSelected(id);
      const cached = detailsRef.current[id];
      if (cached) {
        setDetail(cached);
        setDetailLoading(false); // a prior in-flight fetch must not keep dimming this card
        return;
      }
      setDetailLoading(true);
      const node = g.nodes.find((n) => n.id === id);
      const d = await fetchWalletDetail(id, node, src, g);
      // Ignore if a newer trace OR a newer selection superseded this fetch —
      // otherwise a slow uncached fetch clobbers a later (cached) selection,
      // showing the wrong wallet's risk/score and packaging the wrong wallet.
      if (seq !== traceSeq.current || sel !== selectSeq.current) return;
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
      const result = await runInvestigation(addr, liveRef.current);
      if (seq !== traceSeq.current) return;
      detailsRef.current = { ...result.seedDetails };
      setGraph(result.graph);
      setSource(result.source);
      setStatus(result.status);
      setTracing(false);
      const hasGraph = result.status === "ok" || result.status === "mock";
      const main = hasGraph
        ? (result.graph.nodes.find((n) => n.isMain) ?? result.graph.nodes[0])
        : undefined;
      if (main) void selectWallet(main.id, result.graph, result.source, seq);
    },
    [selectWallet],
  );

  // Run the initial trace once, after MODE resolves. POC auto-traces the demo
  // fixture (the seeded story). LIVE stays idle with an empty input — the fixture
  // is a POC address that only 404s on-chain, and auto-tracing a real wallet on
  // every load would burn ~30s + rate-limit. The analyst types a real wallet.
  const didInit = useRef(false);
  const searchParams = useSearchParams();
  useEffect(() => {
    if (didInit.current || !config) return;
    didInit.current = true;
    // Embedded in a case: auto-trace the case's wallet if one was passed.
    // Deep-link from the Case File ("investigate →"): trace that wallet on load.
    const linked = initialAddress || searchParams.get("address");
    if (linked) {
      setAddress(linked);
      void trace(linked);
    } else if (embedded) {
      // In-case with no wallet yet — stay idle, don't trace the POC fixture.
      setAddress("");
      setStatus("idle");
    } else if (liveRef.current) {
      setAddress("");
      setStatus("idle");
    } else {
      void trace(DEFAULT_ADDRESS);
    }
  }, [config, trace, searchParams, embedded, initialAddress]);

  return (
    <div className={embedded ? "" : "mx-auto max-w-[1200px]"}>
      {/* ── header ─────────────────────────────────────────────────── */}
      <div
        className={`mb-5 flex flex-col items-start gap-3 sm:flex-row sm:items-start sm:gap-4 ${embedded ? "sm:justify-end" : "sm:justify-between"}`}
      >
        {!embedded && (
          <div>
            <h1 className="text-2xl font-bold tracking-tight">{t("title")}</h1>
            <p className="mt-1.5 max-w-[60ch] text-[13px] leading-relaxed text-muted">
              {t("pageLead")}{" "}
              <span className="text-accent-bright">{t("subtitleCta")}</span>
            </p>
          </div>
        )}
        <div className="flex flex-wrap gap-2">
          <AddTransaction
            onAdded={(toAddr) => {
              setAddress(toAddr);
              void trace(toAddr);
            }}
          />
          {/* Standalone gets a plain link; embedded uses the contextual
              "Package for action" button on the verdict banner (no duplicate). */}
          {!onSendToActions && (
            <Link
              href="/actions"
              className="flex h-8 items-center rounded-full bg-accent px-3.5 text-[12px] font-semibold text-[#090909] transition-colors hover:bg-accent-bright"
            >
              {t("sendToActions")}
            </Link>
          )}
        </div>
      </div>

      {/* ── search bar — plumbing: kept compact so the verdict below carries
          the visual weight, not the input itself ─────────────────────── */}
      <form
        className="mb-2.5 flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (!tracing && address.trim()) void trace(address.trim());
        }}
      >
        <div className="flex h-9 flex-1 items-center gap-2 rounded-lg border border-line bg-elevated px-3">
          <span className="text-muted" aria-hidden>
            ⌕
          </span>
          <input
            value={address}
            onChange={(e) => setAddress(e.target.value)}
            spellCheck={false}
            aria-label={t("walletAddressLabel")}
            placeholder={t("walletAddressPlaceholder")}
            className="min-w-0 flex-1 bg-transparent font-mono text-[12px] text-fg outline-none placeholder:text-muted"
          />
          <span
            className="rounded border border-line bg-card px-1.5 py-0.5 font-mono text-[12px] text-muted"
            title={t("walletInputHint")}
          >
            USDT-TRC20
          </span>
          {status && (
            <span
              className={`rounded border px-1.5 py-0.5 text-[12px] ${STATUS_BADGE_CLS[status]}`}
              title={t(`statusBadge.${status}.title`)}
            >
              {t(`statusBadge.${status}.label`)}
            </span>
          )}
        </div>
        <button
          type="submit"
          disabled={tracing || !address.trim()}
          className="h-9 rounded-full bg-accent px-4 text-[12px] font-semibold text-[#090909] transition-colors hover:bg-accent-bright disabled:opacity-50"
        >
          {tracing ? t("tracing") : t("traceWallet")}
        </button>
      </form>

      {/* the case's own wallets — one-click trace chips (no copy-paste) */}
      {caseWallets && caseWallets.length > 0 && (
        <div className="mb-3.5 flex flex-wrap items-center gap-1.5">
          <span className="text-[12px] uppercase tracking-wide text-muted">
            {t("caseWalletsLabel")}
          </span>
          {caseWallets.map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => {
                setAddress(w);
                void trace(w);
              }}
              title={t("traceWalletTitle", { address: w })}
              className={`rounded-lg border px-2 py-1 font-mono text-[12px] transition-colors ${
                address === w
                  ? "border-accent/50 bg-accent/15 text-accent-bright"
                  : "border-line bg-card text-muted hover:text-fg"
              }`}
            >
              {shortAddr(w)}
            </button>
          ))}
        </div>
      )}

      {/* verdict + plain-language recommendation — the headline finding on
          this screen, so it gets the largest type and the most presence */}
      {detail && !tracing && (
        <div
          className="relative mb-4 flex flex-wrap items-center gap-x-5 gap-y-2.5 overflow-hidden rounded-card border px-5 py-4"
          style={{
            borderColor: `${RISK_COLORS[detail.risk]}55`,
            background: `${RISK_COLORS[detail.risk]}12`,
          }}
        >
          <span
            className="absolute inset-y-0 left-0 w-1.5"
            style={{ background: RISK_COLORS[detail.risk] }}
            aria-hidden
          />
          <div className="flex items-center gap-3 pl-1">
            <span
              className="font-mono text-[34px] font-extrabold leading-none tnum"
              style={{
                color: RISK_COLORS[detail.risk],
                textShadow: `0 0 14px ${RISK_COLORS[detail.risk]}55`,
              }}
            >
              {detail.risk === "exchange" ? "—" : detail.score.toFixed(2)}
            </span>
            <div>
              <div
                className="text-[12.5px] font-bold uppercase tracking-wide"
                style={{ color: RISK_COLORS[detail.risk] }}
              >
                {detail.risk === "exchange" ? t("attributedExchange") : t("riskSuffix", { risk: RISK_LABELS[detail.risk] })}
              </div>
              <div className="font-mono text-[12px] text-muted">
                {detail.shortAddress} · conf {detail.confidence.toFixed(2)}
              </div>
            </div>
          </div>
          <p className="min-w-0 flex-1 text-[12px] leading-snug text-fg/80">
            {t(`riskReco.${detail.risk}`)}
          </p>
          {onSendToActions && (
            <button
              type="button"
              onClick={() => onSendToActions(detail.address)}
              title={t("packageForActionTitle")}
              className={`h-8 flex-none rounded-lg px-3 text-[12px] font-semibold transition-colors ${
                detail.risk === "high" || detail.risk === "exchange"
                  ? "bg-accent text-[#090909] hover:bg-accent-bright"
                  : "border border-accent/40 bg-accent/10 text-accent-bright hover:bg-accent/20"
              }`}
            >
              {t("packageForAction")}
            </button>
          )}
        </div>
      )}

      {/* ── graph + reasoning (left) · calculated risk (right) ─────────── */}
      <div className="grid grid-cols-1 items-start gap-3.5 lg:grid-cols-[1fr_336px]">
        {/* left column — graph then the Glass Box, so it fills to match the
            content-rich risk card and there's no dead space below the graph */}
        <div className="space-y-3.5">
          {tracing ? (
            <div
              className="grid h-[540px] place-items-center rounded-card border border-line bg-card"
              aria-live="polite"
            >
              <div className="flex flex-col items-center gap-3 text-center">
                <span
                  className="h-8 w-8 rounded-full border-2 border-accent/25 border-t-accent motion-safe:animate-spin motion-reduce:animate-pulse"
                  aria-hidden
                />
                <div>
                  <p className="text-[13px] font-medium text-fg">{t("tracingOnChain")}</p>
                  <p className="mt-1 text-[12px] text-muted">
                    {t("tracingHint")}
                  </p>
                </div>
              </div>
            </div>
          ) : (status === "ok" || status === "mock") && graph ? (
            <WalletGraph
              graph={graph}
              selectedId={selected}
              onSelect={(id) => {
                if (graph && source)
                  void selectWallet(id, graph, source, traceSeq.current);
              }}
            />
          ) : status && status !== "ok" && status !== "mock" ? (
            <div
              className="grid h-[540px] place-items-center rounded-card border border-line bg-card"
              role="status"
            >
              <div className="max-w-xs px-6 text-center">
                <p className="text-[13px] font-medium text-fg">
                  {t(`statePanel.${status}.title`)}
                </p>
                <p className="mt-1.5 text-[12px] leading-relaxed text-muted">
                  {t(`statePanel.${status}.sub`)}
                </p>
              </div>
            </div>
          ) : (
            <div className="h-[540px] rounded-card border border-line bg-card" />
          )}

          <GlassBox detail={detail} />
        </div>

        <WalletDetailCard detail={detail} loading={detailLoading || tracing} />
      </div>

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
