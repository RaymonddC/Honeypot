"""Synthetic PT A2Z fiat generator — determinism, shape, money conservation."""

from app.fiat import generator as gen
from app.fiat.generator import HOT_WALLET, generate_dataset


def test_generator_deterministic():
    """Same params → byte-identical dataset (seeded, no wall-clock/random)."""
    gen._generate.cache_clear()
    a = generate_dataset()
    gen._generate.cache_clear()
    b = generate_dataset()
    assert a.model_dump() == b.model_dump()


def test_all_roles_present():
    ds = generate_dataset()
    roles = {a.role for a in ds.accounts}
    assert {
        "payer", "shell_merchant", "mule", "collector_mule", "exchange", "retail"
    } <= roles
    assert len(ds.by_role("exchange")) == 3


def test_qris_deposits_in_range():
    ds = generate_dataset()
    qris = [t for t in ds.transactions if t.kind == "qris_deposit"]
    assert qris
    for t in qris:
        assert 10_000 <= t.amount <= 500_000
        assert t.amount % 1000 == 0
        assert t.channel == "qris"


def test_each_bulk_funds_one_usdt_deposit():
    """Money conservation: every collector bulk-to-exchange spawns exactly one
    amount-conserving USDT deposit at the hot wallet (correlation ground truth)."""
    ds = generate_dataset()
    bulks = [t for t in ds.transactions if t.kind == "bulk_to_exchange"]
    assert bulks
    assert len(ds.crypto_deposits) == len(bulks)
    for d in ds.crypto_deposits:
        assert d.to_addr == HOT_WALLET
        assert d.token_symbol == "USDT"
        assert d.data_mode == "poc"
        assert d.value > 0


def test_banks_from_known_set():
    ds = generate_dataset()
    assert {a.bank_name for a in ds.accounts} <= set(gen.BANKS_22)
