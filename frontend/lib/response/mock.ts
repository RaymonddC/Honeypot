/**
 * Local fallback demo data — ported from the approved Response Dashboard
 * mockup (artifact d592d92c · #dash section). Used whenever the backend API
 * is unreachable so the screen always renders standalone.
 */

import type { ActiveCase, MetricTile, OpsStat, ResponseMetrics, RangeKey } from "./types";
import { ACCENT_SOFT, ACCENT } from "./types";

// Keys only, like the API layer — the components resolve the wording, so the
// offline fallback speaks the chosen language too.
export const MOCK_OPS: OpsStat[] = [
  { key: "honeypotSessions", glyph: "⬡", value: "3" },
  { key: "entitiesConfirmed", glyph: "◇", value: "17" },
  { key: "walletsScored", glyph: "◉", value: "42", color: ACCENT },
  { key: "documentsGenerated", glyph: "⚑", value: "9" },
  { key: "bundlesDispatched", glyph: "↗", value: "3/5", color: ACCENT_SOFT },
  { key: "agencyNotifications", glyph: "◈", value: "8" },
];

export const MOCK_TILES: MetricTile[] = [
  {
    key: "casesInProgress",
    value: "24",
    delta: { key: "thisWeek", values: { count: 6 } },
    deltaUp: true,
  },
  {
    key: "avgTimeToFreeze",
    value: "27",
    suffix: "min",
    color: ACCENT,
    delta: { key: "fromBaseline", values: { hours: 12 } },
    deltaUp: true,
  },
  {
    key: "fundsAtRisk",
    value: "Rp 4.8",
    suffix: "B",
    delta: { key: "flaggedOpen" },
  },
  {
    key: "fundsFrozen",
    value: "Rp 712",
    suffix: "M",
    color: ACCENT_SOFT,
    delta: { key: "acked", values: { count: 14 } },
    deltaUp: true,
  },
  {
    // Freeze, not recovery — see the note in lib/response/api.ts buildTiles.
    key: "freezeRate",
    value: "14.8",
    suffix: "%",
    color: ACCENT,
    delta: { key: "ofAtRisk" },
  },
];

/** Time-to-freeze per case, minutes — the mockup's descending trend. */
export const MOCK_TREND = [
  720, 690, 540, 505, 430, 300, 260, 210, 150, 90, 60, 42, 33, 27,
];

// Every row here is fixture data by definition — this whole module is the
// offline fallback — so they are all marked seeded.
export const MOCK_CASES: ActiveCase[] = [
  { ref: "ITU-0417", type: "judol_deposit", atRisk: "Rp 48M", risk: "high", statusKey: "high", source: "baseline" },
  { ref: "ITU-0416", type: "investment_scam", atRisk: "Rp 31M", risk: "high", statusKey: "high", source: "baseline" },
  { ref: "ITU-0412", type: "crypto_phishing", atRisk: "Rp 9M", risk: "med", statusKey: "med", source: "baseline" },
  { ref: "ITU-0409", type: "mule_network", atRisk: "Rp 15M", risk: "low", statusKey: "frozen", source: "baseline" },
];

export function buildMockMetrics(range: RangeKey = "30d"): ResponseMetrics {
  return {
    tiles: MOCK_TILES,
    ops: MOCK_OPS,
    improvement: "27×",
    trend: MOCK_TREND,
    trendNow: "27 min",
    trendTag: "↓ 96% vs baseline",
    cases: MOCK_CASES,
    range,
    source: "mock",
  };
}
