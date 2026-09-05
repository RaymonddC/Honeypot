"""The media bridge — a whole call, driven by scripted frames.

Everything interesting about a live call is logic: when an utterance ends, what
happens when the caller talks over the persona, what happens when a provider
returns the wrong audio format. Logic tested only against a real phone call is
logic tested once, so the bridge is written against a socket-shaped protocol and
driven here with frames.

What these CANNOT prove is latency — whether the reply arrives before the caller
gives up. That needs a real call, and `docs/Live-Voice-Calls.md` is right that it
is the actual blocker.
"""

from __future__ import annotations

import base64
import json
import struct

import pytest

from app.infiltrate.bridge import (
    END_OF_UTTERANCE_MS,
    MIN_UTTERANCE_MS,
    MediaBridge,
    pcm_from_tts,
)
from app.infiltrate.media_stream import CHUNK_MS, SAMPLE_RATE_HZ, TurnTaker, pcm16_to_mulaw


def _pcm(ms: int, amplitude: int) -> bytes:
    import math

    n = SAMPLE_RATE_HZ * ms // 1000
    return b"".join(
        struct.pack("<h", int(amplitude * math.sin(2 * math.pi * i / 40))) for i in range(n)
    )


def _media(ms: int = CHUNK_MS, *, loud: bool = True) -> str:
    payload = pcm16_to_mulaw(_pcm(ms, 20000 if loud else 0))
    return json.dumps({
        "event": "media", "streamSid": "MZ1",
        "media": {"payload": base64.b64encode(payload).decode()},
    })


START = json.dumps({"event": "start", "streamSid": "MZ1", "start": {"callSid": "CA1"}})
STOP = json.dumps({"event": "stop", "streamSid": "MZ1"})


class FakeSocket:
    """Scripted inbound frames; records what the bridge writes back."""

    def __init__(self, inbound: list[str]) -> None:
        self._inbound = list(inbound)
        self.sent: list[dict] = []

    async def receive_text(self) -> str:
        if not self._inbound:
            raise ConnectionError("closed")
        return self._inbound.pop(0)

    async def send_text(self, data: str) -> None:
        self.sent.append(json.loads(data))

    def events(self) -> list[str]:
        return [m.get("event") for m in self.sent]


def _bridge(**kw):
    async def transcribe(_audio):
        return kw.get("text", "halo pak")

    async def reply(_sid, _text):
        return kw.get("answer", "iya, saya dengar")

    async def synthesize(_text):
        return _pcm(200, 12000), SAMPLE_RATE_HZ

    async def on_start(call_sid):
        return f"sess-{call_sid}"

    return MediaBridge(
        transcribe=kw.get("transcribe", transcribe),
        reply=kw.get("reply", reply),
        synthesize=kw.get("synthesize", synthesize),
        on_start=on_start,
        turn_taker=kw.get("turn_taker"),
    )


def _run(coro):
    import asyncio

    return asyncio.run(coro)


# --------------------------------------------------------------------------- #
# A conversation happens
# --------------------------------------------------------------------------- #


def test_a_call_produces_a_spoken_reply():
    silence = [_media(loud=False) for _ in range(END_OF_UTTERANCE_MS // CHUNK_MS + 2)]
    speech = [_media() for _ in range(30)]  # 600 ms
    sock = FakeSocket([START, *speech, *silence, STOP])

    state = _run(_bridge().handle(sock))

    assert state.call_sid == "CA1"
    assert state.session_id == "sess-CA1", "the call was not linked to a session"
    assert state.turns == 1
    assert "media" in sock.events(), "the persona never spoke"
    assert "mark" in sock.events(), (
        "no mark was sent — the bridge would never learn when playback finished "
        "and would hold the floor forever"
    )


def test_a_too_short_noise_is_not_a_turn():
    """A cough or a door must not cost an LLM call and a second of patience."""
    short = [_media() for _ in range(MIN_UTTERANCE_MS // CHUNK_MS - 3)]
    silence = [_media(loud=False) for _ in range(END_OF_UTTERANCE_MS // CHUNK_MS + 2)]
    sock = FakeSocket([START, *short, *silence, STOP])

    assert _run(_bridge().handle(sock)).turns == 0
    assert "media" not in sock.events()


def test_silence_alone_never_starts_a_turn():
    sock = FakeSocket([START, *[_media(loud=False) for _ in range(100)], STOP])
    assert _run(_bridge().handle(sock)).turns == 0


# --------------------------------------------------------------------------- #
# Interruption
# --------------------------------------------------------------------------- #


def test_the_caller_can_cut_the_persona_off():
    """`clear` is what makes barge-in real. Without it the persona keeps talking
    for as long as its buffered reply lasts — several seconds, which is exactly
    when a scammer hangs up."""
    speech = [_media() for _ in range(30)]
    silence = [_media(loud=False) for _ in range(END_OF_UTTERANCE_MS // CHUNK_MS + 2)]
    interruption = [_media() for _ in range(20)]
    sock = FakeSocket([START, *speech, *silence, *interruption, STOP])

    _run(_bridge(turn_taker=TurnTaker(barge_in_ms=100, echo_guard_ms=0)).handle(sock))

    assert "clear" in sock.events(), (
        "the caller spoke over the persona and nothing was cleared — the queued "
        "reply would keep playing over them"
    )


def test_the_persona_does_not_interrupt_itself_on_its_own_echo():
    """Our audio leaks back through the carrier. Without the echo guard the
    persona cuts itself off on its own first syllable."""
    speech = [_media() for _ in range(30)]
    silence = [_media(loud=False) for _ in range(END_OF_UTTERANCE_MS // CHUNK_MS + 2)]
    echo = [_media() for _ in range(4)]  # 80 ms, inside a 200 ms guard
    sock = FakeSocket([START, *speech, *silence, *echo, STOP])

    _run(_bridge(turn_taker=TurnTaker(barge_in_ms=40, echo_guard_ms=200)).handle(sock))
    assert "clear" not in sock.events()


# --------------------------------------------------------------------------- #
# Staying on the line
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("failing", ["transcribe", "reply", "synthesize"])
def test_a_provider_failure_does_not_drop_the_call(failing):
    """Staying on the line IS the product. A failed turn is a missed sentence;
    a dropped call is a lost source."""
    async def boom(*_args):
        raise RuntimeError("provider down")

    speech = [_media() for _ in range(30)]
    silence = [_media(loud=False) for _ in range(END_OF_UTTERANCE_MS // CHUNK_MS + 2)]
    sock = FakeSocket([START, *speech, *silence, _media(), STOP])

    state = _run(_bridge(**{failing: boom}).handle(sock))
    assert state.call_sid == "CA1", f"a failing {failing} ended the call"


def test_a_malformed_frame_mid_call_is_survivable():
    speech = [_media() for _ in range(30)]
    silence = [_media(loud=False) for _ in range(END_OF_UTTERANCE_MS // CHUNK_MS + 2)]
    sock = FakeSocket([START, "not json", *speech, '{"event":', *silence, STOP])
    assert _run(_bridge().handle(sock)).turns == 1


# --------------------------------------------------------------------------- #
# Audio format
# --------------------------------------------------------------------------- #


def test_mp3_is_refused_rather_than_streamed_as_noise():
    """MP3 bytes written to a media stream are full-scale STATIC, not a
    lower-quality voice. The caller hangs up on what sounds like a broken line,
    and the cause is invisible from the far end of a phone call."""
    with pytest.raises(ValueError) as exc:
        pcm_from_tts(b"\xff\xfb\x90fake mp3", "audio/mpeg")
    assert "pcm" in str(exc.value).lower()
    assert "ulaw_8000" in str(exc.value) or "LINEAR16" in str(exc.value), (
        "the error must name the fix, not just the problem"
    )


def test_pcm_is_accepted_with_its_declared_rate():
    audio, rate = pcm_from_tts(b"\x00\x01" * 100, "audio/L16;codec=pcm;rate=24000")
    assert rate == 24000 and audio
