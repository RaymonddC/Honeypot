"""CASEDATA — analyst-entered records that feed TAKEDOWN + TRACE.

TestClient against the POC memory repo (no DB, no network). Verifies add/list,
that a hand-entered crypto transfer makes a brand-new wallet investigable, and
that a tracked bank account is surfaced (+ flagged) on the Bridge.
"""

import time

import pytest
from fastapi.testclient import TestClient

from app.casedata import repository as casedata_repo
from app.main import app
from tests.conftest import bearer

client = TestClient(app)
client.headers.update(bearer())


def _run_investigation(c: TestClient, address: str) -> dict:
    """Submit the async investigate job and poll to completion → the result."""
    r = c.post("/api/investigate", json={"address": address})
    assert r.status_code == 202, r.text
    job_id = r.json()["job_id"]
    state: dict = {}
    for _ in range(100):
        state = c.get(f"/api/investigate/jobs/{job_id}").json()
        if state["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert state["status"] == "done", state
    return state["result"]


@pytest.fixture(autouse=True)
def clean_store():
    casedata_repo.reset_stores()
    yield
    casedata_repo.reset_stores()


# ── bank accounts ───────────────────────────────────────────────────────── #


def test_add_and_list_bank_account():
    r = client.post(
        "/api/casedata/bank-accounts",
        json={
            "bank_name": "BCA",
            "account_number": "5271038462",
            "holder_name": "Rudi Hartono",
            "category": "mule",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["bank_name"] == "BCA"
    assert body["category"] == "mule"
    assert body["id"].startswith("bank_")

    listed = client.get("/api/casedata/bank-accounts").json()
    assert len(listed) == 1
    assert listed[0]["account_number"] == "5271038462"


def test_bank_account_requires_auth():
    anon = TestClient(app)  # no bearer header
    r = anon.post(
        "/api/casedata/bank-accounts",
        json={"bank_name": "BCA", "account_number": "123456"},
    )
    assert r.status_code == 401


def test_tracked_account_surfaces_on_bridge_watchlist():
    client.post(
        "/api/casedata/bank-accounts",
        json={"bank_name": "BCA", "account_number": "9990001112", "category": "scam"},
    )
    r = client.get("/api/bridge/accounts")
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["account_number"] == "9990001112"
    assert "seen_in_flow" in items[0]  # cross-checked against the generated flow


# ── crypto transfers → TAKEDOWN ─────────────────────────────────────────── #


def test_add_crypto_transfer_mints_hash():
    r = client.post(
        "/api/casedata/crypto-transfers",
        json={
            "from_addr": "TVictimAAAAAAAAAAAAAAAAAAAAAAAAAAA",
            "to_addr": "TScamBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
            "value": 25000,
            "ts": "2026-07-20T08:00:00+00:00",
            "category": "scam",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["tx_hash"]  # auto-minted
    assert body["from_addr"].startswith("TVictim")
    assert body["value"] == 25000


def test_manual_transfer_makes_new_wallet_investigable():
    """A brand-new wallet, known ONLY from a hand-entered transfer, has no graph
    before and is investigable after — proving the merge into the TAKEDOWN graph.
    (Uses the async investigate job: submit → poll.)"""
    new_wallet = "TBrandNewScamWalletZZZZZZZZZZZZZZZZ"
    victim = "TBrandNewVictimYYYYYYYYYYYYYYYYYYYY"

    with TestClient(app) as c:
        c.headers.update(bearer())
        # Before: unknown address → job completes with an empty graph.
        pre = _run_investigation(c, new_wallet)
        assert new_wallet not in pre["scores"]

        # Add a transfer victim → new_wallet
        c.post(
            "/api/casedata/crypto-transfers",
            json={
                "from_addr": victim,
                "to_addr": new_wallet,
                "value": 12345,
                "ts": "2026-07-20T09:00:00+00:00",
            },
        )

        # After: the wallet is investigable, and both endpoints appear in the graph
        post = _run_investigation(c, new_wallet)
        assert new_wallet in post["scores"]
        assert victim in post["scores"]


def test_manual_transfer_merges_into_existing_fixture_graph():
    """A manual edge off the existing fixture scam wallet joins its graph."""
    source = "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6"  # P1 fixture scam wallet
    new_cashout = "TManualCashoutWWWWWWWWWWWWWWWWWWWWW"

    with TestClient(app) as c:
        c.headers.update(bearer())
        base = _run_investigation(c, source)
        base_n = len(base["scores"])

        c.post(
            "/api/casedata/crypto-transfers",
            json={
                "from_addr": source,
                "to_addr": new_cashout,
                "value": 5000,
                "ts": "2026-07-21T10:00:00+00:00",
            },
        )
        after = _run_investigation(c, source)
        assert new_cashout in after["scores"]
        assert len(after["scores"]) == base_n + 1
