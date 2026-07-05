/**
 * Response Dashboard API client (docs/API-Contract.md):
 *
 *   GET /api/metrics/response?range=7d|30d|all → dashboard_metrics
 *
 * Base URL: NEXT_PUBLIC_API_URL (default http://localhost:8000). Shapes are
 * normalized defensively (P3-Backend confirmation pending); any failure
 * falls back to the local mock (lib/response/mock.ts) so the screen stays
 * demoable standalone.
 */

import { buildMockMetrics } from "./mock";
import type {
  ActiveCase,
  CaseRisk,
  MetricTile,
  RangeKey,
  ResponseMetrics,
} from "./types";
import {
  BASELINE_FREEZE,
  BASELINE_RECOVERY_PCT,
  CYAN,
  EMERALD,
  formatIDRShort,
  splitIDR,
  splitMinutes,
} from "./types";

const BASE = (
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"
).replace(/\/$/, "");

/* eslint-disable @typescript-eslint/no-explicit-any */

async function request<T>(path: string, timeoutMs = 6000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetch(`${BASE}/api${path}`, { signal: ctrl.signal });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (await res.json()) as T;
  } finally {
    clearTimeout(timer);
  }
}

const num = (v: unknown): number | null => {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

const first = (...vals: unknown[]): any =>
  vals.find((v) => v !== undefined && v !== null);

/* ── Tiles ─────────────────────────────────────────────────────────────── */

function buildTiles(m: any): MetricTile[] {
  const cases = num(
    first(m?.cases_in_progress, m?.open_cases, m?.active_cases_count),
  );
  const freezeMin = num(
    first(
      m?.avg_time_to_freeze_minutes,
      m?.avg_time_to_freeze_min,
      m?.time_to_freeze_minutes,
    ),
  );
  const atRisk = num(first(m?.funds_at_risk_idr, m?.funds_at_risk));
  const frozen = num(first(m?.funds_frozen_idr, m?.funds_frozen));
  const recovery = num(first(m?.recovery_rate_pct, m?.recovery_rate));
  const baseline =
    num(first(m?.baseline_recovery_rate_pct, m?.baseline_recovery_rate)) ??
    BASELINE_RECOVERY_PCT;
  const freezesAcked = num(first(m?.freezes_acknowledged, m?.freezes_acked));
  const casesDelta = num(first(m?.cases_delta_week, m?.cases_new_this_week));

  const ttf = freezeMin != null ? splitMinutes(freezeMin) : null;
  const risk = atRisk != null ? splitIDR(atRisk) : null;
  const froz = frozen != null ? splitIDR(frozen) : null;
  // recovery_rate may arrive as fraction (0.148) or percent (14.8)
  const recPct =
    recovery != null ? (recovery <= 1 ? recovery * 100 : recovery) : null;

  return [
    {
      label: "Cases in progress",
      value: cases != null ? String(cases) : "—",
      delta:
        casesDelta != null ? `▲ ${casesDelta} this week` : "open + active",
      deltaUp: casesDelta != null,
    },
    {
      label: "Avg time-to-freeze",
      value: ttf?.value ?? "—",
      suffix: ttf?.suffix,
      color: EMERALD,
      delta: `▼ from ${BASELINE_FREEZE} baseline`,
      deltaUp: true,
    },
    {
      label: "Funds at risk",
      value: risk?.value ?? "—",
      suffix: risk?.suffix,
      delta: "flagged, open cases",
    },
    {
      label: "Funds frozen",
      value: froz?.value ?? "—",
      suffix: froz?.suffix,
      color: CYAN,
      delta:
        freezesAcked != null
          ? `▲ ${freezesAcked} freezes ack’d`
          : "acknowledged freezes",
      deltaUp: freezesAcked != null,
    },
    {
      label: "Recovery rate",
      value: recPct != null ? recPct.toFixed(1) : "—",
      suffix: "%",
      color: EMERALD,
      delta: `▲ vs ${baseline}% baseline`,
      deltaUp: true,
    },
  ];
}

/* ── Trend ─────────────────────────────────────────────────────────────── */

function normalizeTrend(m: any): number[] {
  const raw = first(
    m?.time_to_freeze_trend,
    m?.trend,
    m?.freeze_trend,
    m?.trend_minutes,
  );
  if (!Array.isArray(raw)) return [];
  return raw
    .map((p) =>
      num(typeof p === "object" ? first(p?.minutes, p?.value, p?.y) : p),
    )
    .filter((v): v is number => v != null && v >= 0);
}

/* ── Cases table ───────────────────────────────────────────────────────── */

function normalizeRisk(v: unknown): { risk: CaseRisk; label: string } {
  const s = String(v ?? "").toLowerCase();
  if (s.includes("frozen") || s.includes("resolved"))
    return { risk: "low", label: "Frozen" };
  if (s.includes("high")) return { risk: "high", label: "High" };
  if (s.includes("med")) return { risk: "med", label: "Med" };
  if (s.includes("low")) return { risk: "low", label: "Low" };
  return { risk: "med", label: s ? s[0].toUpperCase() + s.slice(1) : "—" };
}

function normalizeCases(m: any): ActiveCase[] {
  const items: any[] = first(m?.active_cases, m?.cases, m?.items, []) ?? [];
  return items.map((c, i): ActiveCase => {
    const atRisk = num(first(c?.at_risk_idr, c?.funds_at_risk_idr, c?.at_risk));
    const { risk, label } = normalizeRisk(
      first(c?.status, c?.risk_level, c?.risk),
    );
    const ref = String(
      first(c?.ref, c?.case_ref, c?.title, c?.id, `case-${i}`),
    );
    return {
      // Long UUIDs → short mono ref
      ref: ref.length > 12 ? `${ref.slice(0, 8)}…` : ref,
      type: String(first(c?.crime_type, c?.type, "—")),
      atRisk: atRisk != null ? formatIDRShort(atRisk) : "—",
      risk,
      statusLabel: label,
    };
  });
}

/* ── Public surface ────────────────────────────────────────────────────── */

/**
 * Load the Response Dashboard payload for a range. Falls back to the mock
 * dataset when the API is unreachable or returns an empty read-model.
 */
export async function fetchResponseMetrics(
  range: RangeKey = "30d",
): Promise<ResponseMetrics> {
  try {
    const raw = await request<any>(`/metrics/response?range=${range}`);
    const m = first(raw?.metrics, raw?.data, raw) ?? {};

    const tiles = buildTiles(m);
    if (tiles.every((t) => t.value === "—"))
      throw new Error("empty metrics from API");

    const trend = normalizeTrend(m);
    const last = trend.length ? trend[trend.length - 1] : null;
    const firstV = trend.length ? trend[0] : null;
    const dropPct =
      last != null && firstV != null && firstV > 0
        ? Math.round((1 - last / firstV) * 100)
        : null;

    return {
      tiles,
      trend,
      trendNow:
        last != null
          ? `${splitMinutes(last).value} ${splitMinutes(last).suffix}`
          : "—",
      trendTag: dropPct != null ? `↓ ${dropPct}% vs baseline` : "trend",
      cases: normalizeCases(m),
      range,
      source: "api",
    };
  } catch {
    return buildMockMetrics(range);
  }
}
