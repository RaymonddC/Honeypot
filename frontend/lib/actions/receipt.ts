/**
 * Dispatch receipt — a self-contained confirmation of a dispatched action
 * bundle: which agencies were notified, over which channel, the requested
 * action, and the delivery status, with the evidence hash. Same HTML powers
 * the preview and the download.
 */

import type { ActionBundle, DispatchTarget } from "./types";

const esc = (s: unknown): string =>
  String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string,
  );

function typeOf(t: DispatchTarget): string {
  const at = (t.agencyType ?? "").toLowerCase();
  if (at) return at;
  const n = t.name.toLowerCase();
  if (n.includes("ppatk") || n.includes("ojk")) return "regulator";
  if (n.includes("bank")) return "bank";
  if (/indodax|tokocrypto|reku|exchange|binance/.test(n)) return "exchange";
  if (n.includes("bareskrim") || n.includes("pol")) return "police";
  return "—";
}

function channelOf(t: DispatchTarget): string {
  if (t.channel) return t.channel;
  switch (typeOf(t)) {
    case "regulator":
      return "goAML";
    case "bank":
      return "IASC";
    case "exchange":
      return "Compliance API";
    case "police":
      return "Secure email";
    default:
      return "Secure channel";
  }
}

const STATUS_TEXT: Record<string, string> = {
  mock: "Terkirim · mock sink",
  sent: "Terkirim / Sent",
  acknowledged: "Diterima / Ack",
  queued: "Antrian / Queued",
  failed: "Gagal / Failed",
  draft: "Draf",
};

export function receiptFilename(): string {
  return `dispatch-receipt-${new Date().toISOString().slice(0, 10)}.html`;
}

export function buildDispatchReceiptHtml(bundle: ActionBundle): string {
  const now = new Date();
  const ref = `DSP-${(bundle.caseRef.match(/\d+/)?.[0] ?? "0417").slice(-4)}/${now.getFullYear()}`;
  const rows = bundle.targets
    .map(
      (t, i) => `
      <tr>
        <td>${i + 1}.</td>
        <td><b>${esc(t.name)}</b><br><small>${esc(typeOf(t))}</small></td>
        <td>${esc(channelOf(t))}</td>
        <td>${esc(t.action)}</td>
        <td class="st">${esc(STATUS_TEXT[t.status] ?? t.status)}</td>
      </tr>`,
    )
    .join("");
  const docs = bundle.documents
    .map((d) => `${esc(d.title)}${d.sha256 ? ` <span class="mono">(${esc(d.sha256)})</span>` : ""}`)
    .join(" · ");

  return `<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bukti Pengiriman — ${esc(bundle.caseRef)}</title>
<style>
  :root { --ink:#111827; --muted:#6b7280; --line:#d1d5db; --accent:#0d9488; --head:#f3f4f6; }
  * { box-sizing:border-box; }
  body { margin:0; background:#f3f4f6; color:var(--ink); font:13px/1.6 Arial, Helvetica, sans-serif; }
  .page { max-width:760px; margin:0 auto; background:#fff; padding:44px 52px 56px; box-shadow:0 1px 3px rgba(0,0,0,.1); }
  .top { display:flex; align-items:center; gap:14px; border-bottom:2.5px solid var(--ink); padding-bottom:12px; }
  .crest { width:44px; height:44px; flex:none; border:1.5px solid var(--accent); border-radius:50%;
    display:grid; place-items:center; font-size:19px; color:var(--accent); font-weight:700; }
  .brand { font-size:12px; letter-spacing:.14em; text-transform:uppercase; color:var(--accent); font-weight:700; }
  h1 { font-size:19px; margin:2px 0 0; }
  .meta { display:flex; flex-wrap:wrap; gap:4px 28px; margin:16px 0 6px; font-size:12.5px; }
  .meta b { color:var(--ink); }
  .meta span { color:var(--muted); }
  table { width:100%; border-collapse:collapse; margin:14px 0; font-size:12.5px; }
  th, td { border:1px solid var(--line); padding:6px 9px; text-align:left; vertical-align:top; }
  th { background:var(--head); font-size:11px; text-transform:uppercase; letter-spacing:.03em; }
  td small { color:var(--muted); text-transform:capitalize; }
  td.st { font-weight:700; color:#b45309; white-space:nowrap; }
  .mono { font-family:ui-monospace, monospace; }
  .note { margin-top:8px; font-size:12px; }
  .foot { margin-top:26px; border-top:1px solid var(--line); padding-top:12px; font-size:10.5px; line-height:1.6; color:var(--muted); }
  @media print { body { background:#fff; } .page { box-shadow:none; padding:0; } }
</style></head><body><div class="page">
  <div class="top">
    <div class="crest">◈</div>
    <div>
      <div class="brand">ITTU · UNCOVER</div>
      <h1>Bukti Pengiriman · Dispatch Receipt</h1>
    </div>
  </div>

  <div class="meta">
    <span>No. Kirim: <b>${esc(ref)}</b></span>
    <span>Perkara: <b>${esc(bundle.caseRef)}</b></span>
    <span>Waktu: <b>${esc(now.toLocaleString())}</b></span>
    <span>Status: <b>${bundle.dispatched ? "DIKIRIM / DISPATCHED" : "DRAF"}</b></span>
  </div>

  <table>
    <thead><tr><th style="width:30px">No.</th><th>Instansi Tujuan</th><th>Kanal</th><th>Tindakan diminta</th><th>Status</th></tr></thead>
    <tbody>${rows || `<tr><td colspan="5" style="color:var(--muted)">Tidak ada tujuan.</td></tr>`}</tbody>
  </table>

  <p class="note"><b>Ringkasan:</b> ${esc(bundle.summary)}. Dokumen terlampir: ${docs || "—"}.</p>

  <div class="foot">
    Bukti pengiriman keluaran sistem ITTU. Pengiriman bersifat <b>human-gated</b> — dikonfirmasi oleh analis berwenang.
    Pada mode POC pengiriman diarahkan ke <b>mock sink</b> (tidak ada data yang keluar); pada mode LIVE ke kanal resmi tiap instansi (goAML · IASC · API kepatuhan).
    Integritas berkas: SHA-256 <span class="mono">${esc(bundle.evidenceHash)}</span> (rantai kustodi, UU ITE Pasal 5). Dicetak: ${esc(now.toLocaleString())}.
  </div>
</div></body></html>`;
}
