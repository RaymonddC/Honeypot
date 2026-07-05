/**
 * Local fallback demo data — ported from the approved Investigation mockup
 * (scratchpad/ittu-mockup.html). Used whenever the backend API is
 * unreachable so the screen always renders standalone.
 */

import type {
  FeatureBar,
  GraphNode,
  ReasoningStep,
  WalletDetail,
  WalletGraph,
} from "./types";
import { shortAddr } from "./types";

/** Backend POC fixture source wallet (P1-Backend demo dataset). */
export const DEFAULT_ADDRESS = "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6";

/* ── Gary's canonical 12 features (docs/TAKEDOWN-Design.md) ───────────── */
const FEATURE_NAMES = [
  "Rapid-relay rate",
  "In/out ratio",
  "Tx velocity",
  "Unique counterparties",
  "Round-number %",
  "Account age (inv.)",
  "Fan-in/out ratio",
  "Time-dist. entropy",
  "Chain depth",
  "Volume (total/mean)",
  "Max tx size",
  "Self-loop count",
] as const;

const feats = (v: number[]): FeatureBar[] =>
  FEATURE_NAMES.map((name, i) => ({ name, percentile: v[i] ?? 0 }));

/* ── Graph (13 nodes / 14 edges, peeling chain 0→2→5→9) ───────────────── */
const ADDR = [
  DEFAULT_ADDRESS, //                     0 · main, high
  "TB2mVx4cQpL8dR1nS7kYwE3fJ9hK", //      1 · med
  "TKQb31FnWc8vXz5mP4dLrJqY8f2c", //      2 · high (peel hop)
  "TAe5cN8bXk2wPq9dL4mRv7ZsU3tG", //      3 · low
  "TCx7pW2eJm9kQ4vB8nT5rLgD1aF6", //      4 · low
  "TF9Lm2WkVd6xRq8pJc4nBtE73aa1", //      5 · high (peel hop)
  "TWn4rQt7eKp2mXv9dJ5bLhS8wc02", //      6 · med (fan-out)
  "TDq3fY8vLp5wRn2kM7cX9eBjT4u", //       7 · low
  "TEj6bK4nWm2xPv8qL3dR7cFyH5s", //       8 · med
  "TNVQyKgdxDGrCPFf8dW2QmSbEnw9", //      9 · exchange (Indodax)
  "TGu8dP3kXw6mQn1vB9rL4eJcZ7h", //      10 · low
  "THy2eM7bVk4pXq9wN3dR8cLfA5j", //      11 · low
  "TJs5cQ9nWv3kPm7xL2bR6dYeG8w", //      12 · low
];

interface N {
  i: number;
  x: number;
  y: number;
  r: number;
  risk: GraphNode["risk"];
  score: number;
  label?: string;
  main?: boolean;
}

const NODES: N[] = [
  { i: 0, x: 120, y: 232, r: 26, risk: "high", score: 0.91, main: true },
  { i: 1, x: 250, y: 120, r: 13, risk: "medium", score: 0.5 },
  { i: 2, x: 255, y: 212, r: 16, risk: "high", score: 0.84 },
  { i: 3, x: 240, y: 322, r: 12, risk: "low", score: 0.16 },
  { i: 4, x: 360, y: 82, r: 11, risk: "low", score: 0.16 },
  { i: 5, x: 382, y: 172, r: 15, risk: "high", score: 0.88 },
  { i: 6, x: 372, y: 272, r: 13, risk: "medium", score: 0.61 },
  { i: 7, x: 360, y: 362, r: 11, risk: "low", score: 0.16 },
  { i: 8, x: 500, y: 132, r: 12, risk: "medium", score: 0.5 },
  { i: 9, x: 512, y: 226, r: 19, risk: "exchange", score: 0, label: "Indodax" },
  { i: 10, x: 496, y: 332, r: 11, risk: "low", score: 0.16 },
  { i: 11, x: 622, y: 182, r: 12, risk: "low", score: 0.16 },
  { i: 12, x: 626, y: 276, r: 12, risk: "low", score: 0.16 },
];

/** [from, to, amount USDT, peel?] */
const EDGES: Array<[number, number, number, boolean?]> = [
  [0, 1, 12400],
  [0, 2, 48200, true],
  [0, 3, 8200],
  [2, 5, 47100, true],
  [2, 6, 40000],
  [1, 4, 6300],
  [5, 8, 9800],
  [5, 9, 46000, true],
  [6, 9, 41000],
  [6, 10, 3600],
  [3, 7, 2100],
  [9, 11, 15000],
  [9, 12, 12000],
  [8, 9, 9100],
];

const VOLUMES: Record<number, string> = {
  0: "$412,880",
  2: "$198,400",
  5: "$171,200",
  6: "$88,300",
  9: "$4.2M / day",
};

const MOCK_GRAPH: WalletGraph = {
  nodes: NODES.map((n) => ({
    id: ADDR[n.i],
    label: n.main ? shortAddr(ADDR[n.i]) : n.label,
    risk: n.risk,
    score: n.score,
    size: n.r * 2,
    isMain: n.main,
    position: { x: n.x, y: n.y },
    volume: VOLUMES[n.i],
  })),
  edges: EDGES.map(([a, b, amount, peel]) => ({
    id: `${ADDR[a]}->${ADDR[b]}`,
    source: ADDR[a],
    target: ADDR[b],
    amount,
    isPeel: peel,
  })),
};

/* ── Rich per-wallet detail (ported from the mockup's D map) ──────────── */
const step = (
  n: number,
  tool: string,
  detail: string,
  duration: string | null,
  verdict?: WalletDetail["risk"],
): ReasoningStep => ({ step: n, tool, detail, duration, verdict });

const MOCK_DETAILS: Record<string, WalletDetail> = {
  [ADDR[0]]: {
    address: ADDR[0],
    shortAddress: shortAddr(ADDR[0]),
    risk: "high",
    score: 0.91,
    confidence: 0.88,
    method: "ISOLATION-FOREST · anomaly triage",
    volume: "$412,880",
    counterparties: "37",
    firstSeen: "18 May 2026",
    tags: "scam · relay",
    tagRisk: "high",
    patterns: [
      { icon: "⛓", severity: "high", name: "Peeling chain", evidence: "6-hop sequential, ~2% peel/hop" },
      { icon: "⚡", severity: "high", name: "Rapid relay", evidence: "in/out 0.97 · forwarded <5 min" },
      { icon: "◈", severity: "medium", name: "Fan-out dispersal", evidence: "1 → 14 outputs" },
    ],
    features: feats([97, 96, 78, 64, 71, 88, 58, 74, 69, 76, 81, 8]),
    transactions: [
      { direction: "out", amount: "$48,200", counterparty: "→ TKQb31…8f2c", time: "12:04" },
      { direction: "in", amount: "$50,000", counterparty: "← TX2mR…9p", time: "11:58" },
      { direction: "out", amount: "$46,900", counterparty: "→ TF9Lm2…3aa1", time: "12:11" },
      { direction: "out", amount: "$41,000", counterparty: "→ Indodax", time: "12:23" },
    ],
    reasoning: [
      step(1, "fetch_transfers()", "pulled 214 USDT-TRC20 transfers from TRONSCAN, cached", "120ms"),
      step(2, "compute_features()", "12 indicators; in/out 0.97 + rapid-relay 0.97 exceed threshold", "44ms"),
      step(3, "isolation_forest()", "anomaly score 0.91 — top 3% of population", "31ms"),
      step(4, "detect_patterns()", "peeling-chain + rapid-relay fired; traced to exchange deposit TKQb31…8f2c", "58ms"),
      step(5, "assess()", "pass-through mule forwarding to Indodax within layering window", null, "high"),
    ],
  },
  [ADDR[2]]: {
    address: ADDR[2],
    shortAddress: shortAddr(ADDR[2]),
    risk: "high",
    score: 0.84,
    confidence: 0.83,
    method: "ISOLATION-FOREST · anomaly triage",
    volume: "$198,400",
    counterparties: "22",
    firstSeen: "21 May 2026",
    tags: "relay",
    tagRisk: "high",
    patterns: [
      { icon: "⛓", severity: "high", name: "Peeling chain", evidence: "part of 6-hop chain" },
      { icon: "⚡", severity: "high", name: "Rapid relay", evidence: "in/out 0.94" },
    ],
    features: feats([91, 93, 66, 48, 60, 72, 44, 68, 77, 61, 66, 4]),
    transactions: [
      { direction: "in", amount: "$48,200", counterparty: "← TX9dQp…", time: "12:04" },
      { direction: "out", amount: "$47,100", counterparty: "→ TF9Lm2…3aa1", time: "12:07" },
      { direction: "out", amount: "$1,050", counterparty: "→ Tzz…7k", time: "12:09" },
    ],
    reasoning: [
      step(1, "fetch_transfers()", "96 transfers, second hop from source", "88ms"),
      step(2, "compute_features()", "near-pure pass-through, retains ~1%", "39ms"),
      step(3, "isolation_forest()", "anomaly 0.84", "28ms"),
      step(4, "detect_patterns()", "continues the peeling chain toward exchange", "41ms"),
      step(5, "assess()", "intermediary relay node", null, "high"),
    ],
  },
  [ADDR[5]]: {
    address: ADDR[5],
    shortAddress: shortAddr(ADDR[5]),
    risk: "high",
    score: 0.88,
    confidence: 0.81,
    method: "ISOLATION-FOREST · anomaly triage",
    volume: "$171,200",
    counterparties: "19",
    firstSeen: "21 May 2026",
    tags: "relay · mixer-adj",
    tagRisk: "high",
    patterns: [
      { icon: "⛓", severity: "high", name: "Peeling chain", evidence: "penultimate hop" },
      { icon: "⚡", severity: "high", name: "Rapid relay", evidence: "in/out 0.96" },
      { icon: "◇", severity: "medium", name: "Mixer-adjacent", evidence: "1 hop from tagged mixer" },
    ],
    features: feats([94, 95, 59, 41, 55, 70, 39, 63, 82, 57, 62, 6]),
    transactions: [
      { direction: "in", amount: "$47,100", counterparty: "← TKQb31…8f2c", time: "12:07" },
      { direction: "out", amount: "$46,000", counterparty: "→ Indodax", time: "12:14" },
    ],
    reasoning: [
      step(1, "fetch_transfers()", "61 transfers", "74ms"),
      step(2, "compute_features()", "mixer-adjacent counterparty detected", "36ms"),
      step(3, "isolation_forest()", "anomaly 0.88", "27ms"),
      step(4, "detect_patterns()", "forwards to Indodax hot wallet", "44ms"),
      step(5, "assess()", "final relay before cash-out", null, "high"),
    ],
  },
  [ADDR[6]]: {
    address: ADDR[6],
    shortAddress: shortAddr(ADDR[6]),
    risk: "medium",
    score: 0.61,
    confidence: 0.7,
    method: "ISOLATION-FOREST · anomaly triage",
    volume: "$88,300",
    counterparties: "26",
    firstSeen: "19 May 2026",
    tags: "fan-out",
    tagRisk: "medium",
    patterns: [
      { icon: "◈", severity: "medium", name: "Fan-out dispersal", evidence: "1 → 11 outputs" },
    ],
    features: feats([58, 62, 71, 84, 49, 55, 86, 52, 41, 48, 45, 2]),
    transactions: [
      { direction: "in", amount: "$40,000", counterparty: "← TX9dQp…", time: "12:02" },
      { direction: "out", amount: "$3,600", counterparty: "→ 11 wallets", time: "12:06" },
    ],
    reasoning: [
      step(1, "fetch_transfers()", "130 transfers, high fan-out", "92ms"),
      step(2, "compute_features()", "84th pct counterparties", "40ms"),
      step(3, "isolation_forest()", "anomaly 0.61", "29ms"),
      step(4, "detect_patterns()", "fan-out dispersal to many small wallets", "43ms"),
      step(5, "assess()", "dispersal node, monitor", null, "medium"),
    ],
  },
  [ADDR[9]]: {
    address: ADDR[9],
    shortAddress: "Indodax hot wallet",
    risk: "exchange",
    score: 0,
    confidence: 0.99,
    method: "TAGGED · OJK-licensed exchange",
    volume: "$4.2M / day",
    counterparties: "12k+",
    firstSeen: "2021",
    tags: "exchange · licensed",
    tagRisk: "exchange",
    patterns: null,
    features: null,
    transactions: [
      { direction: "in", amount: "$46,000", counterparty: "← TF9Lm2…3aa1", time: "12:14" },
      { direction: "in", amount: "$41,000", counterparty: "← TX9dQp…", time: "12:23" },
    ],
    reasoning: [
      step(1, "address_tags()", "matched OJK-licensed exchange · Indodax", "12ms"),
      step(2, "assess()", "cash-out endpoint · file freeze/flag request via UNCOVER", null, "exchange"),
    ],
  },
};

/* ── Thin deterministic detail for nodes without a rich entry ─────────── */
export function mockBasicDetail(node: GraphNode): WalletDetail {
  const h = [...node.id].reduce((a, c) => (a * 31 + c.charCodeAt(0)) >>> 0, 7);
  const low = node.risk === "low";
  return {
    address: node.id,
    shortAddress: shortAddr(node.id),
    risk: node.risk,
    score: node.score,
    confidence: 0.6,
    method: "ISOLATION-FOREST · anomaly triage",
    volume: `$${(h % 14) + 3},${String((h * 137) % 900 + 100).padStart(3, "0")}`,
    counterparties: String((h % 11) + 3),
    firstSeen: "2026",
    tags: low ? "—" : "fan-out",
    tagRisk: node.risk,
    patterns: low
      ? []
      : [{ icon: "◈", severity: "medium", name: "Fan-out dispersal", evidence: "minor" }],
    features: null,
    transactions: [
      {
        direction: "in",
        amount: `$${(h % 9) + 1},200`,
        counterparty: "← upstream",
        time: "—",
      },
    ],
    reasoning: [
      step(1, "fetch_transfers()", `limited history (${(h % 40) + 6} txs)`, "—"),
      step(2, "isolation_forest()", `anomaly ${node.score.toFixed(2)} — within normal range`, "—"),
    ],
  };
}

/* ── Public: build the mock investigation for any entered address ─────── */
export function buildMockInvestigation(address: string): {
  graph: WalletGraph;
  details: Record<string, WalletDetail>;
} {
  const main = address.trim() || DEFAULT_ADDRESS;
  const graph: WalletGraph = JSON.parse(JSON.stringify(MOCK_GRAPH));
  const details: Record<string, WalletDetail> = JSON.parse(
    JSON.stringify(MOCK_DETAILS),
  );

  if (main !== DEFAULT_ADDRESS) {
    for (const n of graph.nodes) {
      if (n.id === DEFAULT_ADDRESS) {
        n.id = main;
        n.label = shortAddr(main);
      }
    }
    for (const e of graph.edges) {
      if (e.source === DEFAULT_ADDRESS) e.source = main;
      if (e.target === DEFAULT_ADDRESS) e.target = main;
      e.id = `${e.source}->${e.target}`;
    }
    const d = details[DEFAULT_ADDRESS];
    delete details[DEFAULT_ADDRESS];
    details[main] = { ...d, address: main, shortAddress: shortAddr(main) };
  }

  return { graph, details };
}
