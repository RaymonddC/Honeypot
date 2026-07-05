/**
 * Local fallback demo data — ported from the approved Response Dashboard
 * mockup (artifact d592d92c · #dash section). Used whenever the backend API
 * is unreachable so the screen always renders standalone.
 */

import type { ActiveCase, MetricTile, ResponseMetrics, RangeKey } from "./types";
import { CYAN, EMERALD } from "./types";

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
    color: EMERALD,
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
    color: CYAN,
    delta: "▲ 14 freezes ack’d",
    deltaUp: true,
  },
  {
    label: "Recovery rate",
    value: "14.8",
    suffix: "%",
    color: EMERALD,
    delta: "▲ vs 4.76% baseline",
    deltaUp: true,
  },
];

/** Time-to-freeze per case, minutes — the mockup's descending trend. */
export const MOCK_TREND = [
  720, 690, 540, 505, 430, 300, 260, 210, 150, 90, 60, 42, 33, 27,
];

export const MOCK_CASES: ActiveCase[] = [
  { ref: "ITU-0417", type: "Judol relay", atRisk: "Rp 48M", risk: "high", statusLabel: "High" },
  { ref: "ITU-0416", type: "Invest. scam", atRisk: "Rp 31M", risk: "high", statusLabel: "High" },
  { ref: "ITU-0412", type: "Phishing", atRisk: "Rp 9M", risk: "med", statusLabel: "Med" },
  { ref: "ITU-0409", type: "Mule net", atRisk: "Rp 15M", risk: "low", statusLabel: "Frozen" },
];

export function buildMockMetrics(range: RangeKey = "30d"): ResponseMetrics {
  return {
    tiles: MOCK_TILES,
    trend: MOCK_TREND,
    trendNow: "27 min",
    trendTag: "↓ 96% vs baseline",
    cases: MOCK_CASES,
    range,
    source: "mock",
  };
}
