"""B1 — LIVE TTS audio path: the /audio/{seq} endpoint serves real synthesized
bytes, caches them (no re-paying the provider), and degrades to browser-speech
marks if synthesis fails. Zero network — a fake adapter stands in for ElevenLabs."""

import base64

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings
from app.infiltrate.service import get_tts_adapter
from app.infiltrate.voice import (
    LIVE_TTS_PROVIDERS,
    ElevenLabsTTSAdapter,
    GeminiTTSAdapter,
    TTSResult,
    VoiceMarkTTSAdapter,
    check_elevenlabs_voice,
    reset_audio_cache,
    list_elevenlabs_voices,
    resolve_tts_adapter,
    select_live_tts_adapter,
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


# --------------------------------------------------------------------------- #
# Gemini TTS adapter — PCM→WAV, style prompt, fail-loud, factory (httpx mocked)
# --------------------------------------------------------------------------- #


class _FakeGeminiHttpx:
    last_json: dict | None = None
    pcm = b""

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def post(self, url, headers=None, json=None, **k):
        _FakeGeminiHttpx.last_json = json
        payload = {
            "candidates": [
                {"content": {"parts": [{"inlineData": {
                    "mimeType": "audio/L16;codec=pcm;rate=24000",
                    "data": base64.b64encode(_FakeGeminiHttpx.pcm).decode(),
                }}]}}
            ]
        }
        return httpx.Response(200, json=payload, request=httpx.Request("POST", url))


async def test_gemini_wraps_pcm_as_playable_wav(monkeypatch):
    monkeypatch.setattr("app.infiltrate.voice.httpx.AsyncClient", _FakeGeminiHttpx)
    _FakeGeminiHttpx.pcm = b"\x11\x22\x33\x44" * 20

    r = await GeminiTTSAdapter(Settings(gemini_api_key="k")).synthesize("halo bu", "persona")

    assert r.mime_type == "audio/wav"
    assert r.audio_bytes[:4] == b"RIFF" and r.audio_bytes[8:12] == b"WAVE"
    assert _FakeGeminiHttpx.pcm in r.audio_bytes  # PCM payload preserved under the header

    sent = _FakeGeminiHttpx.last_json
    # persona style directive is prepended (Gemini follows it, doesn't read it aloud)
    assert "nenek" in sent["contents"][0]["parts"][0]["text"]
    voice = sent["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]
    assert voice["voiceName"] == "Sulafat"


def test_gemini_fails_loud_without_key():
    with pytest.raises(NotImplementedError, match="ITTU_GEMINI_API_KEY"):
        GeminiTTSAdapter(Settings(gemini_api_key=""))


def test_live_factory_selects_gemini():
    tts = select_live_tts_adapter(Settings(tts_provider="gemini", gemini_api_key="k"))
    assert tts.provider == "gemini"


def test_elevenlabs_reads_model_and_voices_from_settings():
    a = ElevenLabsTTSAdapter(
        Settings(
            elevenlabs_api_key="k",
            elevenlabs_model="eleven_flash_v2_5",
            elevenlabs_voice_persona="Voice-P",
            elevenlabs_voice_scammer="Voice-S",
        )
    )
    assert a._model == "eleven_flash_v2_5"
    assert a._voice_ids == {"persona": "Voice-P", "scammer": "Voice-S"}


class _FakeVoicesHttpx:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def get(self, url, headers=None, **k):
        return httpx.Response(
            200,
            json={"voices": [
                {"voice_id": "v1", "name": "Rachel"},
                {"voice_id": "v2", "name": "Adam"},
            ]},
            request=httpx.Request("GET", url),
        )


async def test_list_elevenlabs_voices_maps_id_and_name(monkeypatch):
    monkeypatch.setattr("app.infiltrate.voice.httpx.AsyncClient", _FakeVoicesHttpx)
    voices = await list_elevenlabs_voices(Settings(elevenlabs_api_key="k"))
    assert voices == [{"id": "v1", "name": "Rachel"}, {"id": "v2", "name": "Adam"}]


async def test_list_elevenlabs_voices_empty_without_key():
    assert await list_elevenlabs_voices(Settings(elevenlabs_api_key="")) == []


def test_audio_endpoint_applies_voice_overrides(monkeypatch):
    """?model=&voice_persona= reach the adapter via a Settings copy — and the
    cached settings singleton is never mutated (model_copy, not assignment)."""
    recorded: dict[str, str] = {}

    class _FakeEleven:
        data_mode = "live"
        provider = "elevenlabs"

        def __init__(self, settings):
            # Mirror the real adapter so the audio cache signature distinguishes
            # a voice-override request from a plain one.
            self._model = settings.elevenlabs_model
            self._voice_ids = {
                "persona": settings.elevenlabs_voice_persona,
                "scammer": settings.elevenlabs_voice_scammer,
            }
            recorded["model"] = self._model
            recorded["voice_persona"] = self._voice_ids["persona"]

        async def synthesize(self, text: str, voice: str = "persona") -> TTSResult:
            return TTSResult(
                provider=self.provider, voice=voice, text=text,
                duration_seconds=1.0, audio_bytes=b"OVR-bytes", mime_type="audio/mpeg",
            )

    monkeypatch.setitem(LIVE_TTS_PROVIDERS, "elevenlabs", _FakeEleven)
    env_default = get_settings().elevenlabs_model

    s = _start_voice()
    seq = _first_voice_seq(s["id"])

    r = client.get(
        f"/api/sessions/{s['id']}/audio/{seq}"
        "?provider=elevenlabs&model=MDL-X&voice_persona=VP-1"
    )
    assert r.status_code == 200 and r.content == b"OVR-bytes"
    assert recorded["model"] == "MDL-X"
    assert recorded["voice_persona"] == "VP-1"
    # the lru_cached settings singleton is untouched — overrides use model_copy
    assert get_settings().elevenlabs_model == env_default

    # a request WITHOUT overrides uses the unmodified env settings
    r2 = client.get(f"/api/sessions/{s['id']}/audio/{seq}?provider=elevenlabs")
    assert r2.status_code == 200
    assert recorded["model"] == env_default


# --------------------------------------------------------------------------- #
# Per-request provider override — A/B from the portal, no backend restart
# --------------------------------------------------------------------------- #


class _UnkeyedTTS:
    """A LIVE provider whose key is unset — raises at construction (like an
    unkeyed GeminiTTSAdapter), so the endpoint must degrade to marks."""

    provider = "gemini"

    def __init__(self, settings=None):
        raise NotImplementedError("no key")


class _FakeSelectableTTS:
    data_mode = "live"
    provider = "gemini"

    def __init__(self, settings=None):
        pass

    async def synthesize(self, text: str, voice: str = "persona") -> TTSResult:
        return TTSResult(
            provider=self.provider, voice=voice, text=text,
            duration_seconds=1.0, audio_bytes=b"FAKEGEMINIBYTES", mime_type="audio/mpeg",
        )


def test_provider_override_browser_returns_marks():
    app.dependency_overrides[get_tts_adapter] = lambda: VoiceMarkTTSAdapter()
    s = _start_voice()
    seq = _first_voice_seq(s["id"])
    r = client.get(f"/api/sessions/{s['id']}/audio/{seq}", params={"provider": "browser"})
    assert r.status_code == 200
    assert "json" in r.headers["content-type"]
    assert r.json()["audio_url"] is None


def test_provider_override_unkeyed_degrades_to_marks(monkeypatch):
    app.dependency_overrides[get_tts_adapter] = lambda: VoiceMarkTTSAdapter()
    monkeypatch.setitem(LIVE_TTS_PROVIDERS, "gemini", _UnkeyedTTS)
    s = _start_voice()
    seq = _first_voice_seq(s["id"])
    r = client.get(f"/api/sessions/{s['id']}/audio/{seq}", params={"provider": "gemini"})
    assert r.status_code == 200  # a bad/unkeyed override never 500s — degrades
    assert "json" in r.headers["content-type"]
    assert r.json()["audio_url"] is None


def test_provider_override_selects_registered_adapter(monkeypatch):
    app.dependency_overrides[get_tts_adapter] = lambda: VoiceMarkTTSAdapter()
    monkeypatch.setitem(LIVE_TTS_PROVIDERS, "gemini", _FakeSelectableTTS)
    s = _start_voice()
    seq = _first_voice_seq(s["id"])

    # ?provider=gemini → the fake gemini bytes, not the env default
    r = client.get(f"/api/sessions/{s['id']}/audio/{seq}", params={"provider": "gemini"})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert r.headers["x-tts-provider"] == "gemini"
    assert r.content == b"FAKEGEMINIBYTES"

    # no param → env default (POC marks) unchanged (backward-compatible)
    r2 = client.get(f"/api/sessions/{s['id']}/audio/{seq}")
    assert "json" in r2.headers["content-type"]
    assert r2.json()["audio_url"] is None


def test_resolve_tts_adapter_routing():
    d = VoiceMarkTTSAdapter()
    assert resolve_tts_adapter(None, default=d) is d        # no override → default
    assert resolve_tts_adapter("nope", default=d) is d      # unknown → default
    browser = resolve_tts_adapter("browser", default=d)     # browser → fresh marks
    assert isinstance(browser, VoiceMarkTTSAdapter) and browser is not d


# --------------------------------------------------------------------------- #
# check_elevenlabs_voice — test-synth validation (works with a TTS-scoped key)
# --------------------------------------------------------------------------- #


class _FakeElevenHttpx:
    status = 200

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def post(self, url, **k):
        return httpx.Response(
            _FakeElevenHttpx.status, content=b"audio", request=httpx.Request("POST", url)
        )


async def test_check_elevenlabs_voice_ok(monkeypatch):
    monkeypatch.setattr("app.infiltrate.voice.httpx.AsyncClient", _FakeElevenHttpx)
    _FakeElevenHttpx.status = 200
    assert await check_elevenlabs_voice("v1", Settings(elevenlabs_api_key="k")) == {"ok": True}


async def test_check_elevenlabs_voice_bad_id(monkeypatch):
    monkeypatch.setattr("app.infiltrate.voice.httpx.AsyncClient", _FakeElevenHttpx)
    _FakeElevenHttpx.status = 404
    res = await check_elevenlabs_voice("bad", Settings(elevenlabs_api_key="k"))
    assert res == {"ok": False, "status": 404, "error": "http_404"}


async def test_check_elevenlabs_voice_no_key():
    assert await check_elevenlabs_voice("v1", Settings(elevenlabs_api_key="")) == {
        "ok": False,
        "error": "no_key",
    }
