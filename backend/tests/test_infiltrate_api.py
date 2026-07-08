"""INFILTRATE API — start replay session → transcript → entities → review flow.

TestClient against the POC adapters (offline replay + scripted persona), no DB,
no network. Mirrors the P1–P3 API-smoke style.
"""

import pytest
from fastapi.testclient import TestClient

from app.infiltrate import service
from app.infiltrate.channels import DEMO_BCA_ACCOUNT, DEMO_TRON_WALLET
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_stores():
    service.reset_stores()
    yield
    service.reset_stores()


def start() -> dict:
    r = client.post("/api/sessions", json={})
    assert r.status_code == 201, r.text
    return r.json()


def test_start_session_runs_full_replay():
    s = start()
    assert s["data_mode"] == "poc"
    assert s["status"] == "escalated"                 # analyst escalation fired
    assert s["persona"]["name"] == "Bu Sari"
    assert s["channel"] == "telegram"
    assert s["channel_ref"] == "@ProfitMax_Andi"
    assert s["message_count"] == 12                   # 6 turns × 2 directions
    assert s["entity_count"] == 5
    assert s["crime_type"] == "investment_scam"
    assert s["classification"]["confidence"] >= 0.8
    assert len(s["escalations"]) >= 1
    assert len(s["scam_signals"]) >= 1


def test_custody_summary_intact():
    s = start()
    assert s["custody"]["messages_logged"] == 12
    assert s["custody"]["chain_intact"] is True
    assert s["custody"]["genesis"] == "0" * 64
    assert len(s["custody"]["head_sha256"]) == 64


def test_messages_are_hash_chained_with_inline_entities():
    s = start()
    msgs = client.get(f"/api/sessions/{s['id']}/messages").json()
    assert len(msgs) == 12
    assert msgs[0]["direction"] == "inbound"
    assert msgs[0]["prev_sha256"] == "0" * 64
    for prev, cur in zip(msgs, msgs[1:]):
        assert cur["prev_sha256"] == prev["sha256"]
    # entities are inline on their source message
    inline = [e for m in msgs for e in m["entities"]]
    assert len(inline) == 5
    # outbound (persona) turns carry covert tool_calls for the Glass Box
    tool_turns = [m for m in msgs if m["direction"] == "outbound" and m["meta"].get("tool_calls")]
    assert tool_turns


def test_demo_wallet_and_bank_linked_to_investigation():
    """The narrative anchor: honeypot must surface the P1 fixture wallet + BCA mule."""
    s = start()
    ents = client.get(f"/api/entities?session={s['id']}").json()
    by_type = {e["type"]: e for e in ents}
    assert by_type["crypto_wallet"]["value"] == DEMO_TRON_WALLET
    assert by_type["crypto_wallet"]["chain"] == "tron"
    assert by_type["crypto_wallet"]["method"] == "regex"        # validator-corroborated
    assert by_type["bank_account"]["value"] == DEMO_BCA_ACCOUNT
    assert by_type["bank_account"]["bank_name"] == "BCA"
    assert by_type["phone"]["normalized_value"].startswith("+62")


def test_entity_review_updates_status():
    s = start()
    ent = client.get(f"/api/entities?session={s['id']}").json()[0]
    r = client.post(f"/api/entities/{ent['id']}/review", json={"status": "confirmed"})
    assert r.status_code == 200
    body = r.json()
    assert body["review_status"] == "confirmed"
    assert body["method"] == "human"
    # status filter reflects the change
    confirmed = client.get(f"/api/entities?session={s['id']}&status=confirmed").json()
    assert [e["id"] for e in confirmed] == [ent["id"]]


def test_syndicate_clustered_from_entities():
    s = start()
    syns = client.get("/api/syndicates").json()
    assert len(syns) == 1
    syn = syns[0]
    assert syn["id"] == s["syndicate_id"]
    assert syn["entity_count"] == 5
    assert s["id"] in syn["session_ids"]
    kinds = {m["link_type"] for m in syn["members"]}
    assert "collection_wallet" in kinds and "mule_account" in kinds


def test_personas_endpoint():
    personas = client.get("/api/personas").json()
    assert any(p["id"] == "per_busari" and p["name"] == "Bu Sari" for p in personas)


def test_unknown_session_404_envelope():
    r = client.get("/api/sessions/sess_nope/messages")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "session_not_found"


def test_review_unknown_entity_404():
    r = client.post("/api/entities/ent_nope/review", json={"status": "rejected"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "entity_not_found"


def test_invalid_review_status_422():
    s = start()
    ent = client.get(f"/api/entities?session={s['id']}").json()[0]
    r = client.post(f"/api/entities/{ent['id']}/review", json={"status": "banana"})
    assert r.status_code == 422


def test_startup_seeds_a_live_session():
    """Lifespan seeds one POC replay so the console shows live data (no manual POST)."""
    service.reset_stores()
    with TestClient(app) as seeded_client:      # `with` triggers lifespan startup
        sessions = seeded_client.get("/api/sessions").json()
        assert len(sessions) == 1
        assert sessions[0]["crime_type"] == "investment_scam"
        assert sessions[0]["entity_count"] == 5
    service.reset_stores()
