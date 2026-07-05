"""Sankey aggregation + mule clustering over the generated dataset."""

from app.fiat.generator import generate_dataset
from app.trace.correlation import correlate
from app.trace.mules import detect_mule_clusters
from app.trace.sankey import build_sankey


def _build():
    ds = generate_dataset()
    clusters = detect_mule_clusters(ds)
    corrs = correlate(ds.transactions, ds.accounts, ds.crypto_deposits)
    return ds, clusters, corrs, build_sankey(ds, clusters, corrs)


def test_sankey_stages_and_link_integrity():
    _, _, _, sk = _build()
    node_ids = {n.id for n in sk.nodes}
    assert node_ids and sk.links
    for lk in sk.links:
        assert lk.source in node_ids
        assert lk.target in node_ids
        assert lk.kind in {"sweep", "bulk", "onramp", "offshore"}
    stages = {n.stage for n in sk.nodes}
    assert {0, 1, 2, 3} <= stages  # merchants → mules → exchange → hot wallet
    assert any(n.stage_name == "USDT hot wallet" for n in sk.nodes)


def test_sankey_links_aggregated_and_meta():
    _, _, corrs, sk = _build()
    keys = [(lk.source, lk.target, lk.kind) for lk in sk.links]
    assert len(keys) == len(set(keys))  # one aggregated link per (src,tgt,kind)
    assert sk.meta["correlated_deposits"] == len(corrs)
    assert sk.meta["onramp_total_usdt"] > 0
    onramp = [lk for lk in sk.links if lk.kind == "onramp"]
    assert onramp and all(lk.value_usdt for lk in onramp)
    assert any(lk.kind == "offshore" for lk in sk.links)  # payout stage created


def test_mule_clusters_detected():
    ds = generate_dataset()
    clusters = detect_mule_clusters(ds)
    assert clusters
    assert all(c.size >= 3 for c in clusters)
    assert any(c.flagged_mules > 0 for c in clusters)
    assert all(0.0 <= c.confidence <= 1.0 for c in clusters)
    assert any(c.exchange_accounts for c in clusters)  # a cluster cashes out


def test_mule_detection_deterministic():
    ds = generate_dataset()
    a = detect_mule_clusters(ds)
    b = detect_mule_clusters(ds)
    assert [(c.cluster_id, c.size, c.flagged_mules) for c in a] == [
        (c.cluster_id, c.size, c.flagged_mules) for c in b
    ]
