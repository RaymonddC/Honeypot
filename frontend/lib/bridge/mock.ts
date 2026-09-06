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
import { CYAN, AMBER } from "./types";

/* ── Sankey (mockup columns/links, expressed as a node/link graph) ─────── */

export const MOCK_SANKEY: BridgeSankeyData = {
  nodes: [
    // fiat · simulated (amber)
    { id: "qris-a", name: "QRIS shell merchants · cluster A", label: "QRIS merchants", color: "#7a7f87" },
    { id: "qris-b", name: "QRIS shell merchants · cluster B", color: "#7a7f87" },
    { id: "qris-c", name: "QRIS shell merchants · cluster C", color: "#7a7f87" },
    { id: "mule-a", name: "Mule accounts · M-07 / M-03", label: "Mule accounts", color: "#9aa0a8" },
    { id: "mule-b", name: "Mule accounts · M-11 / M-04", color: "#9aa0a8" },
    // bridge → crypto · real TRON (cyan → sky → blue)
    { id: "exchange", name: "Exchange deposits · Indodax / Tokocrypto / Reku", label: "Exchange deposits", color: "#0088e6" },
    { id: "usdt", name: "USDT-TRC20 wallets", label: "USDT wallets", color: "#0099ff" },
    { id: "foreign", name: "Foreign destinations", label: "Foreign", color: "#4b5563" },
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
  bridgedToCrypto: { value: "$34,120", color: CYAN },
  correlatedOnRamps: { value: "18", color: AMBER },
};

/* ── Suspected on-ramps (confidence-ranked) ────────────────────────────── */

export const MOCK_ALERTS: OnRampAlert[] = [
  {
    id: "corr-1",
    confidence: 0.94,
    title: "Mule cluster M-07 → Indodax",
    meta: "Rp 48.2M · Δt 12 min · amount match 99.1%",
    wallet: "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6mK2vN",
    toAddr: "TWd4xLqR8vB3nK7mP2sY9fH6jU1oI5tZ0a",
    valueUsdt: 2930,
    ts: "2026-07-20T09:12:00Z",
  },
  {
    id: "corr-2",
    confidence: 0.89,
    title: "Mule cluster M-03 → Tokocrypto",
    meta: "Rp 31.7M · Δt 24 min · amount match 97.4%",
    wallet: "TJ8kL3mNpQ7rS2tU9vW4xY6zA1bC5dE8fG",
    toAddr: "TKc2mB9nV4xQ7rL3sP8yF6hJ1uI5oW0tZa",
    valueUsdt: 1927,
    ts: "2026-07-20T09:36:00Z",
  },
  {
    id: "corr-3",
    confidence: 0.72,
    title: "Mule cluster M-11 → Reku",
    meta: "Rp 15.0M · Δt 28 min · amount match 94.0%",
    wallet: "TR7yH2gF9dS4aP1oI8uY3tW6qE5rT0zX2c",
    toAddr: "TLp5nQ8mK2vB7xR3sY9fH4jU6oI1tW0zAc",
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
