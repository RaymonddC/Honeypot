"""B1 — LIVE TTS audio path: the /audio/{seq} endpoint serves real synthesized
bytes, caches them (no re-paying the provider), and degrades to browser-speech
marks if synthesis fails. Zero network — a fake adapter stands in for ElevenLabs."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.infiltrate.service import get_tts_adapter
from app.infiltrate.voice import (
    TTSResult,
    VoiceMarkTTSAdapter,
    reset_audio_cache,
    synthesize_line,
)
from app.main import app
from tests.conftest import bearer

client = TestClient(app)
client.headers.update(bearer())


class _FakeLiveTTS:
    data_mode = "live"
    provider = "elevenlabs"
    calls = 0

    async def synthesize(self, text: str, voice: str = "persona") -> TTSResult:
        _FakeLiveTTS.calls += 1
        return TTSResult(
            provider=self.provider, voice=voice, text=text,
            duration_seconds=1.0, audio_bytes=b"ID3\x03fake-mp3-bytes",
            mime_type="audio/mpeg",
        )


class _FailingLiveTTS:
    data_mode = "live"
    provider = "elevenlabs"

    async def synthesize(self, text: str, voice: str = "persona") -> TTSResult:
        raise httpx.HTTPStatusError("401", request=None, response=None)


@pytest.fixture(autouse=True)
def _clean():
    reset_audio_cache()
    _FakeLiveTTS.calls = 0
    yield
    app.dependency_overrides.pop(get_tts_adapter, None)
    reset_audio_cache()


def _start_voice() -> dict:
    r = client.post("/api/sessions", json={"channel_type": "voice"})
    assert r.status_code in (200, 201), r.text
    return r.json()


def _first_voice_seq(session_id: str) -> int:
    msgs = client.get(f"/api/sessions/{session_id}/messages").json()
    return msgs[0]["seq"]


# --------------------------------------------------------------------------- #
# synthesize_line — caching (unit)
# --------------------------------------------------------------------------- #


async def test_synthesize_line_caches_live_bytes():
    tts = _FakeLiveTTS()
    r1 = await synthesize_line(tts, "halo bu, ini dari OJK", "persona")
    r2 = await synthesize_line(tts, "halo bu, ini dari OJK", "persona")
    assert r1.audio_bytes == r2.audio_bytes
    assert _FakeLiveTTS.calls == 1  # second call served from cache
    # a different line (or voice) is a distinct key → a real call
    await synthesize_line(tts, "teks berbeda", "persona")
    await synthesize_line(tts, "halo bu, ini dari OJK", "scammer")
    assert _FakeLiveTTS.calls == 3


async def test_synthesize_line_passes_poc_through_uncached():
    poc = VoiceMarkTTSAdapter()
    r = await synthesize_line(poc, "halo", "persona")
    assert r.audio_bytes is None and r.audio_url is None  # marks, no bytes


# --------------------------------------------------------------------------- #
# /audio/{seq} — serves bytes, caches, degrades (API)
# --------------------------------------------------------------------------- #


def test_audio_endpoint_streams_live_bytes_and_caches():
    app.dependency_overrides[get_tts_adapter] = lambda: _FakeLiveTTS()
    s = _start_voice()
    seq = _first_voice_seq(s["id"])

    r = client.get(f"/api/sessions/{s['id']}/audio/{seq}")
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.headers["x-tts-provider"] == "elevenlabs"
    assert r.content == b"ID3\x03fake-mp3-bytes"
    assert _FakeLiveTTS.calls == 1

    # re-fetch the same line → cache hit, no second provider call
    r2 = client.get(f"/api/sessions/{s['id']}/audio/{seq}")
    assert r2.status_code == 200 and r2.content == r.content
    assert _FakeLiveTTS.calls == 1


def test_audio_endpoint_degrades_to_marks_on_synth_failure():
    app.dependency_overrides[get_tts_adapter] = lambda: _FailingLiveTTS()
    s = _start_voice()
    seq = _first_voice_seq(s["id"])

    r = client.get(f"/api/sessions/{s['id']}/audio/{seq}")
    # the call never breaks: falls back to voice marks so the browser speaks it
    assert r.status_code == 200
    assert "json" in r.headers["content-type"]
    mark = r.json()
    assert mark["audio_url"] is None
    assert mark["seq"] == seq
    assert mark["duration_seconds"] > 0
