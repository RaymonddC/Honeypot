/**
 * Local fallback demo data — ported from the approved Response Dashboard
 * mockup (artifact d592d92c · #dash section). Used whenever the backend API
 * is unreachable so the screen always renders standalone.
 */

import type { ActiveCase, MetricTile, OpsStat, ResponseMetrics, RangeKey } from "./types";
import { ACCENT_SOFT, ACCENT } from "./types";

export const MOCK_OPS: OpsStat[] = [
  { label: "Honeypot sessions", glyph: "⬡", value: "3", sub: "INFILTRATE" },
  { label: "Entities confirmed", glyph: "◇", value: "17", sub: "wallets · accounts" },
  { label: "Wallets scored", glyph: "◉", value: "42", sub: "TAKEDOWN graph", color: ACCENT },
  { label: "Documents generated", glyph: "⚑", value: "9", sub: "UNCOVER" },
  { label: "Bundles dispatched", glyph: "↗", value: "3/5", sub: "human-gated", color: ACCENT_SOFT },
  { label: "Agency notifications", glyph: "📡", value: "8", sub: "routed" },
];

export const MOCK_TILES: MetricTile[] = [
  {
    label: "Cases in progress",
    value: "24",
    delta: "▲ 6 this week",
    deltaUp: true,
  },
  {
    label: "Avg time-to-freeze",
    value: "27",
    suffix: "min",
    color: ACCENT,
    delta: "▼ from 12h+ baseline",
    deltaUp: true,
  },
  {
    label: "Funds at risk",
    value: "Rp 4.8",
    suffix: "B",
    delta: "flagged, open cases",
  },
  {
    label: "Funds frozen",
    value: "Rp 712",
    suffix: "M",
    color: ACCENT_SOFT,
    delta: "▲ 14 freezes ack’d",
    deltaUp: true,
  },
  {
    // Freeze, not recovery — see the note in lib/response/api.ts buildTiles.
    label: "Freeze rate",
    value: "14.8",
    suffix: "%",
    color: ACCENT,
    delta: "of funds at risk, freeze dispatched",
  },
];

/** Time-to-freeze per case, minutes — the mockup's descending trend. */
export const MOCK_TREND = [
  720, 690, 540, 505, 430, 300, 260, 210, 150, 90, 60, 42, 33, 27,
];

// Every row here is fixture data by definition — this whole module is the
// offline fallback — so they are all marked seeded.
export const MOCK_CASES: ActiveCase[] = [
  { ref: "ITU-0417", type: "Judol relay", atRisk: "Rp 48M", risk: "high", statusLabel: "High", source: "baseline" },
  { ref: "ITU-0416", type: "Invest. scam", atRisk: "Rp 31M", risk: "high", statusLabel: "High", source: "baseline" },
  { ref: "ITU-0412", type: "Phishing", atRisk: "Rp 9M", risk: "med", statusLabel: "Med", source: "baseline" },
  { ref: "ITU-0409", type: "Mule net", atRisk: "Rp 15M", risk: "low", statusLabel: "Frozen", source: "baseline" },
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
