/**
 * TAKEDOWN / Investigation screen — frontend-canonical types.
 *
 * The API layer (lib/investigation/api.ts) normalizes whatever the backend
 * returns (docs/API-Contract.md) into these shapes; the mock fallback
 * (lib/investigation/mock.ts) produces them directly.
 */

export type RiskLevel = "low" | "medium" | "high" | "exchange";

export interface GraphNode {
  /** Full wallet address — used as the Cytoscape node id. */
  id: string;
  /** Short label rendered under the node (main wallet + exchanges). */
  label?: string;
  risk: RiskLevel;
  /** Composite / anomaly score 0..1 (0 for tagged exchanges). */
  score: number;
  /** Node diameter in px (risk/volume-scaled). */
  size: number;
  /** The traced (searched) wallet. */
  isMain?: boolean;
  /** Optional preset layout position (mock provides; API may not). */
  position?: { x: number; y: number };
  /** Display volume for the hover tooltip, e.g. "$412,880". */
  volume?: string;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  /** Transfer amount in USDT — drives edge width. */
  amount: number;
  /** Part of the highlighted peeling-chain path. */
  isPeel?: boolean;
  /** ISO timestamp of the transfer (used to synthesize tx lists). */
  ts?: string;
}

export interface WalletGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface PatternFlag {
  name: string;
  severity: "low" | "medium" | "high";
  evidence: string;
  icon?: string;
}

/** One of the 12 features, expressed as a population percentile 0..100. */
export interface FeatureBar {
  name: string;
  percentile: number;
}

export interface TxEntry {
  direction: "in" | "out";
  amount: string;
  counterparty: string;
  time: string;
}

export interface ReasoningStep {
  step: number;
  tool: string;
  detail: string;
  duration?: string | null;
  /** Colored verdict prefix on the final assess() step. */
  verdict?: RiskLevel;
}

export interface WalletDetail {
  address: string;
  shortAddress: string;
  risk: RiskLevel;
  score: number;
  confidence: number;
  /** Scoring method line under the gauge. */
  method: string;
  volume: string;
  counterparties: string;
  firstSeen: string;
  tags: string;
  tagRisk: RiskLevel;
  /** null → not applicable (exchange); [] → none fired. */
  patterns: PatternFlag[] | null;
  /** null → not computed (exchange / thin wallet). */
  features: FeatureBar[] | null;
  transactions: TxEntry[];
  reasoning: ReasoningStep[];
}

export type DataSource = "api" | "mock";

export const RISK_COLORS: Record<RiskLevel, string> = {
  low: "#10b981",
  medium: "#f5a524",
  high: "#ef4444",
  exchange: "#06b6d4",
};

export const RISK_LABELS: Record<RiskLevel, string> = {
  low: "Low",
  medium: "Med",
  high: "High",
  exchange: "Exchange",
};

export function shortAddr(address: string): string {
  return address.length > 12
    ? `${address.slice(0, 6)}…${address.slice(-4)}`
    : address;
}
