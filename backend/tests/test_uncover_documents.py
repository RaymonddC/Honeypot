"""UNCOVER document generators — real PDF bytes, key fields, custody hashing."""

from datetime import datetime, timezone

import pytest

from app.uncover.custody import sha256_hex
from app.uncover.documents import (
    SUBJECT_PLACEHOLDER,
    AccountTarget,
    DocumentContext,
    TimelineEvent,
    WalletTarget,
    build_goaml_draft,
    generate_evidence_pack,
    generate_freeze_request,
    generate_str_draft,
)

WALLET = "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6"
TX_HASH = "ab12cd34" * 8
FIXED_TS = datetime(2026, 7, 5, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def ctx() -> DocumentContext:
    return DocumentContext(
        case_id="CASE-2026-0142",
        crime_type="investment",
        generated_at=FIXED_TS,
        wallets=[
            WalletTarget(
                address=WALLET, chain="tron", risk="high", confidence=0.9,
                reasoning=["Pattern [peeling_chain] fired: 3-hop chain forwarding 90%."],
                patterns=["peeling_chain", "rapid_relay"],
                inflow_usdt=86200.0, tx_hashes=[TX_HASH],
            )
        ],
        accounts=[
            AccountTarget(
                account_number="7810019921", bank_name="BCA", holder_name="Mule One",
                role="mule", inflow_idr=130_000_000, outflow_idr=125_000_000, tx_count=12,
            )
        ],
        timeline=[
            TimelineEvent(ts=FIXED_TS, description="bulk transfer to exchange",
                          amount=125_000_000, currency="IDR", ref="ft-001"),
        ],
        narrative="Test narrative for the suspicious flows.",
        total_at_risk_usdt=86200.0,
        total_at_risk_idr=86200.0 * 16300,
        idr_per_usdt=16300.0,
    )


def test_freeze_request_pdf_bytes_and_fields(ctx):
    doc = generate_freeze_request(ctx)
    assert doc.pdf[:5] == b"%PDF-"
    assert doc.size_bytes > 1000
    assert doc.type == "account_blocking"
    assert doc.format == "iasc"
    # Key fields present in the (uncompressed) PDF stream
    assert WALLET.encode() in doc.pdf
    assert b"7810019921" in doc.pdf
    assert TX_HASH.encode() in doc.pdf
    assert b"POJK 27/2024" in doc.pdf
    assert b"UU ITE Pasal 5" in doc.pdf
    assert b"peeling_chain" in doc.pdf
    assert b"CASE-2026-0142" in doc.pdf


def test_str_draft_pdf_and_goaml_shape(ctx):
    doc = generate_str_draft(ctx)
    assert doc.pdf[:5] == b"%PDF-"
    assert doc.type == "str_report"
    assert doc.format == "ppatk_str"
    # Subject identity stays a human fill-in placeholder
    assert SUBJECT_PLACEHOLDER.strip("[]").encode() in doc.pdf

    goaml = doc.meta["goaml_draft"]
    assert goaml["report"]["report_code"] == "STR"
    assert goaml["report"]["rentity_id"] == SUBJECT_PLACEHOLDER
    assert goaml["subjects"][0]["full_name"] == SUBJECT_PLACEHOLDER
    assert goaml["accounts"][0]["account_number"] == "7810019921"
    assert goaml["crypto_wallets"][0]["address"] == WALLET
    assert goaml["transactions"][0]["currency"] == "IDR"
    assert any("IND-LAY-01" in i for i in goaml["indicators"])
    assert goaml["data_mode"] == "poc"


def test_goaml_transaction_conversion(ctx):
    ctx.timeline.append(TimelineEvent(
        ts=FIXED_TS, description="USDT deposit", amount=100.0, currency="USDT", ref="0xabc"))
    goaml = build_goaml_draft(ctx)
    usdt_tx = goaml["transactions"][-1]
    assert usdt_tx["amount_original"] == 100.0
    assert usdt_tx["amount_local"] == pytest.approx(100.0 * ctx.idr_per_usdt)


def test_evidence_pack_contains_custody_manifest(ctx):
    freeze = generate_freeze_request(ctx)
    str_doc = generate_str_draft(ctx)
    pack = generate_evidence_pack(ctx, manifest_docs=[freeze, str_doc])
    assert pack.pdf[:5] == b"%PDF-"
    assert pack.type == "summary"
    # Manifest carries each document's SHA-256 (rendered as two 32-char halves)
    for d in (freeze, str_doc):
        assert d.sha256[:32].encode() in pack.pdf
        assert d.sha256[32:].encode() in pack.pdf
    assert b"Chain-of-custody manifest" in pack.pdf


def test_custody_hash_deterministic_and_verifiable(ctx):
    d1 = generate_freeze_request(ctx)
    d2 = generate_freeze_request(ctx)
    # invariant PDFs: identical context → identical bytes → identical hash
    assert d1.pdf == d2.pdf
    assert d1.sha256 == d2.sha256
    # stored hash matches an independent recomputation of the returned bytes
    assert sha256_hex(d1.pdf) == d1.sha256
    # different context → different hash
    ctx2 = ctx.model_copy(update={"case_id": "CASE-2026-9999"})
    assert generate_freeze_request(ctx2).sha256 != d1.sha256


def test_document_hashing_survived_the_custody_collapse(ctx):
    """The per-document *audit entry* is gone with the in-memory custody chain;
    the per-document *hash* is not, and must not be.

    They were always separate concerns: the chain recorded that a document was
    made, the hash IS the evidence that these are the bytes. Only the first moved
    into core.audit_log (as the `documents` array on one bundle entry) — see
    app/uncover/custody.py. This pins the half that stayed, because deleting a
    module is exactly when the wrong half gets removed.
    """
    doc = generate_freeze_request(ctx)
    assert doc.sha256 == sha256_hex(doc.pdf), "the stored hash must match the bytes"
    assert doc.sha256, "a document with no custody hash is not evidence"
