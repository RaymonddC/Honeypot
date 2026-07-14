"""LIVE ElevenLabs TTS adapter — synthesis, headers, key-secrecy (zero network)."""

import pytest

from app.core.config import Settings
from app.infiltrate.voice import ElevenLabsTTSAdapter


class _FakeResponse:
    def __init__(self, content: bytes, status_code: int = 200) -> None:
        self.content = content
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _FakeAsyncClient:
    """Records the request it was given; returns scripted fake audio bytes."""

    calls: list[dict] = []
    response: _FakeResponse | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def post(self, url: str, params=None, headers=None, json=None, **kwargs):
        _FakeAsyncClient.calls.append(
            {"url": url, "params": params, "headers": headers, "json": json}
        )
        return _FakeAsyncClient.response


@pytest.fixture(autouse=True)
def _reset_fake_client():
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = _FakeResponse(b"fake-mp3-bytes")
    yield


def _adapter(monkeypatch, api_key: str = "xi-test-key-123") -> ElevenLabsTTSAdapter:
    monkeypatch.setattr("app.infiltrate.voice.httpx.AsyncClient", _FakeAsyncClient)
    settings = Settings(elevenlabs_api_key=api_key)
    return ElevenLabsTTSAdapter(settings)


async def test_synthesize_returns_audio_bytes_and_mime_type(monkeypatch):
    adapter = _adapter(monkeypatch)

    result = await adapter.synthesize("halo, selamat siang", voice="persona")

    assert result.audio_bytes == b"fake-mp3-bytes"
    assert result.mime_type == "audio/mpeg"
    assert result.provider == "elevenlabs"
    assert result.text == "halo, selamat siang"


async def test_synthesize_maps_persona_voice_to_rachel(monkeypatch):
    adapter = _adapter(monkeypatch)
    await adapter.synthesize("hi", voice="persona")
    call = _FakeAsyncClient.calls[0]
    assert call["url"].endswith("/v1/text-to-speech/21m00Tcm4TlvDq8ikWAM")


async def test_synthesize_maps_scammer_voice_to_adam(monkeypatch):
    adapter = _adapter(monkeypatch)
    await adapter.synthesize("hi", voice="scammer")
    call = _FakeAsyncClient.calls[0]
    assert call["url"].endswith("/v1/text-to-speech/pNInz6obpgDQGcFmaJgB")


async def test_synthesize_sends_api_key_header(monkeypatch):
    adapter = _adapter(monkeypatch, api_key="xi-secret-abc")
    await adapter.synthesize("hi", voice="persona")
    call = _FakeAsyncClient.calls[0]
    assert call["headers"]["xi-api-key"] == "xi-secret-abc"


async def test_api_key_never_appears_in_result(monkeypatch):
    adapter = _adapter(monkeypatch, api_key="xi-super-secret-key")
    result = await adapter.synthesize("hi", voice="persona")
    dumped = result.model_dump()
    assert "xi-super-secret-key" not in str(dumped)


async def test_synthesize_sends_output_format_and_voice_settings(monkeypatch):
    adapter = _adapter(monkeypatch)
    await adapter.synthesize("hi", voice="persona")
    call = _FakeAsyncClient.calls[0]
    assert call["params"] == {"output_format": "mp3_44100_128"}
    assert call["json"]["model_id"] == "eleven_multilingual_v2"
    assert "voice_settings" in call["json"]
    assert "stability" in call["json"]["voice_settings"]
    assert "similarity_boost" in call["json"]["voice_settings"]


def test_construction_without_key_raises_not_implemented(monkeypatch):
    settings = Settings(elevenlabs_api_key="")
    with pytest.raises(NotImplementedError, match="ITTU_ELEVENLABS_API_KEY"):
        ElevenLabsTTSAdapter(settings)
