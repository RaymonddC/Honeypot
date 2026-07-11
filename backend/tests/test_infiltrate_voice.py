"""INFILTRATE voice (P4b) — call replay session over the reused pipeline.

Voice channel swaps in; agent loop, extraction, custody, classifier and
syndicate clustering are the same code paths as text. TestClient against the
POC adapters — offline, deterministic, no network, no keys.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.adapters import get_adapter
from app.core.config import Settings
from app.infiltrate import service
from app.infiltrate.channels import DEMO_BCA_ACCOUNT, DEMO_TRON_WALLET
from app.infiltrate.voice import (
    VOICE_CALLER_NUMBER,
    VOICE_SCRIPT,
    ElevenLabsTTSAdapter,
    GoogleTTSAdapter,
    HiggsfieldTTSAdapter,
    PassthroughSTTAdapter,
    PstnChannelAdapter,
    VoiceMarkTTSAdapter,
    VoiceReplayChannelAdapter,
    WhisperSTTAdapter,
    estimate_duration,
    select_live_tts_adapter,
)
from app.main import app
from tests.conftest import bearer

client = TestClient(app)
client.headers.update(bearer())  # P5: POST /sessions requires identity


@pytest.fixture(autouse=True)
def clean_stores():
    service.reset_stores()
    yield
    service.reset_stores()


def start_voice() -> dict:
    r = client.post("/api/sessions", json={"channel_type": "voice"})
    assert r.status_code == 201, r.text
    return r.json()


# --------------------------------------------------------------------------- #
# Voice session — the reused pipeline over the call channel
# --------------------------------------------------------------------------- #


def test_voice_session_shape():
    s = start_voice()
    assert s["channel_type"] == "voice"
    assert s["channel"] == "voice"
    assert s["channel_ref"] == VOICE_CALLER_NUMBER          # caller ID is intel
    assert s["persona"]["name"] == "Bu Sari"
    assert s["data_mode"] == "poc"
    assert s["status"] == "escalated"                       # wallet disclosure fired
    assert s["crime_type"] == "investment_scam"
    assert s["message_count"] == len(VOICE_SCRIPT) * 2      # inbound + outbound per turn
    assert s["entity_count"] == 3                           # phone + bank + wallet


def test_voice_script_discloses_p1_wallet_with_readback():
    """The call must disclose the P1 fixture wallet + BCA mule, and the persona
    must read them back (the confirmation beat that locks them on tape)."""
    scammer_lines = " ".join(t.scammer for t in VOICE_SCRIPT)
    assert DEMO_TRON_WALLET in scammer_lines
    assert DEMO_BCA_ACCOUNT in scammer_lines
    # Read-back confirmation: persona repeats wallet AND account in one reply.
    assert any(
        DEMO_TRON_WALLET in t.persona_reply and DEMO_BCA_ACCOUNT in t.persona_reply
        for t in VOICE_SCRIPT
    )


def test_voice_extraction_finds_wallet_and_mule():
    s = start_voice()
    ents = client.get(f"/api/entities?session={s['id']}").json()
    by_type = {e["type"]: e for e in ents}
    assert by_type["crypto_wallet"]["value"] == DEMO_TRON_WALLET
    assert by_type["crypto_wallet"]["chain"] == "tron"
    assert by_type["crypto_wallet"]["method"] == "regex"    # validator-corroborated
    assert by_type["bank_account"]["value"] == DEMO_BCA_ACCOUNT
    assert by_type["bank_account"]["bank_name"] == "BCA"
    assert by_type["phone"]["normalized_value"].startswith("+62")


def test_voice_custody_chain_intact():
    s = start_voice()
    assert s["custody"]["chain_intact"] is True
    assert s["custody"]["messages_logged"] == len(VOICE_SCRIPT) * 2
    assert s["custody"]["genesis"] == "0" * 64
    msgs = client.get(f"/api/sessions/{s['id']}/messages").json()
    assert msgs[0]["prev_sha256"] == "0" * 64
    for prev, cur in zip(msgs, msgs[1:]):
        assert cur["prev_sha256"] == prev["sha256"]


def test_voice_messages_carry_voice_marks():
    """Every voice message carries {speaker, duration_seconds, offset_seconds}
    and the offsets form a consistent call timeline."""
    s = start_voice()
    msgs = client.get(f"/api/sessions/{s['id']}/messages").json()
    expected_offset = 0.0
    for m in msgs:
        meta = m["meta"]
        expected_speaker = "scammer" if m["direction"] == "inbound" else "persona"
        assert meta["speaker"] == expected_speaker
        assert meta["duration_seconds"] > 0
        assert meta["offset_seconds"] == pytest.approx(expected_offset, abs=0.11)
        expected_offset += meta["duration_seconds"]
    # durations are the deterministic spoken-time estimate of the line
    assert msgs[0]["meta"]["duration_seconds"] == estimate_duration(msgs[0]["content"])


def test_voice_syndicate_clusters_from_call_intel():
    s = start_voice()
    syns = client.get("/api/syndicates").json()
    assert len(syns) == 1
    syn = syns[0]
    assert syn["id"] == s["syndicate_id"]
    assert VOICE_CALLER_NUMBER in syn["label"]
    kinds = {m["link_type"] for m in syn["members"]}
    assert "collection_wallet" in kinds and "mule_account" in kinds


def test_text_session_default_unchanged():
    """channel_type defaults to text — the existing replay is untouched."""
    r = client.post("/api/sessions", json={})
    assert r.status_code == 201
    s = r.json()
    assert s["channel_type"] == "text"
    assert s["channel"] == "telegram"
    msgs = client.get(f"/api/sessions/{s['id']}/messages").json()
    assert all("speaker" not in m["meta"] for m in msgs)    # no voice marks on text


# --------------------------------------------------------------------------- #
# GET /api/sessions/{id}/audio/{seq} — POC voice marks
# --------------------------------------------------------------------------- #


def test_audio_endpoint_returns_poc_voice_marks():
    s = start_voice()
    msgs = client.get(f"/api/sessions/{s['id']}/messages").json()
    first = msgs[0]
    r = client.get(f"/api/sessions/{s['id']}/audio/{first['seq']}")
    assert r.status_code == 200
    mark = r.json()
    assert mark["session_id"] == s["id"]
    assert mark["seq"] == first["seq"]
    assert mark["speaker"] == "scammer"
    assert mark["text"] == first["content"]
    assert mark["duration_seconds"] == first["meta"]["duration_seconds"]
    assert mark["offset_seconds"] == first["meta"]["offset_seconds"]
    assert mark["audio_url"] is None                        # browser speaks it (POC)
    assert mark["provider"] == "poc-voice-marks"


def test_audio_endpoint_text_session_has_no_audio():
    r = client.post("/api/sessions", json={})
    s = r.json()
    audio = client.get(f"/api/sessions/{s['id']}/audio/1")
    assert audio.status_code == 204


def test_audio_endpoint_404s():
    s = start_voice()
    assert client.get("/api/sessions/sess_nope/audio/1").status_code == 404
    r = client.get(f"/api/sessions/{s['id']}/audio/999")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "message_not_found"


# --------------------------------------------------------------------------- #
# Voice channel adapter — POC replay + LIVE fail-loud
# --------------------------------------------------------------------------- #


def test_voice_channel_poc_is_the_registered_default():
    channel = get_adapter("channel_voice", "infiltrate")
    assert isinstance(channel, VoiceReplayChannelAdapter)
    assert channel.data_mode == "poc"
    assert channel.channel == "voice"
    assert channel.channel_ref == VOICE_CALLER_NUMBER


async def test_voice_replay_adapter_is_deterministic():
    contents = []
    for _ in range(2):
        adapter = VoiceReplayChannelAdapter()
        received = []
        while (msg := await adapter.receive()) is not None:
            received.append(msg.content)
        contents.append(received)
    assert contents[0] == contents[1]
    assert len(contents[0]) == len(VOICE_SCRIPT)


def test_live_pstn_channel_fails_loudly():
    with pytest.raises(NotImplementedError, match="PSTN"):
        PstnChannelAdapter()


# --------------------------------------------------------------------------- #
# STT boundary — POC passthrough + LIVE fail-loud
# --------------------------------------------------------------------------- #


async def test_stt_poc_is_transcript_passthrough():
    stt = get_adapter("stt", "infiltrate")
    assert isinstance(stt, PassthroughSTTAdapter)
    assert stt.data_mode == "poc"
    assert await stt.transcribe("halo bu sari") == "halo bu sari"
    assert await stt.transcribe(b"halo bu sari") == "halo bu sari"


def test_stt_live_fails_loudly():
    with pytest.raises(NotImplementedError, match="STT"):
        WhisperSTTAdapter()


# --------------------------------------------------------------------------- #
# TTS boundary — POC voice marks + pluggable LIVE providers
# --------------------------------------------------------------------------- #


async def test_tts_poc_returns_voice_marks_not_audio():
    tts = get_adapter("tts", "infiltrate")
    assert isinstance(tts, VoiceMarkTTSAdapter)
    assert tts.data_mode == "poc"
    line = VOICE_SCRIPT[0].scammer
    result = await tts.synthesize(line, voice="scammer")
    assert result.provider == "poc-voice-marks"
    assert result.voice == "scammer"
    assert result.text == line
    assert result.duration_seconds == estimate_duration(line)
    assert result.audio_url is None


@pytest.mark.parametrize(
    "impl", [GoogleTTSAdapter, HiggsfieldTTSAdapter, ElevenLabsTTSAdapter]
)
def test_live_tts_providers_fail_loudly(impl):
    with pytest.raises(NotImplementedError, match=impl.__name__):
        impl()


@pytest.mark.parametrize(
    ("provider", "impl_name"),
    [
        ("google", "GoogleTTSAdapter"),
        ("higgsfield", "HiggsfieldTTSAdapter"),
        ("elevenlabs", "ElevenLabsTTSAdapter"),
    ],
)
def test_tts_provider_selected_by_setting(provider, impl_name):
    """ITTU_TTS_PROVIDER picks the LIVE impl — each still fails loud (no keys)."""
    with pytest.raises(NotImplementedError, match=impl_name):
        select_live_tts_adapter(Settings(tts_provider=provider))


def test_tts_unknown_provider_rejected():
    with pytest.raises(LookupError, match="Unknown LIVE TTS provider"):
        select_live_tts_adapter(Settings(tts_provider="clippy"))


def test_estimate_duration_is_deterministic_and_floored():
    assert estimate_duration("halo") == 2.0                 # floor for short lines
    long_line = "kata " * 46
    assert estimate_duration(long_line) == estimate_duration(long_line) == 20.0
