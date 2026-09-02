"""UNCOVER document generators — plain-template assemble → ReportLab render.

Three court/regulator-facing artifacts (docs/UNCOVER-Design.md):

(a) **Account/Wallet Freeze Request** — target wallets + bank accounts, tx
    hashes, risk scores with Glass Box reasoning, timestamps, legal basis
    (POJK 27/2024, UU ITE Pasal 5, UU 8/2010 TPPU).
(b) **LTKM / STR draft** — goAML-shaped (reporting entity, transaction
    details, typology indicators, narrative). Subject identity is a
    human-filled placeholder — the analyst completes it before submission.
(c) **Case Evidence Pack** — case summary, flagged patterns, transaction
    timeline, and the chain-of-custody manifest (document hashes, versions).

Custody: every PDF is SHA-256 hashed (app/uncover/custody.py) and an
audit-log entry is emitted. PDFs are built ``invariant=1`` +
``pageCompression=0`` → byte-identical output for identical context
(deterministic custody hashes, greppable text in tests).
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from io import BytesIO

from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.uncover.custody import sha256_hex

TEMPLATE_VERSION = "uncover-templates-0.1.0"
GOAML_SCHEMA_VERSION = "goAML-4.0-draft"
SUBJECT_PLACEHOLDER = "[TO BE COMPLETED BY ANALYST]"

# Pattern name → typology indicator code (goAML/PPATK-style draft codes).
TYPOLOGY_CODES = {
    "peeling_chain": "IND-LAY-01 layering via sequential peeling chain",
    "rapid_relay": "IND-LAY-02 rapid pass-through relay (<5 min)",
    "circular": "IND-LAY-03 circular / wash transactions",
    "structuring": "IND-PLA-01 structuring (smurfing) of similar amounts",
    "fan_out": "IND-LAY-04 dispersal fan-out to many wallets",
    "mule_aggregation": "IND-PLA-02 mule account aggregation (many-in/few-out)",
    "onramp_correlation": "IND-INT-01 fiat→crypto on-ramp conversion",
}

LEGAL_BASIS = [
    ("UU No. 8 Tahun 2010", "Pencegahan dan Pemberantasan Tindak Pidana Pencucian Uang "
     "(anti-money-laundering act — suspension/blocking of suspicious assets)."),
    ("POJK 27/2024 (jo. POJK 23/2025)", "Penerapan program APU, PPT, dan PPPSPM di sektor "
     "jasa keuangan — legal basis for the freeze request to financial-service providers."),
    ("PP 43/2015 jo. PP 61/2021", "Pihak pelapor dan tata cara penyampaian laporan transaksi "
     "keuangan mencurigakan (LTKM/STR) kepada PPATK."),
    ("UU ITE Pasal 5", "Informasi dan dokumen elektronik sebagai alat bukti sah — this "
     "document is SHA-256 hashed and custody-chained for admissibility."),
]

CRIME_TYPE_LABELS = {
    "investment": "Investment scam (penipuan investasi)",
    "judol_deposit": "Online gambling deposits (judi online)",
    "crypto_phishing": "Crypto phishing / wallet drain",
    "romance": "Romance scam",
}

# Role → Indonesian officer title for the signature block.
OFFICER_TITLES = {
    "police-investigator": "Penyidik / Investigator",
    "regulator-analyst": "Analis Transaksi Keuangan",
    "bank-compliance": "Petugas Kepatuhan (Compliance)",
    "exchange-compliance": "Petugas Kepatuhan (Compliance)",
    "agency-admin": "Administrator Instansi",
    "platform-admin": "Administrator Platform",
}

_ID_MONTHS = [
    "", "Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli",
    "Agustus", "September", "Oktober", "November", "Desember",
]


# --------------------------------------------------------------------------- #
# Context models (assembled by the Action Orchestrator, app/uncover/service.py)
# --------------------------------------------------------------------------- #


class WalletTarget(BaseModel):
    address: str
    chain: str = "tron"
    risk: str = "unknown"                 # low|medium|high|unknown
    confidence: float | None = None
    reasoning: list[str] = Field(default_factory=list)   # Glass Box
    patterns: list[str] = Field(default_factory=list)    # fired detector names
    inflow_usdt: float = 0.0
    tx_hashes: list[str] = Field(default_factory=list)


class AccountTarget(BaseModel):
    account_number: str
    bank_name: str
    holder_name: str | None = None
    role: str | None = None               # mule|collector_mule|shell_merchant|…
    cluster: str | None = None
    inflow_idr: float = 0.0
    outflow_idr: float = 0.0
    tx_count: int = 0


class TimelineEvent(BaseModel):
    ts: datetime
    description: str
    amount: float
    currency: str                          # IDR | USDT
    ref: str                               # tx hash / transfer id


class DocumentContext(BaseModel):
    """Everything the generators need — no re-querying inside a generator."""

    case_id: str
    crime_type: str = "investment"
    data_mode: str = "poc"
    generated_at: datetime
    requesting_agency: str = "ITTU — Integrated Trace & Takedown Unit (POC)"
    agency_type: str = ""                 # police | regulator | bank | exchange
    officer_name: str = ""                # signing officer (from the authed user)
    officer_role: str = ""                # officer title for the signature block
    case_reference: str | None = None
    wallets: list[WalletTarget] = Field(default_factory=list)
    accounts: list[AccountTarget] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    narrative: str = ""
    total_at_risk_usdt: float = 0.0
    total_at_risk_idr: float = 0.0
    idr_per_usdt: float = 16250.0

    @property
    def crime_label(self) -> str:
        return CRIME_TYPE_LABELS.get(self.crime_type, self.crime_type)

    def fired_patterns(self) -> list[str]:
        seen: list[str] = []
        for w in self.wallets:
            for p in w.patterns:
                if p not in seen:
                    seen.append(p)
        if any(a.role in ("mule", "collector_mule") for a in self.accounts):
            seen.append("mule_aggregation")
        if self.accounts and self.wallets:
            seen.append("onramp_correlation")
        return seen

    def indicators(self) -> list[str]:
        return [TYPOLOGY_CODES.get(p, f"IND-OTH {p}") for p in self.fired_patterns()]


@dataclass
class GeneratedDocument:
    """One rendered, hashed artifact (held in-memory, POC object store)."""

    id: str
    type: str                # account_blocking | str_report | summary
    format: str              # iasc | ppatk_str | generic
    title: str
    filename: str
    pdf: bytes
    sha256: str
    generated_at: datetime
    template_version: str = TEMPLATE_VERSION
    status: str = "draft"    # draft → issued → acknowledged
    data_mode: str = "poc"
    meta: dict = field(default_factory=dict)   # e.g. the goAML-shaped draft

    @property
    def size_bytes(self) -> int:
        return len(self.pdf)


# --------------------------------------------------------------------------- #
# ReportLab plumbing
# --------------------------------------------------------------------------- #

# Palette mirrors the web letter (lib/actions/letter.ts).
C_INK = colors.HexColor("#111827")
C_MUTED = colors.HexColor("#6b7280")
C_LINE = colors.HexColor("#d1d5db")
C_ACCENT = colors.HexColor("#0d9488")
C_HEADBG = colors.HexColor("#f3f4f6")

_styles = getSampleStyleSheet()
# Body is serif (Times) like the web letter; labels/tables/headers are sans.
STYLE_TITLE = ParagraphStyle(
    "IttuTitle", parent=_styles["Title"], fontName="Times-Bold", fontSize=15,
    textColor=C_INK, spaceAfter=1 * mm)
STYLE_SUB = ParagraphStyle(
    "IttuSub", parent=_styles["Normal"], fontSize=9, textColor=C_MUTED)
STYLE_H = ParagraphStyle(
    "IttuH", parent=_styles["Normal"], fontName="Helvetica-Bold", fontSize=9.5,
    textColor=C_MUTED, spaceBefore=4 * mm, spaceAfter=1.5 * mm)
STYLE_BODY = ParagraphStyle(
    "IttuBody", parent=_styles["Normal"], fontName="Times-Roman", fontSize=10,
    leading=13.5, textColor=C_INK)
STYLE_MONO = ParagraphStyle(
    "IttuMono", parent=_styles["Normal"], fontName="Courier", fontSize=7.5,
    leading=9.5, textColor=C_INK)
STYLE_BULLET = ParagraphStyle(
    "IttuBullet", parent=STYLE_BODY, leftIndent=5 * mm, bulletIndent=1 * mm,
    spaceAfter=0.6 * mm)

TABLE_STYLE = TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), C_HEADBG),
    ("TEXTCOLOR", (0, 0), (-1, 0), C_INK),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
    ("TEXTCOLOR", (0, 1), (-1, -1), C_INK),
    ("FONTSIZE", (0, 0), (-1, -1), 7.8),
    ("GRID", (0, 0), (-1, -1), 0.5, C_LINE),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("TOPPADDING", (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
])


def _mono(text: str) -> Paragraph:
    return Paragraph(text, STYLE_MONO)


def _body(text: str) -> Paragraph:
    return Paragraph(text, STYLE_BODY)


def _header(story: list, title: str, ctx: DocumentContext, doc_kind: str) -> None:
    story.append(Paragraph(title, STYLE_TITLE))
    story.append(Paragraph(
        f"{ctx.requesting_agency} · Case {ctx.case_id}"
        f" · {doc_kind} · generated {ctx.generated_at.isoformat()}"
        f" · mode={ctx.data_mode.upper()}",
        STYLE_SUB,
    ))
    if ctx.data_mode == "poc":
        story.append(Paragraph(
            "POC DEMONSTRATION OUTPUT — generated from proof-of-concept data; "
            "not a legal instrument.", STYLE_SUB,
        ))
    story.append(HRFlowable(width="100%", thickness=0.8,
                            color=colors.HexColor("#1f2937"), spaceAfter=3 * mm))


def _legal_basis(story: list) -> None:
    story.append(Paragraph("Dasar hukum / Legal basis", STYLE_H))
    for ref, desc in LEGAL_BASIS:
        story.append(Paragraph(f"<b>{ref}</b> — {desc}", STYLE_BULLET, bulletText="•"))


# --- Formal-letter styling (kop surat, meta, signature) ------------------- #

STYLE_KOP_AGENCY = ParagraphStyle(
    "KopAgency", parent=_styles["Normal"], fontName="Helvetica-Bold",
    fontSize=15, leading=17, textColor=C_INK)
STYLE_KOP_SUB = ParagraphStyle(
    "KopSub", parent=_styles["Normal"], fontSize=9.5, leading=11.5, textColor=C_INK)
STYLE_KOP_ADDR = ParagraphStyle(
    "KopAddr", parent=_styles["Normal"], fontSize=7.5, leading=9.5, textColor=C_MUTED)
STYLE_CREST = ParagraphStyle(
    "Crest", parent=_styles["Normal"], fontName="Helvetica-Bold", fontSize=20,
    textColor=C_ACCENT, alignment=1)
STYLE_META = ParagraphStyle(
    "Meta", parent=_styles["Normal"], fontSize=9, leading=12.5, textColor=C_INK)
STYLE_JUST = ParagraphStyle("IttuJust", parent=STYLE_BODY, alignment=4)  # justify
STYLE_SIGN = ParagraphStyle(
    "IttuSign", parent=_styles["Normal"], fontName="Times-Roman", fontSize=9.5,
    leading=13, alignment=1, textColor=C_INK)
STYLE_FOOT = ParagraphStyle(
    "IttuFoot", parent=_styles["Normal"], fontSize=7, leading=9.5, textColor=C_MUTED)


def _just(text: str) -> Paragraph:
    return Paragraph(text, STYLE_JUST)


def _division_line(ctx: DocumentContext) -> str:
    t = (ctx.agency_type or "").lower()
    name = (ctx.requesting_agency or "").lower()
    if "police" in t or "bareskrim" in name or "polri" in name:
        return "Direktorat Tindak Pidana Siber (Dittipidsiber)"
    if "regulator" in t or "ppatk" in name or "ojk" in name:
        return "Unit Analisis &amp; Kepatuhan Transaksi Keuangan"
    if "bank" in t:
        return "Divisi Anti Pencucian Uang (APU-PPT)"
    if "exchange" in t:
        return "Divisi Kepatuhan (Compliance)"
    return "Unit Penanganan Tindak Pidana Keuangan"


def _date_id(ctx: DocumentContext) -> str:
    d = ctx.generated_at
    return f"{d.day} {_ID_MONTHS[d.month]} {d.year}"


def _ref_no(ctx: DocumentContext, tag: str) -> str:
    import re
    digits = re.sub(r"\D", "", ctx.case_reference or ctx.case_id) or "0001"
    return f"{digits[-4:]}/{tag}/{ctx.generated_at.year}"


def _letterhead(story: list, ctx: DocumentContext) -> None:
    # Crest box (teal ring) + agency block, side by side — like the web letter.
    crest = Table([[Paragraph("◈", STYLE_CREST)]], colWidths=[12 * mm], rowHeights=[12 * mm])
    crest.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.3, C_ACCENT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
    ]))
    text = [
        Paragraph((ctx.requesting_agency or "").upper(), STYLE_KOP_AGENCY),
        Paragraph(_division_line(ctx), STYLE_KOP_SUB),
        Paragraph("Republik Indonesia · Sistem Forensik Keuangan ITTU", STYLE_KOP_ADDR),
    ]
    head = Table([[crest, text]], colWidths=[16 * mm, None])
    head.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, 0), 0),
        ("LEFTPADDING", (1, 0), (1, 0), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(head)
    story.append(HRFlowable(width="100%", thickness=2.5, color=C_INK,
                            spaceBefore=2 * mm, spaceAfter=0.7 * mm))
    story.append(HRFlowable(width="100%", thickness=0.6, color=C_LINE,
                            spaceAfter=4 * mm))


def _signature(story: list, ctx: DocumentContext) -> None:
    officer = ctx.officer_name or "[Nama Pejabat Penandatangan]"
    # officer_role arrives as a role slug (e.g. "police-investigator") → title.
    role = OFFICER_TITLES.get(ctx.officer_role, ctx.officer_role) or "Pejabat Berwenang"
    inner = Table(
        [
            [Paragraph(f"Jakarta, {_date_id(ctx)}", STYLE_SIGN)],
            [Paragraph(role, STYLE_SIGN)],
            [Spacer(1, 15 * mm)],
            [Paragraph(f"<u><b>{officer}</b></u>", STYLE_SIGN)],
            [Paragraph(ctx.requesting_agency, STYLE_SIGN)],
        ],
        colWidths=[72 * mm],
    )
    inner.setStyle(TableStyle([
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    outer = Table([["", inner]], colWidths=[None, 72 * mm])
    outer.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(Spacer(1, 5 * mm))
    story.append(outer)


def _doc_footer(story: list, ctx: DocumentContext, note: str) -> None:
    story.append(Spacer(1, 6 * mm))
    story.append(HRFlowable(width="100%", thickness=0.5, color=C_LINE, spaceAfter=2 * mm))
    poc = ("Dokumen ini dihasilkan dari data PROOF-OF-CONCEPT dan bukan instrumen hukum. "
           if ctx.data_mode == "poc" else "")
    story.append(Paragraph(
        f"{note} {poc}Integritas bukti: dokumen di-SHA-256 dan dirantai-kustodi "
        f"(UU ITE Pasal 5). Dicetak: {_date_id(ctx)}.", STYLE_FOOT))


def _render(story: list, title: str) -> bytes:
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        title=title,
        author="ITTU UNCOVER",
        leftMargin=16 * mm, rightMargin=16 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
        invariant=1,          # reproducible bytes → deterministic custody hash
        pageCompression=0,    # uncompressed streams → verifiable/greppable text
    )
    doc.build(story)
    return buf.getvalue()


def _finalize(
    ctx: DocumentContext, *, doc_type: str, fmt: str, title: str, slug: str,
    pdf: bytes, meta: dict | None = None,
) -> GeneratedDocument:
    doc = GeneratedDocument(
        id=f"doc_{uuid.uuid4().hex[:12]}",
        type=doc_type,
        format=fmt,
        title=title,
        filename=f"{slug}-{ctx.case_id}.pdf".replace(" ", "_"),
        pdf=pdf,
        sha256=sha256_hex(pdf),
        generated_at=ctx.generated_at,
        data_mode=ctx.data_mode,
        meta=meta or {},
    )
    # No per-document audit entry is written here any more. It used to go to the
    # in-memory custody chain, which did not survive a restart; the durable
    # record is the ONE core-trail `action.bundle.generated` entry the router
    # writes, whose `documents` array carries each document's id, type, format,
    # sha256 and template_version. Same facts, one entry instead of N, and it
    # is still there tomorrow.
    return doc


# --------------------------------------------------------------------------- #
# (a) Account / Wallet Freeze Request
# --------------------------------------------------------------------------- #


def generate_freeze_request(ctx: DocumentContext) -> GeneratedDocument:
    title = "Permohonan Pemblokiran — Account & Wallet Freeze Request"
    case = ctx.case_reference or ctx.case_id
    story: list = []

    _letterhead(story, ctx)

    # Nomor / Sifat / Lampiran / Perihal
    meta = Table(
        [
            [Paragraph("Nomor", STYLE_META), Paragraph(f": {_ref_no(ctx, 'PMB')}", STYLE_META)],
            [Paragraph("Sifat", STYLE_META), Paragraph(": <b>SEGERA / URGENT</b>", STYLE_META)],
            [Paragraph("Lampiran", STYLE_META), Paragraph(": 1 (satu) berkas ringkasan analisis", STYLE_META)],
            [Paragraph("Perihal", STYLE_META),
             Paragraph(": <b>Permohonan Pemblokiran Rekening &amp; Dompet Terkait Dugaan Tindak Pidana</b>", STYLE_META)],
        ],
        colWidths=[20 * mm, None],
    )
    meta.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
    ]))
    story.append(meta)
    story.append(Spacer(1, 4 * mm))

    story.append(_body(
        "Kepada Yth.<br/><b>Kepala Divisi Kepatuhan / APU-PPT</b><br/>"
        "Institusi Keuangan &amp; Penyedia Aset Kripto Terkait<br/>di Tempat"))
    story.append(Spacer(1, 3 * mm))

    story.append(_body("Dengan hormat,"))
    story.append(_just(
        f"Sehubungan dengan penanganan perkara <b>{case}</b> terkait dugaan tindak pidana "
        f"penipuan (<i>fraud</i>) dan pencucian uang dengan tipologi <b>{ctx.crime_label}</b>, "
        "serta berdasarkan hasil analisis forensik keuangan yang kami lakukan, dengan ini kami "
        "memohon bantuan Saudara untuk <b>segera melakukan PEMBLOKIRAN</b> terhadap rekening "
        "dan/atau dompet sebagai berikut:"))
    story.append(Spacer(1, 1.5 * mm))

    if ctx.accounts:
        rows = [["No.", "Nomor Rekening", "Bank", "Atas Nama", "Peran", "Arus Keluar (IDR)"]]
        for i, a in enumerate(ctx.accounts, start=1):
            rows.append([str(i), _mono(a.account_number), a.bank_name,
                         a.holder_name or "—", a.role or "mule", f"Rp {a.outflow_idr:,.0f}"])
        story.append(Table(rows, style=TABLE_STYLE,
                           colWidths=[8 * mm, 34 * mm, 24 * mm, 40 * mm, 24 * mm, None]))
        story.append(Spacer(1, 1.5 * mm))

    if ctx.wallets:
        rows = [["No.", "Alamat Dompet (USDT-TRC20)", "Rantai", "Risiko", "Inflow (USDT)"]]
        for i, w in enumerate(ctx.wallets, start=1):
            rows.append([str(i), _mono(w.address), w.chain.upper(),
                         w.risk.upper(), f"{w.inflow_usdt:,.2f}"])
        story.append(Table(rows, style=TABLE_STYLE,
                           colWidths=[8 * mm, 74 * mm, 16 * mm, 18 * mm, None]))
        story.append(Spacer(1, 1.5 * mm))

    story.append(_just(
        f"Estimasi nilai dana terkait yang berisiko dipindahkan: "
        f"<b>{ctx.total_at_risk_usdt:,.2f} USDT</b> "
        f"(≈ Rp {ctx.total_at_risk_idr:,.0f} pada kurs Rp {ctx.idr_per_usdt:,.0f}/USDT). "
        "Justifikasi risiko per objek disertai penalaran <i>Glass Box</i> dan skor risiko "
        "pada berkas analisis terlampir."))

    patterns = ", ".join(dict.fromkeys(p for w in ctx.wallets for p in w.patterns))
    if patterns:
        story.append(_just(
            f"Pola tipologi pencucian uang yang terdeteksi (fired detectors): <b>{patterns}</b>."))

    tx_hashes = [h for w in ctx.wallets for h in w.tx_hashes]
    if tx_hashes:
        story.append(Paragraph(
            "Lampiran — jejak transaksi pendukung / Supporting tx hashes", STYLE_H))
        for h in tx_hashes[:20]:
            story.append(_mono(h))
        if len(tx_hashes) > 20:
            story.append(_body(
                f"… dan {len(tx_hashes) - 20} transaksi lainnya (lihat Berkas Bukti Perkara)."))

    _legal_basis(story)

    story.append(Paragraph("Tindakan yang dimohonkan / Requested action", STYLE_H))
    story.append(_just(
        "1. Pemblokiran / penundaan sementara terhadap rekening dan dompet tersebut di atas "
        "<b>paling lambat 1×24 jam</b> sejak surat ini diterima. "
        "2. Pengamanan seluruh data KYC dan log transaksi terkait. "
        "3. Konfirmasi pelaksanaan disampaikan kepada unit kami dengan menyebutkan nomor perkara. "
        "Pemblokiran dilaksanakan oleh bank / penyedia aset kripto penerima berdasarkan "
        "kewenangannya (mekanisme IASC); surat ini mengkoordinasikan, bukan menggantikan, "
        "kewenangan hukum tersebut."))

    story.append(Spacer(1, 2 * mm))
    story.append(_just(
        "Demikian permohonan ini kami sampaikan. Atas perhatian dan kerja sama Saudara, "
        "kami ucapkan terima kasih."))

    _signature(story, ctx)
    _doc_footer(story, ctx,
                "Draf keluaran otomatis untuk ditinjau dan ditandatangani pejabat berwenang "
                "sebelum dikirimkan.")

    pdf = _render(story, title)
    return _finalize(ctx, doc_type="account_blocking", fmt="iasc", title=title,
                     slug="freeze-request", pdf=pdf)


# --------------------------------------------------------------------------- #
# (b) LTKM / STR draft — goAML-shaped
# --------------------------------------------------------------------------- #


def build_goaml_draft(ctx: DocumentContext) -> dict:
    """goAML-shaped structured STR draft (JSON now; XML mapping is Phase-3 LIVE)."""
    transactions = []
    for i, ev in enumerate(ctx.timeline, start=1):
        transactions.append({
            "transaction_number": f"{ctx.case_id}-T{i:03d}",
            "date_transaction": ev.ts.isoformat(),
            "transaction_description": ev.description,
            "amount_local": ev.amount if ev.currency == "IDR"
            else round(ev.amount * ctx.idr_per_usdt, 2),
            "currency": ev.currency,
            "amount_original": ev.amount,
            "ref": ev.ref,
        })
    return {
        "schema": GOAML_SCHEMA_VERSION,
        "report": {
            "rentity_id": SUBJECT_PLACEHOLDER,
            "rentity_branch": SUBJECT_PLACEHOLDER,
            "submission_code": "E",           # electronic
            "report_code": "STR",             # LTKM — suspicious transaction report
            "submission_date": ctx.generated_at.isoformat(),
            "currency_code_local": "IDR",
            "reporting_person": SUBJECT_PLACEHOLDER,
            "reason": ctx.narrative or f"Suspected {ctx.crime_label} — case {ctx.case_id}.",
            "action": "Freeze request drafted; multi-agency alert prepared (see case bundle).",
        },
        "subjects": [{
            "type": "person",
            "full_name": SUBJECT_PLACEHOLDER,
            "identification": SUBJECT_PLACEHOLDER,
            "note": "Subject identity must be completed by the analyst before submission.",
        }],
        "accounts": [{
            "account_number": a.account_number,
            "institution_name": a.bank_name,
            "account_holder": a.holder_name or SUBJECT_PLACEHOLDER,
            "suspected_role": a.role or "unknown",
        } for a in ctx.accounts],
        "crypto_wallets": [{
            # goAML has no on-chain fields — ITTU's crypto enrichment is additive.
            "address": w.address,
            "chain": w.chain,
            "composite_risk": w.risk,
            "inflow_usdt": w.inflow_usdt,
            "supporting_tx_hashes": w.tx_hashes[:20],
        } for w in ctx.wallets],
        "transactions": transactions,
        "indicators": ctx.indicators(),
        "crime_type": ctx.crime_type,
        "data_mode": ctx.data_mode,
        "template_version": TEMPLATE_VERSION,
    }


def generate_str_draft(ctx: DocumentContext) -> GeneratedDocument:
    title = "LTKM / Suspicious Transaction Report — Draft (goAML)"
    goaml = build_goaml_draft(ctx)
    story: list = []
    _letterhead(story, ctx)
    story.append(Paragraph("LAPORAN TRANSAKSI KEUANGAN MENCURIGAKAN (LTKM)", STYLE_TITLE))
    story.append(Paragraph(
        "Suspicious Transaction Report — Draft untuk PPATK (goAML)", STYLE_SUB))
    story.append(Spacer(1, 3 * mm))

    story.append(Paragraph("Report header", STYLE_H))
    rows = [
        ["Report code", "STR (LTKM — Laporan Transaksi Keuangan Mencurigakan)"],
        ["Reporting entity", SUBJECT_PLACEHOLDER],
        ["Submission", f"Electronic (goAML) · draft {GOAML_SCHEMA_VERSION}"],
        ["Submission date", ctx.generated_at.isoformat()],
        ["Case reference", ctx.case_id],
        ["Crime typology", ctx.crime_label],
        ["Local currency", "IDR"],
    ]
    story.append(Table(rows, style=TABLE_STYLE, colWidths=[38 * mm, None]))

    story.append(Paragraph("Subject (to be completed)", STYLE_H))
    story.append(_body(
        f"Full name / NIK / address: <b>{SUBJECT_PLACEHOLDER}</b> — subject identity is "
        "deliberately left for the human analyst; every other field is pre-filled from case data."
    ))

    if ctx.accounts:
        story.append(Paragraph("Related accounts", STYLE_H))
        rows = [["Account number", "Bank", "Holder", "Suspected role"]]
        for a in ctx.accounts:
            rows.append([_mono(a.account_number), a.bank_name,
                         a.holder_name or SUBJECT_PLACEHOLDER, a.role or "unknown"])
        story.append(Table(rows, style=TABLE_STYLE, colWidths=[40 * mm, 34 * mm, 50 * mm, None]))

    if ctx.wallets:
        story.append(Paragraph("Related crypto wallets (ITTU on-chain enrichment)", STYLE_H))
        story.append(_body("goAML has no native on-chain capability — this section is ITTU's "
                           "crypto enrichment attached to the STR."))
        rows = [["Address", "Chain", "Risk", "Inflow (USDT)"]]
        for w in ctx.wallets:
            rows.append([_mono(w.address), w.chain.upper(), w.risk.upper(),
                         f"{w.inflow_usdt:,.2f}"])
        story.append(Table(rows, style=TABLE_STYLE, colWidths=[80 * mm, 16 * mm, 16 * mm, None]))

    if ctx.timeline:
        story.append(Paragraph("Transaction details", STYLE_H))
        rows = [["#", "Timestamp (UTC)", "Description", "Amount", "Ref"]]
        for i, ev in enumerate(ctx.timeline[:25], start=1):
            rows.append([str(i), ev.ts.strftime("%Y-%m-%d %H:%M"), _body(ev.description),
                         f"{ev.amount:,.2f} {ev.currency}", _mono(ev.ref[:24] + "…")])
        story.append(Table(rows, style=TABLE_STYLE,
                           colWidths=[7 * mm, 27 * mm, 62 * mm, 30 * mm, None]))
        if len(ctx.timeline) > 25:
            story.append(_body(f"… and {len(ctx.timeline) - 25} further transactions "
                               "(full set in the goAML structured draft)."))

    story.append(Paragraph("Risk indicators / typology", STYLE_H))
    for ind in ctx.indicators() or ["—"]:
        story.append(Paragraph(ind, STYLE_BULLET, bulletText="•"))

    story.append(Paragraph("Grounds for suspicion — narrative", STYLE_H))
    story.append(_body(goaml["report"]["reason"]))

    story.append(Spacer(1, 3 * mm))
    story.append(_body(
        "Draf terstruktur goAML (machine-readable) menyertai dokumen ini "
        "(<b>goaml_draft</b>); penyampaian goAML XML langsung merupakan integrasi mode LIVE."))

    _signature(story, ctx)
    _doc_footer(story, ctx,
                "Draf LTKM keluaran sistem — wajib dilengkapi identitas terlapor dan disahkan "
                "sebelum disampaikan melalui goAML.")

    pdf = _render(story, title)
    return _finalize(ctx, doc_type="str_report", fmt="ppatk_str", title=title,
                     slug="ltkm-str-draft", pdf=pdf, meta={"goaml_draft": goaml})


# --------------------------------------------------------------------------- #
# (c) Case Evidence Pack
# --------------------------------------------------------------------------- #


def generate_evidence_pack(
    ctx: DocumentContext, manifest_docs: list[GeneratedDocument] | None = None
) -> GeneratedDocument:
    title = "Case Evidence Pack — Summary & Chain-of-Custody Manifest"
    story: list = []
    _header(story, title, ctx, "Court-ready evidence bundle")

    story.append(Paragraph("Case summary", STYLE_H))
    story.append(_body(
        f"Case <b>{ctx.case_id}</b> · typology <b>{ctx.crime_label}</b> · "
        f"{len(ctx.wallets)} flagged wallet(s), {len(ctx.accounts)} flagged account(s), "
        f"{len(ctx.timeline)} evidentiary transaction(s). Estimated funds at risk "
        f"{ctx.total_at_risk_usdt:,.2f} USDT (≈ Rp {ctx.total_at_risk_idr:,.0f})."
    ))
    if ctx.narrative:
        story.append(_body(ctx.narrative))

    story.append(Paragraph("Flagged patterns (detectors fired)", STYLE_H))
    for p in ctx.fired_patterns() or ["—"]:
        story.append(Paragraph(TYPOLOGY_CODES.get(p, p), STYLE_BULLET, bulletText="•"))

    story.append(Paragraph("Risk scores with reasoning (Glass Box)", STYLE_H))
    for w in ctx.wallets:
        conf = f"{w.confidence:.2f}" if w.confidence is not None else "—"
        story.append(_body(
            f"<b>{w.address}</b> ({w.chain.upper()}) — risk <b>{w.risk.upper()}</b>, "
            f"confidence {conf}:"))
        for r in w.reasoning:
            story.append(Paragraph(r, STYLE_BULLET, bulletText="•"))

    if ctx.timeline:
        story.append(Paragraph("Transaction timeline", STYLE_H))
        rows = [["Timestamp (UTC)", "Event", "Amount", "Ref"]]
        for ev in ctx.timeline[:40]:
            rows.append([ev.ts.strftime("%Y-%m-%d %H:%M"), _body(ev.description),
                         f"{ev.amount:,.2f} {ev.currency}", _mono(ev.ref[:24] + "…")])
        story.append(Table(rows, style=TABLE_STYLE,
                           colWidths=[27 * mm, 76 * mm, 30 * mm, None]))

    story.append(Paragraph("Chain-of-custody manifest", STYLE_H))
    story.append(_body(
        f"Pipeline: template <b>{TEMPLATE_VERSION}</b> · risk model "
        "<b>takedown-0.1.0/iforest-c0.05+5typologies</b> · correlation "
        "<b>amount_time_window</b>. Every document below is SHA-256 hashed at generation and "
        "recorded in the append-only audit chain — any alteration is detectable "
        "(UU ITE Pasal 5)."
    ))
    rows = [["Document", "Type", "Generated (UTC)", "SHA-256"]]
    for d in manifest_docs or []:
        # two 32-char halves — keeps each half contiguous/verifiable in the stream
        rows.append([_body(d.title), d.type, d.generated_at.isoformat(),
                     _mono(d.sha256[:32] + "<br/>" + d.sha256[32:])])
    rows.append([_body(title + " (this document)"), "summary",
                 ctx.generated_at.isoformat(), _mono("computed on finalization")])
    story.append(Table(rows, style=TABLE_STYLE, colWidths=[52 * mm, 24 * mm, 30 * mm, None]))

    pdf = _render(story, title)
    return _finalize(ctx, doc_type="summary", fmt="generic", title=title,
                     slug="evidence-pack", pdf=pdf)
