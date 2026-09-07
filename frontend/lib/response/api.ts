/**
 * Response Dashboard API client (shape confirmed by P3-Backend):
 *
 *   GET /api/metrics/response?range=7d|30d|all → {
 *     cases_in_progress, cases_total,
 *     time_to_freeze: { avg_minutes, baseline_hours, improvement_factor },
 *     funds: { at_risk_idr, frozen_idr, at_risk_usdt, frozen_usdt,
 *              recovery_rate (fraction), baseline_recovery_rate (0.0476) },
 *     honeypot, wallets_scored, actions,
 *     trend: [{date, cases, frozen_idr, avg_ttf_minutes}, …oldest→newest],
 *     cases: [{case_id, title, crime_type, status: in_progress|frozen,
 *              at_risk_idr, frozen_idr, time_to_freeze_minutes, source}]
 *   }
 *
 * Base URL: NEXT_PUBLIC_API_URL (default http://localhost:8000). Any failure
 * falls back to the local mock (lib/response/mock.ts) so the screen stays
 * demoable standalone.
 */

import { buildMockMetrics } from "./mock";
import type {
  ActiveCase,
  CaseRisk,
  CaseStatusKey,
  MetricTile,
  OpsStat,
  RangeKey,
  ResponseMetrics,
} from "./types";
import {
  BASELINE_RECOVERY_PCT,
  ACCENT_SOFT,
  ACCENT,
  formatIDRShort,
  splitIDR,
  splitMinutes,
} from "./types";

import { apiFetch } from "@/lib/http";

/* eslint-disable @typescript-eslint/no-explicit-any */

async function request<T>(path: string, timeoutMs = 6000): Promise<T> {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await apiFetch(path, { signal: ctrl.signal });
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

/** Rates may arrive as fraction (0.4064) or percent (40.64). */
const asPct = (v: number | null): number | null =>
  v == null ? null : v <= 1 ? v * 100 : v;

/* ── Tiles ─────────────────────────────────────────────────────────────── */

function buildTiles(m: any, frozenCount: number | null): MetricTile[] {
  const ttfObj = m?.time_to_freeze ?? {};
  const funds = m?.funds ?? {};

  const cases = num(first(m?.cases_in_progress, m?.open_cases));
  const freezeMin = num(
    first(ttfObj?.avg_minutes, m?.avg_time_to_freeze_minutes),
  );
  const baselineHours = num(first(ttfObj?.baseline_hours, 12));
  const atRisk = num(first(funds?.at_risk_idr, m?.funds_at_risk_idr));
  const frozen = num(first(funds?.frozen_idr, m?.funds_frozen_idr));
  // Wire name is `recovery_rate`, but the backend computes frozen / at_risk —
  // that is a FREEZE rate. Funds frozen are not funds returned to the victim,
  // and nothing in this pipeline records a return, so it is labelled for what
  // it measures. It is deliberately NOT shown against the IASC 4.76% figure:
  // that baseline is a recovery rate, and beating it with a freeze rate would
  // be comparing two different quantities.
  const freezeRate = asPct(
    num(first(funds?.recovery_rate, m?.recovery_rate_pct)),
  );
  const casesTotal = num(first(m?.cases_total));

  const ttf = freezeMin != null ? splitMinutes(freezeMin) : null;
  const risk = atRisk != null ? splitIDR(atRisk) : null;
  const froz = frozen != null ? splitIDR(frozen) : null;

  // No display text here: this layer emits keys, MetricTiles resolves them
  // against the active locale. Building labels here is why the whole dashboard
  // rendered in English no matter which language was selected.
  return [
    {
      key: "casesInProgress",
      value: cases != null ? String(cases) : "—",
      delta:
        casesTotal != null
          ? { key: "ofTotal", values: { total: casesTotal } }
          : { key: "openActive" },
    },
    {
      key: "avgTimeToFreeze",
      value: ttf?.value ?? "—",
      suffix: ttf?.suffix,
      color: ACCENT,
      delta:
        ttf != null
          ? {
              key: "fromBaseline",
              values: { hours: baselineHours != null ? Math.round(baselineHours) : 12 },
            }
          : { key: "noFreezes" },
      deltaUp: ttf != null,
    },
    {
      key: "fundsAtRisk",
      value: risk?.value ?? "—",
      suffix: risk?.suffix,
      delta: { key: "flaggedOpen" },
    },
    {
      key: "fundsFrozen",
      value: froz?.value ?? "—",
      suffix: froz?.suffix,
      color: ACCENT_SOFT,
      delta:
        frozenCount != null && frozenCount > 0
          ? { key: "acked", values: { count: frozenCount } }
          : { key: "acknowledged" },
      deltaUp: frozenCount != null && frozenCount > 0,
    },
    {
      key: "freezeRate",
      value: freezeRate != null ? freezeRate.toFixed(1) : "—",
      suffix: "%",
      color: ACCENT,
      delta: { key: "ofAtRisk" },
    },
  ];
}

/* ── Operations pipeline ───────────────────────────────────────────────── */

const intStr = (v: unknown): string => {
  const n = num(v);
  return n != null ? Math.round(n).toLocaleString("en-US") : "—";
};

function buildOps(m: any): OpsStat[] {
  const hp = m?.honeypot ?? {};
  const a = m?.actions ?? {};
  const generated = num(a?.bundles_generated);
  const dispatched = num(a?.bundles_dispatched);
  return [
    { key: "honeypotSessions", glyph: "⬡", value: intStr(first(hp?.active_sessions, hp?.sessions)) },
    { key: "entitiesConfirmed", glyph: "◇", value: intStr(hp?.entities_confirmed) },
    { key: "walletsScored", glyph: "◉", value: intStr(m?.wallets_scored), color: ACCENT },
    { key: "documentsGenerated", glyph: "⚑", value: intStr(a?.documents_generated) },
    {
      key: "bundlesDispatched",
      glyph: "↗",
      value: dispatched != null ? `${dispatched}${generated != null ? `/${generated}` : ""}` : "—",
      color: ACCENT_SOFT,
    },
    { key: "agencyNotifications", glyph: "◈", value: intStr(a?.notifications_mock) },
  ];
}

/* ── Trend ─────────────────────────────────────────────────────────────── */

function normalizeTrend(m: any): number[] {
  const raw = first(m?.trend, m?.time_to_freeze_trend, m?.freeze_trend);
  if (!Array.isArray(raw)) return [];
  return raw
    .map((p) =>
      num(
        typeof p === "object"
          ? first(p?.avg_ttf_minutes, p?.minutes, p?.value, p?.y)
          : p,
      ),
    )
    .filter((v): v is number => v != null && v >= 0);
}

/* ── Cases table ───────────────────────────────────────────────────────── */

function normalizeCaseStatus(
  status: unknown,
  atRiskIdr: number | null,
): { risk: CaseRisk; statusKey: CaseStatusKey; statusRaw?: string } {
  const s = String(status ?? "").toLowerCase();
  if (s.includes("frozen") || s.includes("resolved"))
    return { risk: "low", statusKey: "frozen" };
  if (s.includes("high")) return { risk: "high", statusKey: "high" };
  if (s.includes("med")) return { risk: "med", statusKey: "med" };
  if (s.includes("low")) return { risk: "low", statusKey: "low" };
  // in_progress → tint by exposure (≥ Rp 30M reads high, mockup-style)
  if (s.includes("progress") || s.includes("open") || s.includes("active"))
    return atRiskIdr != null && atRiskIdr >= 30e6
      ? { risk: "high", statusKey: "high" }
      : { risk: "med", statusKey: "active" };
  // Unrecognised status: carry the raw value through rather than inventing a
  // label for it — the table shows it verbatim.
  return {
    risk: "med",
    statusKey: "unknown",
    statusRaw: s ? s[0].toUpperCase() + s.slice(1) : "—",
  };
}

function normalizeCases(m: any): ActiveCase[] {
  const items: any[] = first(m?.cases, m?.active_cases, m?.items, []) ?? [];
  return items.map((c, i): ActiveCase => {
    const atRisk = num(first(c?.at_risk_idr, c?.funds_at_risk_idr, c?.at_risk));
    const { risk, statusKey, statusRaw } = normalizeCaseStatus(
      first(c?.status, c?.risk_level, c?.risk),
      atRisk,
    );
    const ref = String(
      first(c?.case_id, c?.ref, c?.case_ref, c?.id, `case-${i}`),
    ).replace(/^CASE-/i, "");
    return {
      ref: ref.length > 12 ? `${ref.slice(0, 9)}…` : ref,
      type: String(first(c?.crime_type, c?.type, "—")),
      atRisk: atRisk != null ? formatIDRShort(atRisk) : "—",
      risk,
      statusKey,
      statusRaw,
      // Unknown provenance is treated as seeded, not real: over-marking a row
      // as demo data is a far cheaper mistake than passing one off as a case
      // this deployment actually worked.
      source: c?.source === "action" ? "action" : "baseline",
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

    const cases = normalizeCases(m);
    // Match on the KEY, not the rendered label: comparing against "Frozen"
    // meant this silently counted zero as soon as the label was translated.
    const frozenCount = cases.length
      ? cases.filter((c) => c.statusKey === "frozen").length
      : null;

    const tiles = buildTiles(m, frozenCount);
    if (tiles.every((t) => t.value === "—"))
      throw new Error("empty metrics from API");

    const trend = normalizeTrend(m);
    const last = trend.length ? trend[trend.length - 1] : null;

    // Improvement vs baseline: backend factor when present, else derived.
    const factor = num(m?.time_to_freeze?.improvement_factor);
    const baselineMin =
      (num(m?.time_to_freeze?.baseline_hours) ?? 12) * 60;
    const dropPct =
      factor != null && factor > 1
        ? Math.round((1 - 1 / factor) * 100)
        : last != null && baselineMin > 0
          ? Math.round((1 - last / baselineMin) * 100)
          : null;
    const improvement =
      factor != null && factor > 1
        ? `${factor >= 10 ? Math.round(factor) : factor.toFixed(1)}×`
        : undefined;

    return {
      tiles,
      ops: buildOps(m),
      improvement,
      trend,
      trendNow:
        last != null
          ? `${splitMinutes(last).value} ${splitMinutes(last).suffix}`
          : "—",
      trendTag:
        dropPct != null && dropPct > 0
          ? `↓ ${dropPct}% vs baseline`
          : "weekly avg",
      cases,
      range,
      source: "api",
    };
  } catch {
    return buildMockMetrics(range);
  }
}
