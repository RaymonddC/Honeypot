/**
 * TRACE / Bridge View screen — frontend-canonical types.
 *
 * The API layer (lib/bridge/api.ts) normalizes whatever the backend returns
 * (docs/API-Contract.md · TRACE endpoints) into these shapes; the mock
 * fallback (lib/bridge/mock.ts) produces them directly, ported from the
 * approved mockup's Bridge View section.
 */

export type DataSource = "api" | "mock";

/* ── Sankey ────────────────────────────────────────────────────────────── */

export interface BridgeSankeyNode {
  /** Stable node id (referenced by links). */
  id: string;
  /** Full name — shown in the hover <title>. */
  name: string;
  /**
   * Stage label rendered next to the node (sparse, mockup-style:
   * "QRIS merchants" / "Mule accounts" / "Exchange deposits" / …).
   * Omitted → no label drawn.
   */
  label?: string;
  /** Explicit fill; falls back to the depth-based fiat→crypto ramp. */
  color?: string;
}

export interface BridgeSankeyLink {
  /** Source / target node ids. */
  source: string;
  target: string;
  /** Flow volume (relative units — drives link width). */
  value: number;
}

export interface BridgeSankeyData {
  nodes: BridgeSankeyNode[];
  links: BridgeSankeyLink[];
}

/* ── Suspected on-ramps (correlation alerts) ───────────────────────────── */

export interface OnRampAlert {
  id: string;
  /** Correlation confidence 0..1 — feed is ranked by this. */
  confidence: number;
  /** e.g. "Mule cluster M-07 → Indodax". */
  title: string;
  /** e.g. "Rp 48.2M · Δt 12 min · amount match 99.1%". */
  meta: string;
  /** The crypto wallet that fed the exchange — hand off to Takedown to trace. */
  wallet?: string;
}

/* ── Mule network stats card ───────────────────────────────────────────── */

export interface MuleNetworkStats {
  /** Louvain community count. */
  clusters: string;
  muleAccounts: string;
  shellMerchants: string;
  /** Correlation time window, e.g. "30 min". */
  correlationWindow: string;
}

/* ── Stat row ──────────────────────────────────────────────────────────── */

export interface StatValue {
  value: string;
  /** Small dimmed suffix (e.g. "M" in "Rp 530.4 M"). */
  suffix?: string;
  /** Value color override (defaults to foreground). */
  color?: string;
}

export interface BridgeStats {
  qrisInflow: StatValue;
  bridgedToCrypto: StatValue;
  correlatedOnRamps: StatValue;
}

/* ── Aggregate screen payload ──────────────────────────────────────────── */

export interface BridgeData {
  stats: BridgeStats;
  sankey: BridgeSankeyData;
  alerts: OnRampAlert[];
  mules: MuleNetworkStats;
  source: DataSource;
}

/* ── Colors (mockup fiat→crypto ramp) ──────────────────────────────────── */

/** Node fill by Sankey depth: QRIS → mules → exchange → USDT. */
export const STAGE_COLORS = ["#f5a524", "#f59e0b", "#06b6d4", "#0ea5e9"];
/** Foreign-destination endpoints get the deep-blue end of the ramp. */
export const FOREIGN_COLOR = "#3b82f6";

export const CYAN = "#06b6d4";
export const AMBER = "#f5a524";
export const HIGH = "#ef4444";

/** Confidence tint for the on-ramp feed (mockup: ≥0.8 red, else amber). */
export const confidenceColor = (c: number): string =>
  c >= 0.8 ? HIGH : AMBER;

/* ── Formatters ────────────────────────────────────────────────────────── */

/** Compact IDR: miliar (B) → "Rp 48.2M"-style juta (mockup convention). */
export function formatIDR(v: number): string {
  if (!Number.isFinite(v) || v <= 0) return "—";
  if (v >= 1e12) return `Rp ${(v / 1e12).toFixed(1)} T`;
  if (v >= 1e9) return `Rp ${(v / 1e9).toFixed(1)} M`;
  if (v >= 1e6) return `Rp ${(v / 1e6).toFixed(1)}M`;
  return `Rp ${Math.round(v).toLocaleString("en-US")}`;
}

export const formatUSD = (v: number): string =>
  Number.isFinite(v) ? `$${Math.round(v).toLocaleString("en-US")}` : "—";

export const formatMinutes = (seconds: number): string =>
  `Δt ${Math.max(1, Math.round(seconds / 60))} min`;
