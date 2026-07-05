"""Bridge API smoke + cross-endpoint consistency (TestClient, POC in-memory)."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_simulate_summary():
    r = client.post("/api/bridge/simulate", json={})
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    assert d["data_mode"] == "poc"
    s = d["summary"]
    assert s["accounts"]["total"] > 0
    assert s["crypto_deposits"] > 0
    assert s["correlations"] > 0
    assert s["mule_clusters"] > 0


def test_sankey_link_integrity():
    d = client.get("/api/bridge/sankey").json()
    node_ids = {n["id"] for n in d["nodes"]}
    assert node_ids and d["links"]
    for lk in d["links"]:
        assert lk["source"] in node_ids
        assert lk["target"] in node_ids
    assert d["meta"]["onramp_total_usdt"] > 0


def test_correlations_sorted_with_unmatched():
    d = client.get("/api/bridge/correlations").json()
    items = d["items"]
    assert items
    confs = [c["confidence"] for c in items]
    assert confs == sorted(confs, reverse=True)
    for c in items:
        assert 0 < c["time_delta_seconds"] <= 1800
        assert c["fiat"]["amount_idr"] > 0
        assert c["crypto"]["amount_usdt"] > 0
    # the TAKEDOWN peeling-chain cash-out has no fiat counterpart
    assert d["unmatched_deposits"]


def test_correlations_min_confidence_filter():
    everything = client.get("/api/bridge/correlations").json()["items"]
    hi = client.get(
        "/api/bridge/correlations", params={"min_confidence": 0.99}
    ).json()["items"]
    assert len(hi) <= len(everything)
    assert all(c["confidence"] >= 0.99 for c in hi)


def test_mules_endpoint():
    d = client.get("/api/bridge/mules").json()
    assert d["items"]
    for c in d["items"]:
        assert c["size"] >= 3
        assert 0.0 <= c["confidence"] <= 1.0
