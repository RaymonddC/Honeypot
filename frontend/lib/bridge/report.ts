/**
 * Trace report — a self-contained, print-friendly HTML document built entirely
 * client-side from the BridgeData the panel already has. The same HTML string is
 * both previewed (in an <iframe srcDoc>) and downloaded, so what you see is
 * exactly what you save. No backend endpoint needed.
 */

import type { BridgeData } from "./types";
import { confidenceColor } from "./types";

const esc = (s: unknown): string =>
  String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string,
  );

/** Human file name for the download. */
export function traceReportFilename(): string {
  return `bridgewatch-trace-report-${new Date().toISOString().slice(0, 10)}.html`;
}

/** Save an HTML string to disk as a standalone document. */
export function downloadHtml(html: string, filename: string): void {
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
  } finally {
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
}

/** Build the full standalone trace report as an HTML string. */
export function buildTraceReportHtml(
  data: BridgeData,
  caseTitle?: string,
): string {
  const now = new Date();
  const nameOf = (id: string) =>
    data.sankey.nodes.find((n) => n.id === id)?.name ?? id;

  const flows = data.sankey.links
    .map((l) => ({ s: nameOf(l.source), t: nameOf(l.target), v: l.value }))
    .sort((a, b) => b.v - a.v);
  const totalFlow = data.sankey.links.reduce((s, l) => s + l.value, 0) || 1;

  const kpi = (label: string, value: string, sub?: string) => `
    <div class="kpi">
      <div class="kpi-l">${esc(label)}</div>
      <div class="kpi-v">${esc(value)}</div>
      ${sub ? `<div class="kpi-s">${esc(sub)}</div>` : ""}
    </div>`;

  const flowRows = flows
    .map(
      (f) => `
      <tr>
        <td>${esc(f.s)}</td>
        <td class="arrow">→</td>
        <td>${esc(f.t)}</td>
        <td class="num">${f.v.toLocaleString("en-US")}</td>
        <td class="num muted">${((f.v / totalFlow) * 100).toFixed(1)}%</td>
      </tr>`,
    )
    .join("");

  const alertRows = data.alerts
    .map(
      (a) => `
      <tr>
        <td><span class="dot" style="background:${confidenceColor(a.confidence)}"></span>${a.confidence.toFixed(2)}</td>
        <td>${esc(a.title)}</td>
        <td class="muted">${esc(a.meta)}</td>
      </tr>`,
    )
    .join("");

  const sourceLabel =
    data.source === "api" ? "Live backend API" : "Demo dataset (offline)";

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BridgeWatch Trace Report${caseTitle ? ` — ${esc(caseTitle)}` : ""}</title>
<style>
  :root { --ink:#0f172a; --muted:#64748b; --line:#e2e8f0; --accent:#0b5394; --bg:#f8fafc; }
  * { box-sizing:border-box; }
  body { margin:0; font:14px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif; color:var(--ink); background:#fff; }
  .wrap { max-width:820px; margin:0 auto; padding:40px 36px 64px; }
  .top { display:flex; justify-content:space-between; align-items:flex-start; border-bottom:3px solid var(--accent); padding-bottom:16px; margin-bottom:8px; }
  .brand { font-size:12px; letter-spacing:.14em; text-transform:uppercase; color:var(--accent); font-weight:700; }
  h1 { font-size:22px; margin:4px 0 2px; }
  .meta { font-size:12px; color:var(--muted); text-align:right; }
  .meta b { color:var(--ink); }
  h2 { font-size:13px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); margin:28px 0 10px; border-bottom:1px solid var(--line); padding-bottom:6px; }
  .kpis { display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:16px; }
  .kpi { border:1px solid var(--line); border-radius:10px; padding:12px 14px; background:var(--bg); }
  .kpi-l { font-size:10.5px; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }
  .kpi-v { font-size:22px; font-weight:800; margin-top:4px; letter-spacing:-.01em; }
  .kpi-s { font-size:11px; color:var(--muted); margin-top:2px; }
  table { width:100%; border-collapse:collapse; font-size:12.5px; }
  th { text-align:left; font-size:10.5px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); border-bottom:1px solid var(--line); padding:6px 8px; }
  td { padding:7px 8px; border-bottom:1px solid var(--line); }
  td.num { text-align:right; font-variant-numeric:tabular-nums; font-weight:600; }
  td.arrow { color:var(--accent); text-align:center; width:24px; }
  .muted { color:var(--muted); font-weight:400; }
  .dot { display:inline-block; width:8px; height:8px; border-radius:50%; margin-right:7px; vertical-align:middle; }
  .foot { margin-top:32px; padding-top:14px; border-top:1px solid var(--line); font-size:11px; color:var(--muted); line-height:1.6; }
  @media print { body { -webkit-print-color-adjust:exact; print-color-adjust:exact; } .wrap { padding:0; } }
</style></head>
<body><div class="wrap">
  <div class="top">
    <div>
      <div class="brand">ITTU · BridgeWatch</div>
      <h1>Fiat → Crypto Trace Report</h1>
      <div class="muted" style="font-size:12px">Where dirty rupiah becomes USDT — on-ramp correlation &amp; mule network</div>
    </div>
    <div class="meta">
      ${caseTitle ? `Case: <b>${esc(caseTitle)}</b><br>` : ""}
      Generated: <b>${esc(now.toLocaleString())}</b><br>
      Source: <b>${esc(sourceLabel)}</b>
    </div>
  </div>

  <h2>Summary</h2>
  <div class="kpis">
    ${kpi("QRIS inflow (sim)", `${data.stats.qrisInflow.value}${data.stats.qrisInflow.suffix ? " " + data.stats.qrisInflow.suffix : ""}`, "fiat entering the funnel")}
    ${kpi("Bridged to crypto", data.stats.bridgedToCrypto.value, "reached USDT / exchanges")}
    ${kpi("Correlated on-ramps", data.stats.correlatedOnRamps.value, "fiat↔crypto matches")}
  </div>

  <h2>Fund flow — paths by volume</h2>
  <table>
    <thead><tr><th>From</th><th></th><th>To</th><th style="text-align:right">Volume</th><th style="text-align:right">Share</th></tr></thead>
    <tbody>${flowRows || `<tr><td colspan="5" class="muted">No flows.</td></tr>`}</tbody>
  </table>

  <h2>Suspected on-ramps — ranked by confidence</h2>
  <table>
    <thead><tr><th>Conf.</th><th>Correlation</th><th>Evidence</th></tr></thead>
    <tbody>${alertRows || `<tr><td colspan="3" class="muted">No correlated on-ramps.</td></tr>`}</tbody>
  </table>

  <h2>Mule network</h2>
  <table>
    <tbody>
      <tr><td class="muted">Clusters (Louvain)</td><td class="num">${esc(data.mules.clusters)}</td></tr>
      <tr><td class="muted">Mule accounts</td><td class="num">${esc(data.mules.muleAccounts)}</td></tr>
      <tr><td class="muted">Shell merchants</td><td class="num">${esc(data.mules.shellMerchants)}</td></tr>
      <tr><td class="muted">Correlation window</td><td class="num">${esc(data.mules.correlationWindow)}</td></tr>
    </tbody>
  </table>

  <div class="foot">
    Fiat side is synthetic (PT A2Z parameters / PaySim) — real bank &amp; QRIS data isn't public; the crypto side is real TRON.
    On-ramps are ranked by fiat↔crypto correlation confidence (amount + timing match within the correlation window).
    This report is generated from the current BridgeWatch view for investigative reference — figures are decision-support, not a legal filing.
  </div>
</div></body></html>`;
}
