/**
 * TAKEDOWN API client — aligned to P1-Backend's confirmed shapes:
 *
 *   POST /api/investigate {address, chain?}        → {address, chain, data_mode,
 *        graph: {nodes:[{data:{id,label,is_source,hop,risk,risk_score,tags,categories}}],
 *                edges:[{data:{id,source,target,value,token,ts,tx_hash}}]},
 *        scores: {<address>: <risk object>}}
 *   GET  /api/wallets/{addr}/graph?hops=3          → {address, hops, nodes, edges} (same elements, flat)
 *   GET  /api/wallets/{addr}/risk                  → {iso_forest_score, composite_risk, confidence,
 *        patterns: [{name, fired, score, evidence, description} ×5],
 *        reasoning: string[], features: {…Gary's 12}, tags: [{tag, category, …}], …}
 *
 * Base URL: NEXT_PUBLIC_API_URL (default http://localhost:8000). Any failure
 * falls back to the local mock (lib/investigation/mock.ts) so the screen
 * stays demoable standalone.
 */

import { buildMockInvestigation, mockBasicDetail } from "./mock";
import type {
  DataSource,
  FeatureBar,
  GraphEdge,
  GraphNode,
  PatternFlag,
  ReasoningStep,
  RiskLevel,
  TxEntry,
  WalletDetail,
  WalletGraph,
} from "./types";
import { shortAddr } from "./types";

import { apiFetch } from "@/lib/http";

/* eslint-disable @typescript-eslint/no-explicit-any */

/** Honest outcome of a trace, so LIVE never renders fabricated mock data.
 * "idle" = LIVE landing state before the analyst has traced anything. */
export type TraceStatus = "idle" | "ok" | "empty" | "rate_limited" | "error" | "mock";

/** Carries the HTTP status so callers can classify (404 empty / 503 rate-limited). */
class HttpError extends Error {
  constructor(readonly status: number) {
    super(`HTTP ${status}`);
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 6000,
): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await apiFetch(path, {
      ...init,
      signal: ctrl.signal,
    });
    if (!res.ok) throw new HttpError(res.status);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

/* ── helpers ───────────────────────────────────────────────────────────── */

function toRisk(v: unknown, score: number): RiskLevel {
  const s = String(v ?? "").toLowerCase();
  if (s.startsWith("ex")) return "exchange";
  if (s === "high") return "high";
  if (s === "medium" || s === "med") return "medium";
  if (s === "low") return "low";
  return score >= 0.7 ? "high" : score >= 0.4 ? "medium" : "low";
}

const clampPct = (n: number) =>
  Math.max(0, Math.min(100, Math.round(n)));

const money = (v: number) =>
  `$${Math.round(v).toLocaleString("en-US")}`;

function prettify(key: string): string {
  const s = key.replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

const isExchangeTags = (tags: any): boolean =>
  Array.isArray(tags) &&
  tags.some(
    (t) =>
      String(t?.category ?? "").toLowerCase() === "exchange" ||
      String(t ?? "").toLowerCase() === "exchange",
  );

/* ── graph normalization ──────────────────────────────────────────────── */

function normalizeGraph(raw: any, address: string): WalletGraph {
  const g = raw?.graph ?? raw ?? {};
  const rawNodes: any[] = g.nodes ?? [];
  const rawEdges: any[] = g.edges ?? [];

  const nodes: GraphNode[] = rawNodes.map((n0) => {
    const n = n0?.data ?? n0;
    const id = String(n.id ?? n.address ?? "");
    const score = Number(n.risk_score ?? n.score ?? 0);
    const categories: string[] = Array.isArray(n.categories)
      ? n.categories.map((c: any) => String(c).toLowerCase())
      : [];
    const isExchange = categories.includes("exchange");
    const risk: RiskLevel = isExchange ? "exchange" : toRisk(n.risk, score);
    const isMain = Boolean(n.is_source ?? n.is_main ?? id === address);
    return {
      id,
      // Only label the traced wallet + attributed nodes (mockup style).
      label:
        isMain || isExchange
          ? String(n.tags?.[0] ?? n.label ?? shortAddr(id))
          : undefined,
      risk,
      score,
      isMain,
      size: isMain ? 52 : isExchange ? 38 : 22 + Math.round(score * 12),
    };
  });

  const edges: GraphEdge[] = rawEdges.map((e0, i) => {
    const e = e0?.data ?? e0;
    const source = String(e.source ?? "");
    const target = String(e.target ?? "");
    return {
      id: String(e.id ?? `${source}->${target}#${i}`),
      source,
      target,
      amount: Number(e.value ?? e.amount ?? 0),
      ts: e.ts ? String(e.ts) : undefined,
      txHash: e.tx_hash ? String(e.tx_hash) : undefined,
    };
  });

  if (!nodes.length) throw new Error("empty graph from API");
  return { nodes, edges };
}

/**
 * Highlight the peeling chain from every fired peeling_chain pattern's
 * evidence hops. Edges are one-per-transfer (MultiDiGraph — parallel edges
 * possible), so match by tx_hash when the hop carries one; fall back to
 * from→to pairs otherwise.
 */
function applyPeelHighlight(
  graph: WalletGraph,
  scores: Record<string, any>,
): void {
  const hashes = new Set<string>();
  const pairs = new Set<string>();
  for (const risk of Object.values(scores ?? {})) {
    for (const p of risk?.patterns ?? []) {
      if (p?.name !== "peeling_chain" || !p?.fired) continue;
      for (const hop of p?.evidence?.hops ?? []) {
        if (hop?.tx_hash) hashes.add(String(hop.tx_hash));
        else if (hop?.from && hop?.to) pairs.add(`${hop.from}->${hop.to}`);
      }
    }
  }
  if (!hashes.size && !pairs.size) return;
  for (const e of graph.edges) {
    if (
      (e.txHash && hashes.has(e.txHash)) ||
      pairs.has(`${e.source}->${e.target}`)
    )
      e.isPeel = true;
  }
}

/* ── risk / detail normalization ──────────────────────────────────────── */

/** Gary's 12 features: display name + raw-value → 0..100 bar scale. */
const FEATURE_DISPLAY: Array<{
  key: string;
  name: string;
  scale: (v: number) => number;
}> = [
  { key: "rapid_relay_rate", name: "Rapid-relay rate", scale: (v) => v * 100 },
  { key: "inout_ratio", name: "In/out ratio", scale: (v) => v * 100 },
  { key: "tx_velocity", name: "Tx velocity", scale: (v) => v * 10 },
  { key: "unique_counterparties", name: "Unique counterparties", scale: (v) => v * 2 },
  { key: "round_number_pct", name: "Round-number %", scale: (v) => v * 100 },
  { key: "account_age_days", name: "Account age (inv.)", scale: (v) => 100 - Math.min(100, v) },
  { key: "fan_ratio", name: "Fan-in/out ratio", scale: (v) => v * 100 },
  { key: "time_entropy", name: "Time-dist. entropy", scale: (v) => v * 100 },
  { key: "chain_depth", name: "Chain depth", scale: (v) => v * 25 },
  { key: "total_volume", name: "Volume (total)", scale: (v) => (v > 0 ? (Math.log10(v) / 6) * 100 : 0) },
  { key: "max_tx_size", name: "Max tx size", scale: (v) => (v > 0 ? (Math.log10(v) / 5.5) * 100 : 0) },
  { key: "self_loop_count", name: "Self-loop count", scale: (v) => v * 20 },
];

function normalizeFeatures(raw: any): FeatureBar[] | null {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const known = FEATURE_DISPLAY.filter((f) => raw[f.key] != null);
  if (known.length) {
    return known.map((f) => ({
      name: f.name,
      percentile: clampPct(f.scale(Number(raw[f.key]) || 0)),
    }));
  }
  // Unknown feature keys — generic fallback.
  const out = Object.entries(raw).map(([k, v]) => {
    const n = Number(v) || 0;
    return { name: prettify(k), percentile: clampPct(n <= 1 ? n * 100 : n) };
  });
  return out.length ? out : null;
}

const PATTERN_ICONS: Array<[string, string]> = [
  ["peel", "⛓"],
  ["relay", "⚡"],
  ["circ", "♺"],
  ["struct", "▤"],
  ["fan", "◈"],
];

function normalizePatterns(raw: any): PatternFlag[] {
  if (!Array.isArray(raw)) return [];
  return raw
    .filter((p: any) => p && (p.fired ?? true))
    .map((p: any) => {
      const name = String(p.name ?? p.pattern ?? "pattern");
      const icon =
        PATTERN_ICONS.find(([k]) => name.toLowerCase().includes(k))?.[1] ??
        "◆";
      const score = Number(p.score ?? 0);
      return {
        name: prettify(name),
        severity: (score >= 0.66 ? "high" : "medium") as PatternFlag["severity"],
        evidence: String(p.description ?? p.evidence_summary ?? ""),
        icon,
      };
    });
}

/** Backend reasoning is a string array — map each line to a Glass Box step. */
function reasoningSteps(
  raw: any,
  level: RiskLevel,
  confidence: number,
  firedCount: number,
): ReasoningStep[] {
  const lines: any[] =
    typeof raw === "string" ? [raw] : Array.isArray(raw) ? raw : [];
  const steps: ReasoningStep[] = lines.map((line, i) => {
    const text = typeof line === "string" ? line : String(line?.detail ?? line);
    let tool = "score_wallet()";
    let detail = text;
    const pat = text.match(/^Pattern \[([a-z_]+)\] fired:?\s*(.*)$/i);
    if (pat) {
      tool = `${pat[1]}()`;
      detail = pat[2] || text;
    } else if (/isolation forest/i.test(text)) {
      tool = "isolation_forest()";
    } else if (/tag|exchange|attribut/i.test(text)) {
      tool = "address_tags()";
    }
    return { step: i + 1, tool, detail, duration: null };
  });
  // Closing verdict step (the mockup's assess() line).
  steps.push({
    step: steps.length + 1,
    tool: "assess()",
    detail:
      level === "exchange"
        ? "attributed exchange — cash-out endpoint, route via UNCOVER"
        : `composite risk with ${firedCount} typology pattern${firedCount === 1 ? "" : "s"} fired · confidence ${confidence.toFixed(2)}`,
    duration: null,
    verdict: level,
  });
  return steps;
}

function normalizeDetail(
  risk: any,
  address: string,
  node?: GraphNode,
): WalletDetail {
  const r = risk ?? {};
  const score = Number(
    r.iso_forest_score ?? r.risk_score ?? r.score ?? node?.score ?? 0,
  );
  const exchange = isExchangeTags(r.tags) || node?.risk === "exchange";
  const level: RiskLevel = exchange
    ? "exchange"
    : toRisk(r.composite_risk ?? r.risk, score);
  const confidence = Number(r.confidence ?? 0.6);
  const feats = r.features ?? {};
  const patterns = normalizePatterns(r.patterns);
  const ageDays = Number(feats.account_age_days);
  const tags: string = Array.isArray(r.tags)
    ? r.tags
        .map((t: any) => String(t?.tag ?? t))
        .filter(Boolean)
        .join(" · ")
    : "";

  return {
    address,
    shortAddress: shortAddr(address),
    risk: level,
    score,
    confidence,
    method: exchange
      ? "TAGGED · attributed exchange"
      : "ISOLATION-FOREST · anomaly triage",
    volume:
      feats.total_volume != null ? money(Number(feats.total_volume)) : "—",
    counterparties:
      feats.unique_counterparties != null
        ? String(feats.unique_counterparties)
        : "—",
    firstSeen: Number.isFinite(ageDays)
      ? ageDays < 1
        ? "<1 day"
        : `${Math.round(ageDays)}d ago`
      : "—",
    tags: tags || "—",
    tagRisk: level,
    patterns: exchange ? null : patterns,
    features: exchange ? null : normalizeFeatures(feats),
    transactions: [], // synthesized from graph edges below
    reasoning: reasoningSteps(r.reasoning, level, confidence, patterns.length),
  };
}

/** No tx-list endpoint — derive the wallet's transfers from graph edges. */
function txsFromGraph(address: string, graph?: WalletGraph): TxEntry[] {
  if (!graph) return [];
  const fmtTime = (ts?: string) => {
    if (!ts) return "—";
    const d = new Date(ts);
    return Number.isNaN(d.getTime())
      ? "—"
      : `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
  };
  const labelFor = (id: string) =>
    graph.nodes.find((n) => n.id === id)?.label ?? shortAddr(id);

  return graph.edges
    .filter((e) => e.source === address || e.target === address)
    .sort((a, b) => (a.ts ?? "").localeCompare(b.ts ?? ""))
    .slice(0, 10)
    .map((e): TxEntry => {
      const out = e.source === address;
      return {
        direction: out ? "out" : "in",
        amount: money(e.amount),
        counterparty: out ? `→ ${labelFor(e.target)}` : `← ${labelFor(e.source)}`,
        time: fmtTime(e.ts),
      };
    });
}

/* ── public surface ────────────────────────────────────────────────────── */

export interface InvestigationResult {
  graph: WalletGraph;
  source: DataSource;
  /** Honest outcome for the UI — LIVE never returns "mock". */
  status: TraceStatus;
  /** Pre-seeded wallet details (POST /investigate `scores`, or mock). */
  seedDetails: Record<string, WalletDetail>;
}

// A LIVE on-chain trace (bounded BFS + real API latency) can take tens of seconds
// on a busy wallet; POC returns instantly. Use a generous ceiling so a slow live
// trace completes instead of aborting to the mock fallback. Node-click /risk reads
// stay on the fast default — they read already-scored data.
const TRACE_TIMEOUT_MS = 120_000;

// Full BFS depth for POC (fixtures are tiny). LIVE overrides this to 1 per-call.
const MAX_HOPS = 3;

/**
 * Run an investigation. In LIVE mode the result is HONEST — a reachable-but-empty
 * wallet, a rate-limit, or a provider error each get their own status and never a
 * fabricated mock graph. Mock is only the POC / offline-demo dataset.
 */
export async function runInvestigation(
  address: string,
  live = false,
): Promise<InvestigationResult> {
  const enc = encodeURIComponent(address);
  // LIVE traces a busy wallet against real chains — keep it shallow (hops=1) so a
  // whale returns a small, fast graph within the fetch window instead of hundreds
  // of nodes. POC uses small deterministic fixtures, so full depth stays instant.
  const hops = live ? 1 : MAX_HOPS;
  let payload: any = null;
  let err: unknown = null;

  try {
    payload = await request<any>(
      "/investigate",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address, chain: "tron", hops }),
      },
      TRACE_TIMEOUT_MS,
    );
  } catch (e) {
    err = e;
  }

  // POST responded 200 but without a graph (older backend) → the graph read path.
  if (!err && !payload?.graph) {
    try {
      const raw = await request<any>(
        `/wallets/${enc}/graph?hops=${hops}`,
        undefined,
        TRACE_TIMEOUT_MS,
      );
      const mainRisk = await request<any>(`/wallets/${enc}/risk`).catch(
        () => null,
      );
      payload = { graph: raw, scores: mainRisk ? { [address]: mainRisk } : {} };
    } catch (e) {
      err = e;
    }
  }

  if (payload?.graph && !err) {
    const graph = normalizeGraph(payload, address);
    const scores: Record<string, any> = payload.scores ?? {};
    if (graph.nodes.length === 0) {
      return { graph, source: "api", status: "empty", seedDetails: {} };
    }
    applyPeelHighlight(graph, scores);
    const seedDetails: Record<string, WalletDetail> = {};
    for (const [addr, riskObj] of Object.entries(scores)) {
      const node = graph.nodes.find((n) => n.id === addr);
      const d = normalizeDetail(riskObj, addr, node);
      d.transactions = txsFromGraph(addr, graph);
      seedDetails[addr] = d;
    }
    return { graph, source: "api", status: "ok", seedDetails };
  }

  // Failure. POC (or unknown mode) → the offline demo dataset. LIVE → honest state,
  // NEVER mock: 404 = empty wallet, 503 = rate-limited, else = provider error.
  if (!live) {
    const { graph, details } = buildMockInvestigation(address);
    return { graph, source: "mock", status: "mock", seedDetails: details };
  }
  const status: TraceStatus =
    err instanceof HttpError
      ? err.status === 404
        ? "empty"
        : err.status === 503
          ? "rate_limited"
          : "error"
      : "error"; // timeout / network / unreachable
  return { graph: { nodes: [], edges: [] }, source: "api", status, seedDetails: {} };
}

/** GET /wallets/{addr}/risk for a clicked node; mock fallback on failure. */
export async function fetchWalletDetail(
  address: string,
  node: GraphNode | undefined,
  source: DataSource,
  graph?: WalletGraph,
): Promise<WalletDetail> {
  if (source === "api") {
    try {
      const risk = await request<any>(
        `/wallets/${encodeURIComponent(address)}/risk`,
      );
      const d = normalizeDetail(risk, address, node);
      d.transactions = txsFromGraph(address, graph);
      return d;
    } catch {
      /* fall through to mock */
    }
  }
  if (node) {
    const d = mockBasicDetail(node);
    if (source === "api") d.transactions = txsFromGraph(address, graph);
    return d;
  }
  const { details } = buildMockInvestigation(address);
  return (
    details[address] ??
    mockBasicDetail({ id: address, risk: "low", score: 0.16, size: 24 })
  );
}
