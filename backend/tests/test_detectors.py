"""Each of the 5 typology detectors, positive + negative cases."""

from app.takedown.features import compute_features
from app.takedown.graph import build_digraph
from app.takedown.scoring import (
    cycles_by_address,
    detect_circular,
    detect_fan_out,
    detect_peeling_chain,
    detect_rapid_relay,
    detect_structuring,
    iso_forest_scores,
    score_investigation,
)
from tests.conftest import EXCHANGE, MULE1, RELAY1, SOURCE, VICTIM1, make_transfer


# --- peeling chain -----------------------------------------------------------


def test_peeling_chain_fires_on_fixture_source(fixture_transfers):
    result = detect_peeling_chain(SOURCE, fixture_transfers)
    assert result.fired
    hops = result.evidence["hops"]
    assert len(hops) == 3  # source → relay1 → relay2 → exchange
    assert hops[-1]["to"] == EXCHANGE
    assert all(h["forward_share"] >= 0.7 for h in hops)
    assert hops[0]["peeled_off"] == 9900.0  # the mule fan-out is the peel


def test_peeling_chain_negative_on_victim(fixture_transfers):
    assert not detect_peeling_chain(VICTIM1, fixture_transfers).fired


# --- rapid relay -------------------------------------------------------------


def test_rapid_relay_fires_on_relay(fixture_transfers):
    fv = compute_features(RELAY1, fixture_transfers)
    result = detect_rapid_relay(RELAY1, fixture_transfers, fv)
    assert result.fired
    assert result.evidence["relay_pairs"]
    assert all(p["delta_seconds"] <= 300 for p in result.evidence["relay_pairs"])


def test_rapid_relay_negative_when_slow():
    ts = [
        make_transfer("Ta", "Tw", 1000, "2026-06-10T09:00:00", 1),
        make_transfer("Tw", "Tb", 990, "2026-06-10T15:00:00", 2),
    ]
    fv = compute_features("Tw", ts)
    assert not detect_rapid_relay("Tw", ts, fv).fired


# --- circular ----------------------------------------------------------------


def test_circular_fires_on_wash_cycle(fixture_transfers):
    g = build_digraph(fixture_transfers)
    cmap = cycles_by_address(g)
    result = detect_circular(MULE1, cmap.get(MULE1, []))
    assert result.fired
    assert any(MULE1 in c for c in result.evidence["cycles"])


def test_circular_negative_outside_cycle(fixture_transfers):
    g = build_digraph(fixture_transfers)
    cmap = cycles_by_address(g)
    assert not detect_circular(SOURCE, cmap.get(SOURCE, [])).fired


# --- structuring -------------------------------------------------------------


def test_structuring_fires_on_mule_fanout(fixture_transfers):
    result = detect_structuring(SOURCE, fixture_transfers)
    assert result.fired
    assert result.evidence["cluster_size"] >= 10  # 10 × 990 USDT
    assert 990.0 in result.evidence["amounts"]


def test_structuring_negative_on_distinct_amounts():
    ts = [
        make_transfer("Tw", f"Tb{i}", v, "2026-06-10T09:00:00", i)
        for i, v in enumerate([100, 5000, 90000])
    ]
    assert not detect_structuring("Tw", ts).fired


# --- fan-out -----------------------------------------------------------------


def test_fan_out_fires_on_source(fixture_transfers):
    result = detect_fan_out(SOURCE, fixture_transfers)
    assert result.fired
    assert result.evidence["unique_receivers"] >= 10


def test_fan_out_negative_on_relay(fixture_transfers):
    assert not detect_fan_out(RELAY1, fixture_transfers).fired


# --- isolation forest + composite ---------------------------------------------


def test_iso_forest_scores_normalized(fixture_transfers):
    from app.takedown.graph import hop_depths

    g = build_digraph(fixture_transfers)
    depths = hop_depths(g, SOURCE)
    features = {a: compute_features(a, fixture_transfers, d) for a, d in depths.items()}
    scores = iso_forest_scores(features)
    assert all(0.0 <= s <= 1.0 for s in scores.values())
    # the scam source is the most anomalous wallet in the population
    assert scores[SOURCE] == max(scores.values())


def test_score_investigation_narrative(fixture_transfers):
    scores = score_investigation(SOURCE, fixture_transfers)
    assert scores[SOURCE].composite_risk == "high"
    fired = {p.name for p in scores[SOURCE].patterns if p.fired}
    assert {"peeling_chain", "rapid_relay", "structuring", "fan_out"} <= fired
    assert scores[SOURCE].reasoning  # Glass Box is never empty
    # relay wallet also lands high (pass-through layering)
    assert scores[RELAY1].composite_risk == "high"
    # the tagged exchange deposit is a destination, not a suspect
    assert scores[EXCHANGE].composite_risk == "low"
    assert any("exchange" in r.lower() for r in scores[EXCHANGE].reasoning)
    # a victim depositor stays low
    assert scores[VICTIM1].composite_risk == "low"


def test_score_investigation_deterministic(fixture_transfers):
    a = score_investigation(SOURCE, fixture_transfers)
    b = score_investigation(SOURCE, fixture_transfers)
    assert {k: v.iso_forest_score for k, v in a.items()} == {
        k: v.iso_forest_score for k, v in b.items()
    }
