"""Feature engine — Gary's canonical 12, computed from transfer sets."""

from app.takedown.features import FEATURE_ORDER, compute_features
from tests.conftest import RELAY1, SOURCE, make_transfer


def test_empty_wallet_returns_zeroed_vector():
    fv = compute_features("Tunknown", [], chain_depth=2)
    assert fv.total_volume == 0.0
    assert fv.chain_depth == 2
    assert fv.unique_counterparties == 0


def test_feature_row_matches_canonical_order():
    fv = compute_features("Tunknown", [])
    assert len(fv.as_row()) == len(FEATURE_ORDER) == 13  # 12 features, volume split in two


def test_source_features_on_fixtures(fixture_transfers):
    fv = compute_features(SOURCE, fixture_transfers)
    # 3 victim deposits in, 10 mule fan-outs + 1 relay forward out
    assert fv.unique_counterparties == 14
    assert fv.total_volume == 100000.0 + 99900.0
    assert fv.max_tx_size == 90000.0
    assert fv.round_number_pct == 1.0  # all fixture amounts are round
    assert 0.99 <= fv.inout_ratio <= 1.0  # near-pure pass-through
    assert fv.fan_ratio == 3 / 11  # 3 senders / 11 receivers


def test_relay_features_on_fixtures(fixture_transfers):
    fv = compute_features(RELAY1, fixture_transfers, chain_depth=1)
    assert fv.rapid_relay_rate == 1.0  # everything forwarded within 5 min
    assert fv.inout_ratio > 0.99
    assert fv.chain_depth == 1
    assert fv.unique_counterparties == 3  # source in; peel + relay2 out


def test_rapid_relay_rate_zero_when_slow():
    ts = [
        make_transfer("Ta", "Tw", 1000, "2026-06-10T09:00:00", 1),
        make_transfer("Tw", "Tb", 1000, "2026-06-10T10:00:00", 2),  # 1h later
    ]
    assert compute_features("Tw", ts).rapid_relay_rate == 0.0


def test_self_loop_count():
    ts = [make_transfer("Tw", "Tw", 100, "2026-06-10T09:00:00", 1)]
    assert compute_features("Tw", ts).self_loop_count == 1


def test_round_number_pct():
    ts = [
        make_transfer("Ta", "Tw", 1000, "2026-06-10T09:00:00", 1),
        make_transfer("Ta", "Tw", 123.45, "2026-06-10T09:05:00", 2),
    ]
    assert compute_features("Tw", ts).round_number_pct == 0.5


def test_time_entropy_spread_vs_burst():
    burst = [
        make_transfer("Ta", "Tw", 10, f"2026-06-10T09:{m:02d}:00", i)
        for i, m in enumerate(range(5))
    ]
    spread = [
        make_transfer("Ta", "Tw", 10, f"2026-06-10T{h:02d}:00:00", i)
        for i, h in enumerate(range(0, 24, 5))
    ]
    assert compute_features("Tw", burst).time_entropy == 0.0
    assert compute_features("Tw", spread).time_entropy > 0.4
