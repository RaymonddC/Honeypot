"""INFILTRATE Tier-B live turns (docs/Live-Voice-Calls.md) — interactive
session start + POST /sessions/{id}/turn.

Unlike the scripted replay (POST /sessions with no `interactive` flag), an
interactive session opens with just the persona's greeting and then takes
free-text inbound utterances one at a time — same pipeline (agent turn +
Layer-A/B extraction + custody + reclassify), just driven turn-by-turn
instead of pre-run. POC/keyless stays deterministic and never 500s (the
`InteractiveScriptedGateway` fallback); LIVE only engages with a key, and the
provider call itself is always mocked here — hermetic, no network.
"""

import json
import types

from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.infiltrate import gateway as gateway_module
from app.infiltrate import service
from app.infiltrate.channels import DEMO_BCA_ACCOUNT, DEMO_TRON_WALLET
from app.infiltrate.gateway import INTERACTIVE_STALL_LINES
from app.main import app
from tests.conftest import bearer

client = TestClient(app)
client.headers.update(bearer())


def setup_function(_fn=None):
    service.reset_stores()


def teardown_function(_fn=None):
    service.reset_stores()


def start_interactive(channel_type: str = "voice") -> dict:
    r = client.post("/api/sessions", json={"channel_type": channel_type, "interactive": True})
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Starting an interactive session
# --------------------------------------------------------------------------- #


def test_interactive_start_is_open_not_a_scripted_replay():
    s = start_interactive()
    assert s["status"] == "active"
    assert s["message_count"] == 1                  # just the greeting — no replay
    assert s["entity_count"] == 0
    assert s["crime_type"] is None
    assert s["custody"]["chain_intact"] is True
    assert s["custody"]["messages_logged"] == 1

    msgs = client.get(f"/api/sessions/{s['id']}/messages").json()
    assert len(msgs) == 1
    assert msgs[0]["direction"] == "outbound"        # persona speaks first
    assert msgs[0]["meta"]["speaker"] == "persona"
    assert msgs[0]["meta"]["duration_seconds"] > 0


def test_interactive_text_channel_also_supported():
    s = start_interactive(channel_type="text")
    assert s["channel_type"] == "text"
    assert s["message_count"] == 1
    msgs = client.get(f"/api/sessions/{s['id']}/messages").json()
    assert "speaker" not in msgs[0]["meta"]          # no voice marks on text


# --------------------------------------------------------------------------- #
# POST /sessions/{id}/turn — keyless (POC-safe) fallback
# --------------------------------------------------------------------------- #


def test_turn_keyless_fallback_never_500s_and_is_deterministic():
    s = start_interactive()
    r = client.post(f"/api/sessions/{s['id']}/turn", json={"text": "halo, ini siapa ya?"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["session_id"] == s["id"]
    assert out["turn"] == 0
    assert out["model"] == "poc-interactive-stall-1"
    assert len(out["messages"]) == 2
    inbound, outbound = out["messages"]
    assert inbound["direction"] == "inbound" and inbound["content"] == "halo, ini siapa ya?"
    assert outbound["direction"] == "outbound"
    assert outbound["content"] == INTERACTIVE_STALL_LINES[0]
    assert out["custody"]["messages_logged"] == 3    # greeting + this turn's 2


def test_turn_advances_deterministically_across_multiple_turns():
    s = start_interactive()
    for i in range(3):
        r = client.post(f"/api/sessions/{s['id']}/turn", json={"text": f"turn {i}"})
        out = r.json()
        assert out["turn"] == i
        assert out["messages"][1]["content"] == INTERACTIVE_STALL_LINES[i % len(INTERACTIVE_STALL_LINES)]

    session = client.get(f"/api/sessions/{s['id']}").json()
    assert session["message_count"] == 1 + 3 * 2
    assert session["custody"]["chain_intact"] is True


def test_turn_extracts_entities_from_free_text():
    s = start_interactive()
    text = (
        f"transfer ke rekening BCA 5271038462 atau kirim USDT ke {DEMO_TRON_WALLET} ya nak"
    )
    r = client.post(f"/api/sessions/{s['id']}/turn", json={"text": text})
    out = r.json()
    by_type = {e["type"]: e for e in out["entities"]}
    assert by_type["bank_account"]["value"] == DEMO_BCA_ACCOUNT
    assert by_type["crypto_wallet"]["value"] == DEMO_TRON_WALLET
    assert by_type["crypto_wallet"]["chain"] == "tron"

    # Entities also show up on GET /api/entities for the session.
    ents = client.get(f"/api/entities?session={s['id']}").json()
    assert {e["type"] for e in ents} >= {"bank_account", "crypto_wallet"}


def test_turn_voice_marks_offsets_continue_the_call_timeline():
    s = start_interactive()
    greeting_offset = client.get(f"/api/sessions/{s['id']}/messages").json()[0]["meta"]["offset_seconds"]
    r = client.post(f"/api/sessions/{s['id']}/turn", json={"text": "halo pak"})
    inbound = r.json()["messages"][0]
    assert inbound["meta"]["offset_seconds"] >= greeting_offset


# --------------------------------------------------------------------------- #
# 404s
# --------------------------------------------------------------------------- #


def test_turn_404s_unknown_session():
    r = client.post("/api/sessions/sess_nope/turn", json={"text": "hi"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "session_not_found"


def test_turn_404s_a_finished_scripted_replay_session():
    """Scripted (non-interactive) sessions have no open `_LiveState` — /turn
    is a Tier-B-only endpoint."""
    r = client.post("/api/sessions", json={})
    s = r.json()
    turn = client.post(f"/api/sessions/{s['id']}/turn", json={"text": "hi"})
    assert turn.status_code == 404


def test_turn_requires_auth():
    s = start_interactive()
    anon = TestClient(app)  # no bearer header
    r = anon.post(f"/api/sessions/{s['id']}/turn", json={"text": "hi"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "missing_token"


# --------------------------------------------------------------------------- #
# POST /sessions/{id}/turn — LIVE brain (hermetic: litellm call is mocked)
# --------------------------------------------------------------------------- #


def _fake_tool_call(name: str, args: dict):
    return types.SimpleNamespace(
        function=types.SimpleNamespace(name=name, arguments=json.dumps(args))
    )


def _fake_litellm_response(content: str, tool_calls=None, model="claude-haiku-4-5"):
    message = types.SimpleNamespace(content=content, tool_calls=tool_calls or [])
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)], model=model)


def test_turn_uses_live_llm_when_a_key_is_configured(monkeypatch):
    settings = get_settings()
    settings.llm_api_key = "sk-test-not-real"
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    async def fake_complete(**kwargs):
        return _fake_litellm_response(
            "baik nak, ibu catat dulu ya",
            tool_calls=[_fake_tool_call(
                "escalate_to_analyst", {"reason": "high_value_turn", "detail": "money question"}
            )],
        )

    monkeypatch.setattr(gateway_module, "_litellm_complete", fake_complete)
    try:
        s = start_interactive()
        r = client.post(f"/api/sessions/{s['id']}/turn", json={"text": "kirim ke rekening saya"})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["model"] == "claude-haiku-4-5"
        assert out["messages"][1]["content"] == "baik nak, ibu catat dulu ya"
        assert out["status"] == "escalated"          # escalate_to_analyst tool fired
    finally:
        settings.llm_api_key = ""
