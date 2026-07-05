"""API smoke tests — TestClient against the POC adapter (no DB, no network)."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import EXCHANGE, RELAY1, SOURCE


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "mode": "poc"}


def test_investigate(client):
    r = client.post("/api/investigate", json={"address": SOURCE})
    assert r.status_code == 200
    body = r.json()
    assert body["address"] == SOURCE
    assert body["data_mode"] == "poc"
    assert len(body["graph"]["nodes"]) == 19
    assert len(body["graph"]["edges"]) == 21
    assert set(body["scores"]) == {n["data"]["id"] for n in body["graph"]["nodes"]}
    src_node = next(n for n in body["graph"]["nodes"] if n["data"]["id"] == SOURCE)
    assert src_node["data"]["is_source"] is True
    assert src_node["data"]["risk"] == "high"


def test_wallet_graph_hops_limit(client):
    r3 = client.get(f"/api/wallets/{SOURCE}/graph?hops=3")
    r1 = client.get(f"/api/wallets/{SOURCE}/graph?hops=1")
    assert r3.status_code == r1.status_code == 200
    assert len(r1.json()["nodes"]) < len(r3.json()["nodes"])
    # hop annotations respect the BFS depth
    assert all(n["data"]["hop"] <= 1 for n in r1.json()["nodes"])


def test_wallet_graph_rejects_hops_over_max(client):
    assert client.get(f"/api/wallets/{SOURCE}/graph?hops=7").status_code == 422


def test_wallet_risk(client):
    r = client.get(f"/api/wallets/{RELAY1}/risk")
    assert r.status_code == 200
    body = r.json()
    assert body["composite_risk"] == "high"
    assert 0 <= body["iso_forest_score"] <= 1
    assert {p["name"] for p in body["patterns"]} == {
        "peeling_chain", "rapid_relay", "circular", "structuring", "fan_out",
    }
    assert body["reasoning"]
    assert len(body["features"]) == 13  # 12 features, volume split total/mean
    assert body["data_mode"] == "poc"


def test_exchange_tagged_low_risk(client):
    body = client.get(f"/api/wallets/{EXCHANGE}/risk").json()
    assert body["composite_risk"] == "low"
    assert body["tags"][0]["tag"] == "Indodax"
    assert body["tags"][0]["category"] == "exchange"


def test_unknown_wallet_404_error_envelope(client):
    r = client.get("/api/wallets/TnopeNopeNope/risk")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "wallet_not_found"
