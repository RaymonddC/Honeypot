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

from app.uncover.custody import audit_log, sha256_hex

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

_styles = getSampleStyleSheet()
STYLE_TITLE = ParagraphStyle(
    "IttuTitle", parent=_styles["Title"], fontSize=15, spaceAfter=2 * mm)
STYLE_SUB = ParagraphStyle(
    "IttuSub", parent=_styles["Normal"], fontSize=9, textColor=colors.HexColor("#555555"))
STYLE_H = ParagraphStyle(
    "IttuH", parent=_styles["Heading2"], fontSize=11, spaceBefore=4 * mm, spaceAfter=1.5 * mm)
STYLE_BODY = ParagraphStyle(
    "IttuBody", parent=_styles["Normal"], fontSize=9, leading=12)
STYLE_MONO = ParagraphStyle(
    "IttuMono", parent=_styles["Normal"], fontName="Courier", fontSize=7.5, leading=9.5)
STYLE_BULLET = ParagraphStyle(
    "IttuBullet", parent=STYLE_BODY, leftIndent=5 * mm, bulletIndent=1 * mm)

TABLE_STYLE = TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 7.5),
    ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9ca3af")),
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f3f4f6")]),
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
    story.append(Paragraph("Legal basis / Dasar hukum", STYLE_H))
    for ref, desc in LEGAL_BASIS:
        story.append(Paragraph(f"<b>{ref}</b> — {desc}", STYLE_BULLET, bulletText="•"))


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
    audit_log.record(
        action="action.document.generated",
        target_type="action_document",
        target_id=doc.id,
        detail={
            "case_id": ctx.case_id,
            "type": doc.type,
            "format": doc.format,
            "sha256": doc.sha256,
            "template_version": doc.template_version,
            "data_mode": doc.data_mode,
        },
    )
    return doc


# --------------------------------------------------------------------------- #
# (a) Account / Wallet Freeze Request
# --------------------------------------------------------------------------- #


def generate_freeze_request(ctx: DocumentContext) -> GeneratedDocument:
    title = "Permohonan Pemblokiran — Account & Wallet Freeze Request"
    story: list = []
    _header(story, title, ctx, "Freeze Request (IASC-compatible)")

    story.append(_body(
        f"Pursuant to the legal basis below, <b>{ctx.requesting_agency}</b> requests the "
        f"immediate <b>blocking/freezing</b> of the assets listed in this document, identified "
        f"during investigation of case <b>{ctx.case_id}</b> "
        f"(typology: <b>{ctx.crime_label}</b>). Total estimated funds at risk: "
        f"<b>{ctx.total_at_risk_usdt:,.2f} USDT</b> "
        f"(≈ Rp {ctx.total_at_risk_idr:,.0f} at Rp {ctx.idr_per_usdt:,.0f}/USDT)."
    ))

    if ctx.wallets:
        story.append(Paragraph("Target crypto wallets (freeze / flag at exchange)", STYLE_H))
        rows = [["Address", "Chain", "Risk", "Conf.", "Inflow (USDT)", "Fired patterns"]]
        for w in ctx.wallets:
            rows.append([
                _mono(w.address), w.chain.upper(), w.risk.upper(),
                f"{w.confidence:.2f}" if w.confidence is not None else "—",
                f"{w.inflow_usdt:,.2f}", ", ".join(w.patterns) or "—",
            ])
        story.append(Table(rows, style=TABLE_STYLE,
                           colWidths=[62 * mm, 13 * mm, 14 * mm, 12 * mm, 25 * mm, None]))

    if ctx.accounts:
        story.append(Paragraph("Target bank accounts (freeze at holding bank)", STYLE_H))
        rows = [["Account number", "Bank", "Holder", "Role", "Outflow (IDR)"]]
        for a in ctx.accounts:
            rows.append([
                _mono(a.account_number), a.bank_name, a.holder_name or "—",
                a.role or "—", f"Rp {a.outflow_idr:,.0f}",
            ])
        story.append(Table(rows, style=TABLE_STYLE,
                           colWidths=[38 * mm, 30 * mm, 40 * mm, 26 * mm, None]))

    tx_hashes = [h for w in ctx.wallets for h in w.tx_hashes]
    if tx_hashes:
        story.append(Paragraph("Supporting transaction hashes (evidence)", STYLE_H))
        for h in tx_hashes[:20]:
            story.append(_mono(h))
        if len(tx_hashes) > 20:
            story.append(_body(f"… and {len(tx_hashes) - 20} further transactions "
                               "(see Case Evidence Pack)."))

    story.append(Paragraph("Risk assessment — Glass Box reasoning", STYLE_H))
    for w in ctx.wallets:
        story.append(_body(f"<b>{w.address}</b> — composite risk <b>{w.risk.upper()}</b>:"))
        for r in w.reasoning:
            story.append(Paragraph(r, STYLE_BULLET, bulletText="•"))
    if not ctx.wallets:
        story.append(_body("See attached analyst narrative."))

    _legal_basis(story)

    story.append(Paragraph("Requested action", STYLE_H))
    story.append(_body(
        "1. Immediate temporary blocking (penundaan/pemblokiran sementara) of the assets above. "
        "2. Preservation of all associated KYC records and transaction logs. "
        "3. Confirmation of execution to the requesting agency, referencing this case id. "
        "The freeze is executed by the receiving bank/exchange under its own authority "
        "(IASC mechanism); this request compresses coordination, not legal authority."
    ))
    story.append(Spacer(1, 6 * mm))
    story.append(_body(f"Issued electronically by {ctx.requesting_agency} — "
                       f"{ctx.generated_at.isoformat()}. Document custody: SHA-256 hashed "
                       "and audit-chained (UU ITE Pasal 5)."))

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
    _header(story, title, ctx, "LTKM/STR draft for PPATK goAML")

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

    story.append(Spacer(1, 4 * mm))
    story.append(_body("A machine-readable goAML-shaped draft accompanies this PDF "
                       "(bundle field <b>goaml_draft</b>); live goAML XML submission is a "
                       "LIVE-mode integration."))

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
