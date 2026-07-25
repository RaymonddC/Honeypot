/**
 * Response Dashboard screen — frontend-canonical types.
 *
 * The API layer (lib/response/api.ts) normalizes GET /api/metrics/response
 * (docs/API-Contract.md · docs/Response-Dashboard.md) into these shapes; the
 * mock fallback (lib/response/mock.ts) produces them directly, ported from
 * the approved mockup's Response Dashboard (#dash) section.
 */

export type DataSource = "api" | "mock";

/* ── Metric tiles ──────────────────────────────────────────────────────── */

export interface MetricTile {
  /** Eyebrow label, e.g. "Avg time-to-freeze". */
  label: string;
  /** Big mono figure, e.g. "27". */
  value: string;
  /** Small dimmed unit suffix, e.g. "min" / "B" / "%". */
  suffix?: string;
  /** Value color override (defaults to foreground). */
  color?: string;
  /** Delta / context line under the value, e.g. "▲ 6 this week". */
  delta?: string;
  /** Tint the delta emerald (mockup .d.up). */
  deltaUp?: boolean;
}

/* ── Active cases table ────────────────────────────────────────────────── */

export type CaseRisk = "high" | "med" | "low";

export interface ActiveCase {
  /** Short case ref, e.g. "ITU-0417". */
  ref: string;
  /** Crime type, e.g. "Judol relay". */
  type: string;
  /** Funds at risk, formatted, e.g. "Rp 48M". */
  atRisk: string;
  risk: CaseRisk;
  /** Pill label — usually the risk level, "Frozen" when resolved. */
  statusLabel: string;
}

/* ── Operations pipeline (INFILTRATE → TAKEDOWN → UNCOVER activity) ─────── */

export interface OpsStat {
  label: string;
  value: string;
  /** Small context line under the figure. */
  sub?: string;
  /** Glyph for the tile. */
  glyph?: string;
  /** Accent color for the figure. */
  color?: string;
}

/* ── Aggregate screen payload ──────────────────────────────────────────── */

export interface ResponseMetrics {
  /** Order: cases · time-to-freeze · at risk · frozen · recovery rate. */
  tiles: MetricTile[];
  /** Operational pipeline stats (honeypot · wallets · documents · dispatch). */
  ops: OpsStat[];
  /** Time-to-freeze improvement vs manual baseline, e.g. "42×". */
  improvement?: string;
  /** Time-to-freeze trend, minutes per case/period (sparkline). */
  trend: number[];
  /** Latest trend value label, e.g. "27 min". */
  trendNow: string;
  /** Trend card tag, e.g. "↓ 96% vs baseline". */
  trendTag: string;
  cases: ActiveCase[];
  /** Active range filter (7d | 30d | all). */
  range: RangeKey;
  source: DataSource;
}

export type RangeKey = "7d" | "30d" | "all";

export const RANGE_LABELS: Record<RangeKey, string> = {
  "7d": "Last 7 days",
  "30d": "Last 30 days",
  all: "All time",
};

/* ── Colors (mockup tokens) ────────────────────────────────────────────── */

export const EMERALD = "#34d399";
export const CYAN = "#06b6d4";

/** IASC baseline the recovery rate is benchmarked against. */
export const BASELINE_RECOVERY_PCT = 4.76;
/** Manual-workflow baseline the time-to-freeze story is told against. */
export const BASELINE_FREEZE = "12h+";

/* ── Formatters ────────────────────────────────────────────────────────── */

/**
 * Compact IDR split into {value, suffix} for tile styling — dashboard
 * convention (mockup): T=triliun, B=miliar, M=juta.
 */
export function splitIDR(v: number): { value: string; suffix?: string } {
  if (!Number.isFinite(v) || v <= 0) return { value: "—" };
  if (v >= 1e12) return { value: `Rp ${(v / 1e12).toFixed(1)}`, suffix: "T" };
  if (v >= 1e9) return { value: `Rp ${(v / 1e9).toFixed(1)}`, suffix: "B" };
  if (v >= 1e6) return { value: `Rp ${Math.round(v / 1e6)}`, suffix: "M" };
  return { value: `Rp ${Math.round(v).toLocaleString("en-US")}` };
}

/** Inline compact IDR for table cells, e.g. "Rp 48M". */
export function formatIDRShort(v: number): string {
  if (!Number.isFinite(v) || v <= 0) return "—";
  if (v >= 1e12) return `Rp ${(v / 1e12).toFixed(1)}T`;
  if (v >= 1e9) return `Rp ${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `Rp ${Math.round(v / 1e6)}M`;
  return `Rp ${Math.round(v).toLocaleString("en-US")}`;
}

/** Minutes → {value, suffix} ("27 min", "1.4 h"). */
export function splitMinutes(min: number): { value: string; suffix: string } {
  if (!Number.isFinite(min) || min < 0) return { value: "—", suffix: "" };
  if (min >= 120) return { value: (min / 60).toFixed(1), suffix: "h" };
  return { value: String(Math.round(min)), suffix: "min" };
}
