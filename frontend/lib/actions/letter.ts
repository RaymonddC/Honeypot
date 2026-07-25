/**
 * Official document generator — turns a generated ActionDocument into a formal,
 * agency-grade letter (freeze request) or report (STR/LTKM), rendered as a
 * self-contained HTML page that is both previewed and downloaded. Indonesian
 * official-correspondence conventions (kop surat, nomor/sifat/perihal, dasar
 * hukum, tembusan, tanda tangan), with English glosses.
 *
 * These are system-generated DRAFTS for a human officer to review and sign —
 * the footer makes that explicit, and the SHA-256 custody hash is stamped on.
 */

import type { ActionDocument, DispatchTarget } from "./types";

export interface LetterContext {
  agencyName: string;
  agencyType?: string;
  officerName: string;
  officerRole: string;
  caseRef: string;
  evidenceHash: string;
  targets: DispatchTarget[];
}

const esc = (s: unknown): string =>
  String(s ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c] as string,
  );

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

export function documentFilename(doc: ActionDocument): string {
  const kind = doc.kind === "freeze" ? "permohonan-pemblokiran" : "ltkm-str";
  return `${kind}-${new Date().toISOString().slice(0, 10)}.html`;
}

const field = (doc: ActionDocument, needle: string): string | undefined =>
  doc.fields.find((f) => f.label.toLowerCase().includes(needle))?.value;

/** Agency division line by type — a plausible unit for the letterhead. */
function divisionLine(ctx: LetterContext): string {
  const t = (ctx.agencyType ?? "").toLowerCase();
  if (t.includes("police") || /bareskrim|polri/i.test(ctx.agencyName))
    return "Direktorat Tindak Pidana Siber (Dittipidsiber)";
  if (t.includes("regulator") || /ppatk|ojk/i.test(ctx.agencyName))
    return "Unit Analisis & Kepatuhan Transaksi Keuangan";
  if (t.includes("bank")) return "Divisi Anti Pencucian Uang (APU-PPT)";
  if (t.includes("exchange")) return "Divisi Kepatuhan (Compliance)";
  return "Unit Penanganan Tindak Pidana Keuangan";
}

const refNo = (ctx: LetterContext, tag: string): string => {
  const num = (ctx.caseRef.match(/(\d[\d-]*)/)?.[1] ?? "0001").replace(/-/g, "");
  return `${num.slice(-4)}/${tag}/${new Date().getFullYear()}`;
};

const todayID = () =>
  new Date().toLocaleDateString("id-ID", { day: "numeric", month: "long", year: "numeric" });

const SHELL = (title: string, body: string) => `<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${esc(title)}</title>
<style>
  :root { --ink:#111827; --muted:#6b7280; --line:#d1d5db; --accent:#0d9488; }
  * { box-sizing:border-box; }
  body { margin:0; background:#f3f4f6; color:var(--ink);
    font:13.5px/1.65 "Times New Roman", Georgia, serif; }
  .page { max-width:820px; margin:0 auto; background:#fff; padding:52px 60px 64px;
    box-shadow:0 1px 3px rgba(0,0,0,.1); }
  .kop { display:flex; align-items:center; gap:16px; }
  .crest { width:52px; height:52px; flex:none; border:2px solid var(--accent);
    border-radius:50%; display:grid; place-items:center; font-size:22px; color:var(--accent); font-weight:700; }
  .kop .agency { font-size:19px; font-weight:700; letter-spacing:.02em; text-transform:uppercase; }
  .kop .sub { font-size:12.5px; }
  .kop .addr { font-size:11px; color:var(--muted); font-family:Arial, sans-serif; }
  .rule { border:0; border-top:3px solid var(--ink); margin:10px 0 4px; }
  .rule.thin { border-top:1px solid var(--ink); margin:0 0 22px; }
  .meta { border-collapse:collapse; margin:18px 0 8px; font-size:13px; }
  .meta td { padding:1px 0; vertical-align:top; }
  .meta td:first-child { width:78px; }
  .to { margin:16px 0 18px; font-size:13px; }
  p { margin:9px 0; text-align:justify; }
  table.items { width:100%; border-collapse:collapse; margin:12px 0; font-size:12.5px;
    font-family:Arial, sans-serif; }
  table.items th, table.items td { border:1px solid var(--line); padding:6px 9px; text-align:left; vertical-align:top; }
  table.items th { background:#f3f4f6; font-size:11px; text-transform:uppercase; letter-spacing:.03em; }
  .mono { font-family:ui-monospace, monospace; }
  ul.basis { margin:6px 0; padding-left:22px; }
  ul.basis li { margin:3px 0; }
  .urgent { display:inline-block; border:1.5px solid #b91c1c; color:#b91c1c; font-weight:700;
    font-family:Arial, sans-serif; font-size:11px; padding:1px 7px; border-radius:3px; letter-spacing:.04em; }
  .sign { margin-top:34px; width:290px; margin-left:auto; text-align:center; font-size:13px; }
  .sign .space { height:64px; }
  .sign .name { text-decoration:underline; font-weight:700; }
  .cc { margin-top:28px; font-size:11.5px; font-family:Arial, sans-serif; color:var(--muted); }
  .cc ol { margin:3px 0; padding-left:20px; }
  .foot { margin-top:30px; border-top:1px solid var(--line); padding-top:10px;
    font-family:Arial, sans-serif; font-size:10px; line-height:1.6; color:var(--muted); }
  h1.rep { font-size:17px; text-align:center; margin:6px 0 2px; letter-spacing:.03em; }
  h1.rep small { display:block; font-size:12px; font-weight:400; color:var(--muted); }
  h2.sec { font-size:12.5px; font-family:Arial, sans-serif; text-transform:uppercase;
    letter-spacing:.04em; margin:18px 0 6px; border-bottom:1px solid var(--line); padding-bottom:4px; }
  dl { margin:0; font-size:13px; } dl dt { color:var(--muted); font-family:Arial, sans-serif; font-size:11px; text-transform:uppercase; margin-top:8px; }
  dl dd { margin:1px 0 0; }
  @media print { body { background:#fff; } .page { box-shadow:none; padding:0; } }
</style></head><body><div class="page">${body}</div></body></html>`;

/* ── Freeze request — Surat Permohonan Pemblokiran ─────────────────────── */

function freezeLetter(doc: ActionDocument, ctx: LetterContext): string {
  const account = field(doc, "account");
  const wallet = field(doc, "wallet");
  const exchange = field(doc, "exchange");
  const atRisk = field(doc, "risk") ?? field(doc, "amount");
  const basis = field(doc, "basis");

  const rows: string[] = [];
  if (account)
    rows.push(
      `<tr><td>${rows.length + 1}.</td><td>Rekening bank<br><small>Bank account</small></td><td class="mono">${esc(account)}</td><td>Diduga rekening penerima / penampung (mule)</td></tr>`,
    );
  if (wallet)
    rows.push(
      `<tr><td>${rows.length + 1}.</td><td>Dompet kripto<br><small>USDT-TRC20 wallet</small></td><td class="mono">${esc(wallet)}</td><td>Diduga dompet pengumpul dana${exchange ? ` di ${esc(exchange)}` : ""}</td></tr>`,
    );
  if (!rows.length)
    rows.push(`<tr><td>1.</td><td>—</td><td class="mono">${esc(field(doc, "value") ?? "—")}</td><td>Objek pemblokiran</td></tr>`);

  const cc = ctx.targets.length
    ? `<div class="cc">Tembusan (cc):<ol>${ctx.targets
        .map((t) => `<li>${esc(t.name)}${t.action ? ` — ${esc(t.action)}` : ""}</li>`)
        .join("")}</ol></div>`
    : "";

  const body = `
  <div class="kop">
    <div class="crest">◈</div>
    <div>
      <div class="agency">${esc(ctx.agencyName)}</div>
      <div class="sub">${esc(divisionLine(ctx))}</div>
      <div class="addr">Republik Indonesia · Sistem Forensik Keuangan ITTU</div>
    </div>
  </div>
  <hr class="rule"><hr class="rule thin">

  <h1 class="rep">PERMOHONAN PEMBLOKIRAN REKENING &amp; DOMPET
    <small>Request to Freeze Accounts / Wallets — Suspected Financial Crime</small></h1>

  <table class="meta">
    <tr><td>Nomor</td><td>: ${esc(refNo(ctx, "PMB"))}</td></tr>
    <tr><td>Sifat</td><td>: <span class="urgent">SEGERA / URGENT</span></td></tr>
    <tr><td>Perkara</td><td>: ${esc(ctx.caseRef)}</td></tr>
    <tr><td>Kepada</td><td>: Kepala Divisi Kepatuhan / APU-PPT — Institusi Keuangan &amp; Penyedia Aset Kripto Terkait</td></tr>
    <tr><td>Tanggal</td><td>: ${esc(todayID())}</td></tr>
  </table>

  <h2 class="sec">A. Objek Pemblokiran / Freeze Targets</h2>
  <table class="items">
    <thead><tr><th style="width:34px">No.</th><th style="width:120px">Jenis</th><th>Identitas</th><th>Keterangan</th></tr></thead>
    <tbody>${rows.join("")}</tbody>
  </table>

  <h2 class="sec">B. Dasar Permohonan / Basis</h2>
  <p>Sehubungan dengan penanganan perkara <b>${esc(ctx.caseRef)}</b> terkait dugaan tindak pidana penipuan (<i>fraud</i>) dan pencucian uang, hasil analisis forensik keuangan kami mengindikasikan bahwa objek pada bagian A patut diduga digunakan untuk menerima dan/atau menampung dana hasil tindak pidana. Dengan ini kami memohon bantuan Saudara untuk <b>segera melakukan PEMBLOKIRAN</b> terhadap objek dimaksud.</p>
  ${atRisk ? `<dl><dt>Estimasi nilai dana berisiko / Value at risk</dt><dd><b>${esc(atRisk)}</b></dd></dl>` : ""}

  <h2 class="sec">C. Dasar Hukum / Legal Basis</h2>
  <ul class="basis">
    <li>Undang-Undang No. 8 Tahun 2010 tentang Pencegahan dan Pemberantasan Tindak Pidana Pencucian Uang (Pasal 71 dan 72);</li>
    <li>${esc(basis ?? "POJK No. 27/POJK.03/2024 tentang Penyelenggaraan Produk Bank Umum")};</li>
    <li>Undang-Undang No. 11 Tahun 2008 jo. No. 19 Tahun 2016 tentang Informasi dan Transaksi Elektronik.</li>
  </ul>

  <h2 class="sec">D. Instruksi Pelaksanaan / Execution</h2>
  <p>Mengingat sifat perkara yang mendesak dan potensi pemindahan dana, kami mohon pemblokiran dapat dilaksanakan <b>paling lambat 1&times;24 jam</b> sejak surat ini diterima, dengan konfirmasi pelaksanaan disampaikan kepada unit kami. Atas perhatian dan kerja sama Saudara, kami ucapkan terima kasih.</p>

  <div class="sign">
    <div>Jakarta, ${esc(todayID())}</div>
    <div>${esc(ctx.officerRole)}</div>
    <div class="space"></div>
    <div class="name">${esc(ctx.officerName)}</div>
    <div>${esc(ctx.agencyName)}</div>
  </div>

  ${cc}

  <div class="foot">
    Dokumen ini dihasilkan oleh sistem ITTU sebagai <b>draf keluaran otomatis</b> untuk ditinjau dan ditandatangani oleh pejabat berwenang sebelum dikirimkan.
    Integritas bukti terkait: SHA-256 <span class="mono">${esc(ctx.evidenceHash)}</span> (rantai kustodi UU ITE Pasal 5). Dicetak: ${esc(todayID())}.
  </div>`;

  return SHELL("Permohonan Pemblokiran — " + ctx.caseRef, body);
}

/* ── STR / LTKM — Laporan Transaksi Keuangan Mencurigakan ──────────────── */

function ltkmReport(doc: ActionDocument, ctx: LetterContext): string {
  const subject = field(doc, "subject");
  const typology = field(doc, "typology") ?? field(doc, "crime");
  const amount = field(doc, "amount") ?? field(doc, "risk");
  const indicators = field(doc, "indicator");
  const format = field(doc, "format") ?? "goAML XML";

  const body = `
  <div class="kop">
    <div class="crest">◈</div>
    <div>
      <div class="agency">${esc(ctx.agencyName)}</div>
      <div class="sub">${esc(divisionLine(ctx))}</div>
      <div class="addr">Republik Indonesia · Sistem Forensik Keuangan ITTU</div>
    </div>
  </div>
  <hr class="rule"><hr class="rule thin">

  <h1 class="rep">LAPORAN TRANSAKSI KEUANGAN MENCURIGAKAN (LTKM)
    <small>Suspicious Transaction Report — untuk PPATK</small></h1>

  <table class="meta">
    <tr><td>Nomor</td><td>: ${esc(refNo(ctx, "LTKM"))}</td></tr>
    <tr><td>Perkara</td><td>: ${esc(ctx.caseRef)}</td></tr>
    <tr><td>Format</td><td>: ${esc(format)}</td></tr>
    <tr><td>Tanggal</td><td>: ${esc(todayID())}</td></tr>
  </table>

  <h2 class="sec">A. Identitas Terlapor / Subject</h2>
  <dl>
    <dt>Nama / Identitas</dt><dd>${esc(subject ?? "[DIISI OLEH ANALIS — subject identity to be completed]")}</dd>
  </dl>

  <h2 class="sec">B. Ringkasan Transaksi / Transaction Summary</h2>
  <dl>
    <dt>Tipologi</dt><dd>${esc(typology ?? "—")}</dd>
    <dt>Nilai terkait / Value</dt><dd>${esc(amount ?? "—")}</dd>
    <dt>Indikator (red flags)</dt><dd>${esc(indicators ?? "—")}</dd>
  </dl>

  <h2 class="sec">C. Uraian / Narrative</h2>
  <p>${esc(ctx.agencyName)} menyampaikan laporan atas dugaan transaksi keuangan mencurigakan sehubungan dengan perkara <b>${esc(ctx.caseRef)}</b>. Analisis forensik mengindikasikan pola ${esc(typology ?? "pencucian uang")} dengan indikator ${esc(indicators ?? "sebagaimana terlampir")}. Laporan ini disampaikan sebagai pemenuhan kewajiban pelaporan dan bahan analisis lebih lanjut.</p>

  <h2 class="sec">D. Dasar Hukum</h2>
  <ul class="basis">
    <li>Undang-Undang No. 8 Tahun 2010 tentang Pencegahan dan Pemberantasan TPPU (kewajiban pelaporan LTKM);</li>
    <li>Peraturan PPATK terkait tata cara penyampaian LTKM melalui goAML.</li>
  </ul>

  <div class="sign">
    <div>Jakarta, ${esc(todayID())}</div>
    <div>${esc(ctx.officerRole)}</div>
    <div class="space"></div>
    <div class="name">${esc(ctx.officerName)}</div>
    <div>${esc(ctx.agencyName)}</div>
  </div>

  <div class="foot">
    Draf LTKM keluaran sistem ITTU — wajib ditinjau, dilengkapi identitas terlapor, dan disahkan sebelum disampaikan melalui goAML.
    Integritas bukti: SHA-256 <span class="mono">${esc(ctx.evidenceHash)}</span>. Dicetak: ${esc(todayID())}.
  </div>`;

  return SHELL("LTKM / STR — " + ctx.caseRef, body);
}

export function buildDocumentHtml(doc: ActionDocument, ctx: LetterContext): string {
  return doc.kind === "ltkm" ? ltkmReport(doc, ctx) : freezeLetter(doc, ctx);
}
