"""Correlation engine — rediscovers the on-ramp; honors window + tolerance."""

import uuid
from datetime import datetime, timedelta, timezone

from app.chain.schemas import Transfer
from app.fiat.generator import generate_dataset
from app.fiat.schemas import FiatAccountOut, FiatTransactionOut
from app.trace.correlation import (
    AMOUNT_TOLERANCE,
    TIME_WINDOW_SECONDS,
    correlate,
    unmatched_deposits,
)

RATE = 16_300.0


def test_correlate_matches_every_synthetic_onramp():
    """Each amount-conserving deposit rediscovers its bulk transfer, 1:1."""
    ds = generate_dataset()
    corrs = correlate(ds.transactions, ds.accounts, ds.crypto_deposits)
    assert len(corrs) == len(ds.crypto_deposits)
    assert len({c.fiat.fiat_tx_id for c in corrs}) == len(corrs)  # no fiat reused
    assert len({c.crypto.tx_hash for c in corrs}) == len(corrs)   # no deposit reused
    for c in corrs:
        assert 0 < c.time_delta_seconds <= TIME_WINDOW_SECONDS
        assert c.amount_match >= 1 - AMOUNT_TOLERANCE
        assert 0.0 < c.confidence <= 1.0
    assert corrs == sorted(corrs, key=lambda c: -c.confidence)  # confidence desc


# --- hand-crafted unit cases -------------------------------------------------

T0 = datetime(2026, 6, 10, 9, 0, tzinfo=timezone.utc)


def _bulk(amount_idr: float = 16_300_000.0):
    exch = FiatAccountOut(id=uuid.uuid4(), account_number="1234567890",
                          bank_name="BCA", holder_name="PT X", role="exchange")
    collector = FiatAccountOut(id=uuid.uuid4(), account_number="9999999999",
                               bank_name="BRI", holder_name="Y", role="collector_mule")
    tx = FiatTransactionOut(id=uuid.uuid4(), from_account_id=collector.id,
                            to_account_id=exch.id, amount=amount_idr, ts=T0,
                            channel="transfer", kind="bulk_to_exchange")
    return [exch, collector], tx  # expected USDT = amount/RATE = 1000


def _deposit(value: float, ts: datetime) -> Transfer:
    return Transfer(tx_hash=uuid.uuid4().hex, from_addr="Tsender", to_addr="Thot",
                    value=value, token_symbol="USDT", ts=ts)


def test_no_match_outside_time_window():
    accts, tx = _bulk()
    dep = _deposit(1000.0, T0 + timedelta(hours=2))  # exact amount, far too late
    assert correlate([tx], accts, [dep], rate=RATE) == []


def test_no_match_outside_amount_tolerance():
    accts, tx = _bulk()
    dep = _deposit(800.0, T0 + timedelta(minutes=10))  # 20% off, in window
    assert correlate([tx], accts, [dep], rate=RATE) == []


def test_match_within_window_and_tolerance():
    accts, tx = _bulk()
    dep = _deposit(995.0, T0 + timedelta(minutes=10))  # 0.5% fee, in window
    corrs = correlate([tx], accts, [dep], rate=RATE)
    assert len(corrs) == 1
    assert corrs[0].fiat.from_bank == "BRI"
    assert corrs[0].crypto.amount_usdt == 995.0


def test_unmatched_deposits_returns_uncorrelated():
    accts, tx = _bulk()
    matched = _deposit(995.0, T0 + timedelta(minutes=10))
    orphan = _deposit(86_200.0, T0 + timedelta(minutes=5))  # no fiat counterpart
    corrs = correlate([tx], accts, [matched, orphan], rate=RATE)
    un = unmatched_deposits([matched, orphan], corrs)
    assert [d.tx_hash for d in un] == [orphan.tx_hash]
