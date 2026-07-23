"""The 3 MVP honeypot scam scenarios — investment / judol / crypto-phishing.

Each scenario must replay end-to-end through the POC agent loop and produce the
right persona, transport, crime classification, and validator-corroborated
intel (the entities that make the transcript court-usable). TestClient against
the POC adapters — no DB, no network.
"""

import pytest
from fastapi.testclient import TestClient

from app.infiltrate import service
from app.infiltrate.scenarios import (
    JUDOL_BANK_ACCOUNT,
    JUDOL_SITE,
    PHISHING_ETH_WALLET,
    PHISHING_SITE,
    SCENARIOS,
)
from app.main import app
from tests.conftest import bearer

client = TestClient(app)
client.headers.update(bearer())


@pytest.fixture(autouse=True)
def clean_stores():
    service.reset_stores()
    yield
    service.reset_stores()


def start(scenario: str | None = None) -> dict:
    body = {"scenario": scenario} if scenario else {}
    r = client.post("/api/sessions", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_three_scenarios_are_exposed():
    r = client.get("/api/scenarios")
    assert r.status_code == 200, r.text
    scenarios = r.json()
    keys = {s["key"] for s in scenarios}
    assert keys == {"investment_scam", "judol_deposit", "crypto_phishing"}
    for s in scenarios:
        assert s["turns"] >= 6                        # a full scripted conversation
        assert s["persona"]["name"]
        assert s["expected_crime_type"] == s["key"]


def test_three_personas_are_exposed():
    personas = client.get("/api/personas").json()
    names = {p["name"] for p in personas}
    assert {"Bu Sari", "Pak Budi", "Mbak Rina"} <= names


@pytest.mark.parametrize("key", list(SCENARIOS))
def test_scenario_classifies_to_its_own_typology(key):
    s = start(key)
    assert s["crime_type"] == SCENARIOS[key].expected_crime_type
    assert s["classification"]["confidence"] >= 0.6
    assert s["persona"]["name"] == SCENARIOS[key].persona.name
    assert s["channel_ref"] == SCENARIOS[key].channel_ref
    assert s["custody"]["chain_intact"] is True
    assert s["entity_count"] >= 3


def test_default_scenario_is_investment_scam_unchanged():
    """No scenario key → the original ProfitMax replay, byte-for-byte behaviour."""
    s = start()
    assert s["crime_type"] == "investment_scam"
    assert s["persona"]["name"] == "Bu Sari"
    assert s["channel"] == "telegram"
    assert s["channel_ref"] == "@ProfitMax_Andi"
    assert s["message_count"] == 12                   # 6 turns × 2 directions
    assert s["entity_count"] == 5


def test_judol_discloses_site_and_mule_account():
    s = start("judol_deposit")
    ents = client.get(f"/api/entities?session={s['id']}").json()
    by_type = {e["type"]: e for e in ents}
    assert by_type["url"]["normalized_value"] == JUDOL_SITE
    assert by_type["bank_account"]["value"] == JUDOL_BANK_ACCOUNT
    assert by_type["bank_account"]["bank_name"] == "BCA"
    assert "phone" in by_type
    # deposit-mule disclosure escalates to a human analyst
    assert len(s["escalations"]) >= 1


def test_phishing_discloses_eth_wallet_and_probes_seed_phrase():
    s = start("crypto_phishing")
    ents = client.get(f"/api/entities?session={s['id']}").json()
    by_type = {e["type"]: e for e in ents}
    wallet = by_type["crypto_wallet"]
    assert wallet["value"] == PHISHING_ETH_WALLET
    assert wallet["chain"] == "eth"
    assert wallet["method"] == "regex"                # validator-corroborated
    assert by_type["url"]["normalized_value"] == PHISHING_SITE
    # the seed-phrase exfil attempt is flagged + escalated
    signals = {sig["signal"] for sig in s["scam_signals"]}
    assert "seed_phrase_probe" in signals
    assert len(s["escalations"]) >= 1


def test_scenario_entities_are_hash_chained():
    """Custody chain stays intact across a non-default scenario replay."""
    s = start("crypto_phishing")
    msgs = client.get(f"/api/sessions/{s['id']}/messages").json()
    assert msgs[0]["prev_sha256"] == "0" * 64
    for prev, cur in zip(msgs, msgs[1:]):
        assert cur["prev_sha256"] == prev["sha256"]
