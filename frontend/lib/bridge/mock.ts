/**
 * Local fallback demo data — ported from the approved Bridge View mockup
 * (scratchpad/ittu-mockup.html · #bridge section). Used whenever the backend
 * API is unreachable so the screen always renders standalone.
 *
 * Case template: PT A2Z (Rp 530 M · 4,656 accounts · 22 banks).
 */

import type {
  BridgeData,
  BridgeSankeyData,
  BridgeStats,
  MuleNetworkStats,
  OnRampAlert,
} from "./types";
import { ACCENT_SOFT, AMBER } from "./types";

/* ── Sankey (mockup columns/links, expressed as a node/link graph) ─────── */

export const MOCK_SANKEY: BridgeSankeyData = {
  nodes: [
    // fiat · simulated (amber)
    { id: "qris-a", name: "QRIS shell merchants · cluster A", nameKey: "qrisA", label: "QRIS merchants", labelKey: "qrisShort", color: "#7a7f87" },
    { id: "qris-b", name: "QRIS shell merchants · cluster B", nameKey: "qrisB", color: "#7a7f87" },
    { id: "qris-c", name: "QRIS shell merchants · cluster C", nameKey: "qrisC", color: "#7a7f87" },
    { id: "mule-a", name: "Mule accounts · M-07 / M-03", nameKey: "muleA", label: "Mule accounts", labelKey: "muleShort", color: "#9aa0a8" },
    { id: "mule-b", name: "Mule accounts · M-11 / M-04", nameKey: "muleB", color: "#9aa0a8" },
    // bridge → crypto · real TRON (cyan → sky → blue)
    { id: "exchange", name: "Exchange deposits · Indodax / Tokocrypto / Reku", nameKey: "exchange", label: "Exchange deposits", labelKey: "exchangeShort", color: "#0088e6" },
    { id: "usdt", name: "USDT-TRC20 wallets", nameKey: "usdt", label: "USDT wallets", labelKey: "usdtShort", color: "#0099ff" },
    { id: "foreign", name: "Foreign destinations", nameKey: "foreign", label: "Foreign", labelKey: "foreignShort", color: "#4b5563" },
  ],
  // Values = mockup link weights (relative flow volume).
  links: [
    { source: "qris-a", target: "mule-a", value: 90 },
    { source: "qris-b", target: "mule-a", value: 60 },
    { source: "qris-c", target: "mule-b", value: 55 },
    { source: "qris-a", target: "mule-b", value: 40 },
    { source: "mule-a", target: "exchange", value: 150 },
    { source: "mule-b", target: "exchange", value: 90 },
    { source: "exchange", target: "usdt", value: 110 },
    { source: "exchange", target: "foreign", value: 120 },
  ],
};

/* ── Stat row ──────────────────────────────────────────────────────────── */

export const MOCK_STATS: BridgeStats = {
  qrisInflow: { value: "Rp 530.4", suffix: "M" },
  bridgedToCrypto: { value: "$34,120", color: ACCENT_SOFT },
  correlatedOnRamps: { value: "18", color: AMBER },
};

/* ── Suspected on-ramps (confidence-ranked) ────────────────────────────── */

export const MOCK_ALERTS: OnRampAlert[] = [
  {
    id: "corr-1",
    confidence: 0.94,
    title: "Mule cluster M-07 → Indodax",
    amountIdr: 48_200_000,
    deltaSeconds: 720,
    amountMatchPct: 99.1,
    wallet: "TDFYPobNrmKmxEBdG1wZfSF63u7bc3pUHt",
    toAddr: "TB8h4xVyk1u7zqbxCUfHFaKYFUa2VMHSr8",
    valueUsdt: 2930,
    ts: "2026-07-20T09:12:00Z",
  },
  {
    id: "corr-2",
    confidence: 0.89,
    title: "Mule cluster M-03 → Tokocrypto",
    amountIdr: 31_700_000,
    deltaSeconds: 1440,
    amountMatchPct: 97.4,
    wallet: "TJBrVeW4SUKCpgi8awdBe1zjCtWW4EXWJJ",
    toAddr: "TJiEbm7WKWBKEhdbvs1nFXC4CuJdhuPVna",
    valueUsdt: 1927,
    ts: "2026-07-20T09:36:00Z",
  },
  {
    id: "corr-3",
    confidence: 0.72,
    title: "Mule cluster M-11 → Reku",
    amountIdr: 15_000_000,
    deltaSeconds: 1680,
    amountMatchPct: 94.0,
    wallet: "TD7X3LdKzdociNXhTsjdUeYeVa8F8UZzjj",
    toAddr: "TXVmxz1Gnch4Afj9mTx1KqiLCCKoSbePuD",
    valueUsdt: 912,
    ts: "2026-07-20T10:04:00Z",
  },
];

/* ── Mule network stats ────────────────────────────────────────────────── */

export const MOCK_MULES: MuleNetworkStats = {
  clusters: "7",
  muleAccounts: "4,656",
  shellMerchants: "212",
  correlationWindow: "30 min",
};

export function buildMockBridge(): BridgeData {
  return {
    stats: MOCK_STATS,
    sankey: MOCK_SANKEY,
    alerts: MOCK_ALERTS,
    mules: MOCK_MULES,
    source: "mock",
  };
}
