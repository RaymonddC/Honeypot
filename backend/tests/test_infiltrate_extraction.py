"""Entity extraction — Layer-A regex/validators, normalization, reconciliation."""

import pytest

from app.infiltrate import extraction as ex
from app.infiltrate.channels import DEMO_BCA_ACCOUNT, DEMO_TRON_WALLET, REPLAY_SCRIPT


# --- crypto wallets --------------------------------------------------------- #

def test_tron_wallet_extracted_and_chained():
    ents = ex.extract_layer_a(f"kirim USDT ke {DEMO_TRON_WALLET} network TRC20")
    wallets = [e for e in ents if e.type == "crypto_wallet"]
    assert len(wallets) == 1
    w = wallets[0]
    assert w.value == DEMO_TRON_WALLET
    assert w.chain == "tron"
    assert w.confidence >= 0.9
    assert "USDT-TRC20" in w.context


def test_valid_tron_base58check_scores_highest():
    # A real 34-char base58check TRON address (USDT-TRC20 contract) → checksum passes.
    chain, validators, conf = ex.validate_crypto("TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t")
    assert chain == "tron"
    assert "tron_base58check" in validators
    assert conf > 0.95


@pytest.mark.parametrize("addr,chain", [
    ("0x742d35Cc6634C0532925a3b844Bc454e4438f44e", "eth"),
    ("bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4", "btc"),
])
def test_other_chains_format_validated(addr, chain):
    detected, validators, conf = ex.validate_crypto(addr)
    assert detected == chain
    assert validators and conf > 0


def test_non_wallet_text_rejected():
    assert ex.validate_crypto("Terima kasih") == (None, [], 0.0)


# --- phones (E.164 normalization) ------------------------------------------ #

@pytest.mark.parametrize("raw,expected", [
    ("0813-9988-7766", "+6281399887766"),
    ("+62 812-3344-5566", "+6281233445566"),
    ("081399887766", "+6281399887766"),
    ("62 851 2233 4455", "+6285122334455"),
])
def test_phone_normalization_to_e164(raw, expected):
    assert ex.normalize_phone(raw) == expected


@pytest.mark.parametrize("bad", ["123", "021-5551234", "not a phone"])
def test_phone_rejects_non_mobile(bad):
    assert ex.normalize_phone(bad) is None


# --- URLs ------------------------------------------------------------------- #

def test_url_extracted_and_refanged():
    ents = ex.extract_layer_a("cek di hxxps://profit-maxx-invest[.]com sekarang")
    urls = [e for e in ents if e.type == "url"]
    assert len(urls) == 1
    assert urls[0].normalized_value == "https://profit-maxx-invest.com"


# --- Indonesian bank accounts (context-anchored) --------------------------- #

def test_bank_account_needs_context_anchor():
    # Bare digit run with no bank keyword → not extracted.
    assert not [e for e in ex.extract_layer_a("nomor antrian 5271038462 ya") if e.type == "bank_account"]


def test_bank_account_with_anchor_and_bank_name():
    ents = ex.extract_layer_a("transfer ke rekening BCA 5271038462 a.n. Rudi Hartono")
    accts = [e for e in ents if e.type == "bank_account"]
    assert len(accts) == 1
    a = accts[0]
    assert a.normalized_value == "5271038462"
    assert a.bank_name == "BCA"
    assert "bank_name_match" in a.validators_passed
    assert "Rudi Hartono" in a.context


# --- reconciliation --------------------------------------------------------- #

def test_reconcile_corroboration_boosts_confidence():
    a = ex.extract_layer_a(f"wallet {DEMO_TRON_WALLET}")
    base_confidence = a[0].confidence              # capture before reconcile
    hint = ex.validate_layer_b_hint(
        {"type": "crypto_wallet", "value": DEMO_TRON_WALLET, "chain": "tron"}
    )
    merged = ex.reconcile(a, [hint])
    assert len(merged) == 1
    m = merged[0]
    assert set(m.methods) == {"regex", "llm"}     # corroborated across layers
    assert m.method == "regex"                     # regex = highest-trust label
    assert m.confidence > base_confidence          # boosted


def test_layer_b_hint_rejected_if_unvalidated():
    # A hallucinated "wallet" that fails Layer-A validation is dropped (anti-poisoning).
    assert ex.validate_layer_b_hint(
        {"type": "crypto_wallet", "value": "definitely-not-a-wallet"}
    ) is None


def test_full_transcript_yields_demo_entities_per_message():
    """The replay must reveal the demo TRON wallet + BCA account (links to Investigation)."""
    found: dict[str, list[str]] = {}
    for turn in REPLAY_SCRIPT:
        for e in ex.extract_layer_a(turn.scammer):
            found.setdefault(e.type, []).append(e.normalized_value)
    assert DEMO_TRON_WALLET in found["crypto_wallet"]
    assert DEMO_BCA_ACCOUNT in found["bank_account"]
    assert "+6281399887766" in found["phone"]
    assert "https://profit-maxx-invest.com" in found["url"]
