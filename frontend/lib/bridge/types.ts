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
  /**
   * Full name — shown in the hover <title>. Backend-composed and therefore
   * English ("Mule cluster M-07 (14 accts)"); used verbatim when `nameKey` is
   * absent. Localising these properly needs the backend to send a key plus
   * parameters instead of a finished sentence.
   */
  name: string;
  /**
   * i18n leaf under bridge.sankeyNodes.*, set by the mock (which is what the
   * offline demo actually renders). When present it wins over `name`, so the
   * demo path reads in the chosen language while the live path degrades to the
   * backend's own wording rather than showing a missing-key error.
   */
  nameKey?: string;
  /**
   * Stage label rendered next to the node (sparse, mockup-style:
   * "QRIS merchants" / "Mule accounts" / "Exchange deposits" / …).
   * Omitted → no label drawn.
   */
  label?: string;
  /** i18n leaf for `label`, same fallback rule as `nameKey`. */
  labelKey?: string;
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
  /**
   * The correlation evidence, as NUMBERS. OnRampFeed formats and joins them.
   * This used to be a finished English sentence ("… · amount match 99.1%")
   * built in the data layer, which rendered untranslated in the feed.
   */
  amountIdr?: number;
  deltaSeconds?: number;
  /** 0..100. */
  amountMatchPct?: number;
  /** The crypto wallet that fed the exchange (from_addr) — Takedown trace target. */
  wallet?: string;
  /** Exchange hot-wallet address the USDT landed in (to_addr). */
  toAddr?: string;
  /** USDT amount of the crypto leg — lets the correlation be saved as a transfer. */
  valueUsdt?: number;
  /** ISO timestamp of the crypto deposit. */
  ts?: string;
  /** On-chain tx hash of the deposit, when known. */
  txHash?: string;
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
export const STAGE_COLORS = ["#7a7f87", "#9aa0a8", "#0088e6", "#0099ff"];
/** Foreign-destination endpoints get the deep-blue end of the ramp. */
export const FOREIGN_COLOR = "#4b5563";

// Lighter tint of --accent-bright (see lib/response/types.ts).
export const ACCENT_SOFT = "#33adff";
export const AMBER = "#f5a524";
export const HIGH = "#ef4444";

/** Confidence tint for the on-ramp feed (mockup: ≥0.8 red, else amber). */
export const confidenceColor = (c: number): string =>
  c >= 0.8 ? HIGH : AMBER;

/* ── Formatters ────────────────────────────────────────────────────────── */

/**
 * Compact IDR, matching the dashboard convention used in lib/response/types.ts:
 * T = triliun, B = miliar, M = juta.
 *
 * The miliar branch previously also returned "M", so Rp 4,800,000 and
 * Rp 4,800,000,000 both rendered as "Rp 4.8 M" — a thousandfold ambiguity in
 * the one field this screen exists to communicate. POC fixture volumes sit in
 * the juta range so the collision rarely showed, but LIVE bank feeds (and the
 * Rp 530 miliar case this demo is built on) land squarely in it. Response
 * already rendered miliar as "B", so Bridge was also disagreeing with the
 * Command Center about the same number.
 */
export function formatIDR(v: number): string {
  if (!Number.isFinite(v) || v <= 0) return "—";
  if (v >= 1e12) return `Rp ${(v / 1e12).toFixed(1)} T`;
  if (v >= 1e9) return `Rp ${(v / 1e9).toFixed(1)} B`;
  if (v >= 1e6) return `Rp ${(v / 1e6).toFixed(1)} M`;
  return `Rp ${Math.round(v).toLocaleString("en-US")}`;
}

export const formatUSD = (v: number): string =>
  Number.isFinite(v) ? `$${Math.round(v).toLocaleString("en-US")}` : "—";

export const formatMinutes = (seconds: number): string =>
  `Δt ${Math.max(1, Math.round(seconds / 60))} min`;
