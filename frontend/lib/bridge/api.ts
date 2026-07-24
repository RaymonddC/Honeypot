/**
 * TRACE API client — Bridge View data (docs/API-Contract.md):
 *
 *   POST /api/bridge/simulate   {case?, params?}  → ok / generation stats
 *   GET  /api/bridge/sankey?case=                 → sankey_data
 *   GET  /api/bridge/correlations?case=           → [correlation]
 *   GET  /api/bridge/mules?case=                  → [mule_cluster]
 *
 * Base URL: NEXT_PUBLIC_API_URL (default http://localhost:8000). Shapes are
 * normalized defensively (P2-Backend confirmation pending); any failure
 * falls back to the local mock (lib/bridge/mock.ts) so the screen stays
 * demoable standalone.
 */

import { buildMockBridge } from "./mock";
import type {
  BridgeData,
  BridgeSankeyData,
  BridgeSankeyLink,
  BridgeSankeyNode,
  BridgeStats,
  MuleNetworkStats,
  OnRampAlert,
} from "./types";
import { AMBER, CYAN, formatIDR, formatMinutes, formatUSD } from "./types";

import { apiFetch } from "@/lib/http";

/* eslint-disable @typescript-eslint/no-explicit-any */

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 6000,
): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await apiFetch(path, {
      ...init,
      signal: ctrl.signal,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

const num = (v: unknown): number | null => {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

const first = (...vals: unknown[]): any =>
  vals.find((v) => v !== undefined && v !== null);

/* ── Sankey normalization ─────────────────────────────────────────────── */

function normalizeSankey(raw: any): BridgeSankeyData {
  const g = first(raw?.sankey, raw?.sankey_data, raw?.data, raw) ?? {};
  const rawNodes: any[] = g.nodes ?? [];
  const rawLinks: any[] = g.links ?? g.edges ?? [];

  const nodes: BridgeSankeyNode[] = rawNodes.map((n, i) => {
    const id = String(first(n?.id, n?.name, i));
    const name = String(first(n?.name, n?.label, n?.id, `node ${i}`));
    return {
      id,
      name,
      // Backend may send an explicit stage label; else name doubles as one.
      label: n?.label != null ? String(n.label) : name,
      color: n?.color ? String(n.color) : undefined,
    };
  });

  // Links may reference nodes by id, name, or array index.
  const refToId = (ref: any): string => {
    if (typeof ref === "number") return nodes[ref]?.id ?? String(ref);
    if (ref && typeof ref === "object")
      return String(first(ref.id, ref.name, ref.index, ""));
    return String(ref ?? "");
  };

  const ids = new Set(nodes.map((n) => n.id));
  const links: BridgeSankeyLink[] = rawLinks
    .map((l): BridgeSankeyLink => ({
      source: refToId(first(l?.source, l?.from)),
      target: refToId(first(l?.target, l?.to)),
      value: num(first(l?.value, l?.amount, l?.volume)) ?? 0,
    }))
    .filter(
      (l) =>
        l.value > 0 && ids.has(l.source) && ids.has(l.target) &&
        l.source !== l.target,
    );

  if (nodes.length < 2 || !links.length)
    throw new Error("empty sankey from API");
  return { nodes, links };
}

/* ── Correlations → on-ramp alert feed ────────────────────────────────── */

// Last-4 of an account number, prefixed "·" (e.g. "·8462").
const acctTail = (s: unknown): string => {
  const d = String(s ?? "").replace(/\D/g, "");
  return d ? ` ·${d.slice(-4)}` : "";
};

// "PT Indodax Nasional Indonesia" → "Indodax" (recognizable exchange token).
const exchangeShort = (name: unknown): string => {
  const s = String(name ?? "").replace(/^PT\.?\s+/i, "").trim();
  return s.split(/\s+/)[0] || s;
};

function normalizeCorrelations(raw: any): OnRampAlert[] {
  const items: any[] = Array.isArray(raw)
    ? raw
    : (raw?.items ?? raw?.correlations ?? []);

  return items
    .map((c, i): OnRampAlert => {
      // The backend sends nested `fiat` / `crypto` legs; older/flat shapes are
      // still honored as fallbacks.
      const fiat = c?.fiat ?? {};
      const crypto = c?.crypto ?? {};
      const confidence = Math.max(
        0,
        Math.min(1, num(first(c?.confidence, c?.score)) ?? 0),
      );

      // Fiat / mule side — who paid into the exchange.
      const from = first(
        c?.label, c?.mule_cluster, c?.cluster, // legacy flat
        fiat.from_holder,
        fiat.from_bank
          ? `${fiat.from_bank}${acctTail(fiat.from_account_number)}`
          : fiat.from_account_number,
      );
      // Crypto / exchange side — prefer the exchange NAME (receiving holder),
      // then its bank, then the hot-wallet address.
      const toRaw = first(
        c?.exchange, c?.exchange_name, // legacy flat
        fiat.to_holder,
        fiat.to_bank,
        crypto.to_addr,
      );
      const to = toRaw != null ? exchangeShort(toRaw) : null;

      const title =
        c?.title != null
          ? String(c.title)
          : `${from != null ? String(from) : "Mule account"}${to != null ? ` → ${to}` : ""}`;

      const parts: string[] = [];
      const idr = num(
        first(fiat.amount_idr, c?.fiat_amount_idr, c?.amount_idr, c?.fiat_amount),
      );
      if (idr != null) parts.push(formatIDR(idr));
      const dt = num(first(c?.time_delta_seconds, c?.delta_seconds));
      if (dt != null) parts.push(formatMinutes(dt));
      const match = num(first(c?.amount_match, c?.amount_match_pct));
      if (match != null)
        parts.push(
          `amount match ${(match <= 1 ? match * 100 : match).toFixed(1)}%`,
        );

      // The depositing wallet (launderer feeding the exchange) — the Takedown
      // target. Fall back to the hot-wallet address, then any flat field.
      const walletRaw = first(
        crypto.from_addr,
        crypto.to_addr,
        c?.crypto_wallet,
        c?.wallet,
      );
      const wallet =
        walletRaw != null && String(walletRaw).length >= 4
          ? String(walletRaw)
          : undefined;

      return {
        id: String(first(c?.id, `corr-${i}`)),
        confidence,
        title,
        meta: parts.join(" · ") || "correlated on-ramp",
        wallet,
      };
    })
    .sort((a, b) => b.confidence - a.confidence);
}

/* ── Mule clusters → network stats card ───────────────────────────────── */

function normalizeMules(raw: any): MuleNetworkStats {
  const clusters: any[] = Array.isArray(raw)
    ? raw
    : (raw?.items ?? raw?.clusters ?? []);
  const stats = first(raw?.stats, raw?.summary, {}) as any;

  const sum = (keys: string[]): number | null => {
    let total = 0;
    let found = false;
    for (const c of clusters)
      for (const k of keys) {
        const v = num(c?.[k]);
        if (v != null) {
          total += v;
          found = true;
          break;
        }
      }
    return found ? total : null;
  };

  const nClusters = num(first(stats?.clusters, stats?.total_clusters)) ??
    (clusters.length || null);
  const accounts =
    num(first(stats?.mule_accounts, stats?.total_accounts)) ??
    sum(["n_accounts", "accounts", "account_count", "size"]);
  const merchants =
    num(first(stats?.shell_merchants, stats?.total_merchants)) ??
    sum(["n_merchants", "merchants", "merchant_count"]);
  const windowMin = num(
    first(stats?.correlation_window_minutes, stats?.window_minutes, raw?.window_minutes),
  );

  const fmt = (v: number | null): string =>
    v != null ? Math.round(v).toLocaleString("en-US") : "—";

  return {
    clusters: fmt(nClusters),
    muleAccounts: fmt(accounts),
    shellMerchants: fmt(merchants),
    correlationWindow: windowMin != null ? `${windowMin} min` : "30 min",
  };
}

/* ── Stat row (from response aggregates, else derived) ────────────────── */

function deriveStats(
  sankeyRaw: any,
  mulesRaw: any,
  alerts: OnRampAlert[],
): BridgeStats {
  const pools = [sankeyRaw?.stats, sankeyRaw, mulesRaw?.stats].filter(Boolean);
  const pick = (...keys: string[]): number | null => {
    for (const pool of pools)
      for (const k of keys) {
        const v = num(pool?.[k]);
        if (v != null) return v;
      }
    return null;
  };

  const inflow = pick("qris_inflow_idr", "fiat_inflow_idr", "total_fiat_idr", "qris_inflow");
  const bridged = pick("bridged_usd", "bridged_to_crypto_usd", "total_crypto_usd", "bridged_usdt");
  const correlated =
    pick("correlated_onramps", "correlated_on_ramps", "correlations") ??
    (alerts.length || null);

  const idr = inflow != null ? formatIDR(inflow) : "—";
  const m = idr.match(/^(.*) (T|M)$/); // split unit suffix for styling

  return {
    qrisInflow: m
      ? { value: m[1], suffix: m[2] }
      : { value: idr },
    bridgedToCrypto: {
      value: bridged != null ? formatUSD(bridged) : "—",
      color: CYAN,
    },
    correlatedOnRamps: {
      value: correlated != null ? String(correlated) : "—",
      color: AMBER,
    },
  };
}

/* ── Public surface ───────────────────────────────────────────────────── */

/**
 * Load the full Bridge View payload. With `simulate`, POST /bridge/simulate
 * first to (re)generate the synthetic PT A2Z fiat side. Falls back to the
 * mock dataset when the API is unreachable or returns an empty pipeline.
 */
export async function fetchBridgeData(opts?: {
  simulate?: boolean;
}): Promise<BridgeData> {
  try {
    if (opts?.simulate) {
      await request<any>(
        "/bridge/simulate",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({}),
        },
        20000,
      ).catch(() => null); // simulate is best-effort; reads decide the source
    }

    const [sankeyRaw, corrRaw, mulesRaw] = await Promise.all([
      request<any>("/bridge/sankey"),
      request<any>("/bridge/correlations").catch(() => null),
      request<any>("/bridge/mules").catch(() => null),
    ]);

    const sankey = normalizeSankey(sankeyRaw);
    const alerts = normalizeCorrelations(corrRaw);
    const mules = normalizeMules(mulesRaw);
    const stats = deriveStats(sankeyRaw, mulesRaw, alerts);

    return { stats, sankey, alerts, mules, source: "api" };
  } catch {
    return buildMockBridge();
  }
}
