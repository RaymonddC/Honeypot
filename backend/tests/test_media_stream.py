"""Twilio Media Streams — codec, frame parsing, and turn-taking.

These are the parts of phase 5 that can be proven WITHOUT a carrier. The live
media loop cannot: end-to-end latency and barge-in against real speech need a
real call, and `docs/Live-Voice-Calls.md` is explicit that those are the actual
blockers. What is tested here is everything with an exact answer.

The codec matters most. Getting μ-law wrong produces audio that is *almost*
right, which down a phone line sounds like static and gets blamed on the
carrier — expensive to diagnose live, trivial to catch here.
"""

from __future__ import annotations

import base64
import json
import struct

import pytest

from app.infiltrate.media_stream import (
    BYTES_PER_CHUNK,
    SAMPLE_RATE_HZ,
    Event,
    Turn,
    TurnTaker,
    chunk_pcm16,
    clear_frame,
    mark_frame,
    media_frame,
    mulaw_to_pcm16,
    parse_frame,
    pcm16_to_mulaw,
    resample_pcm16,
    rms,
)

# `audioop` is the reference implementation and was REMOVED in Python 3.13. The
# app runs on 3.13, which is exactly why the codec here is hand-written — but
# wherever the stdlib is still present it is the oracle, so the local version is
# checked against it rather than against its own assumptions.
try:  # pragma: no cover - availability is the point
    import audioop  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    audioop = None  # type: ignore[assignment]


def _tone(samples: int, amplitude: int = 8000, period: int = 40) -> bytes:
    """Deterministic PCM16 that exercises sign, magnitude and zero crossings."""
    import math

    out = bytearray()
    for n in range(samples):
        value = int(amplitude * math.sin(2 * math.pi * n / period))
        out += struct.pack("<h", value)
    return bytes(out)


# --------------------------------------------------------------------------- #
# Codec — checked against the stdlib where it exists
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(audioop is None, reason="audioop removed in this Python")
def test_mulaw_decode_matches_the_stdlib_byte_for_byte():
    """Every one of the 256 μ-law values, not a sample of them. The table is
    small enough to check exhaustively, so there is no reason not to."""
    payload = bytes(range(256))
    assert mulaw_to_pcm16(payload) == audioop.ulaw2lin(payload, 2)


@pytest.mark.skipif(audioop is None, reason="audioop removed in this Python")
def test_encode_matches_the_stdlib_for_EVERY_pcm16_value():
    """All 65536 inputs, not a sample of them.

    A sampled test nearly shipped a real defect. The obvious 16-bit formulation
    of G.711 agrees with the stdlib almost everywhere and differs by one in the
    last bit at the smallest magnitudes; a tone-based check passed happily and
    only an extremes case caught it. Exhaustive costs a fraction of a second
    here and leaves nowhere for that class of bug to hide.
    """
    data = b"".join(struct.pack("<h", v) for v in range(-32768, 32768))
    mismatches = [
        value
        for value, (mine, ref) in zip(
            range(-32768, 32768),
            zip(pcm16_to_mulaw(data), audioop.lin2ulaw(data, 2)),
        )
        if mine != ref
    ]
    assert not mismatches, (
        f"{len(mismatches)} PCM values encode differently from the stdlib "
        f"reference; first few: {mismatches[:8]}"
    )


def test_a_round_trip_preserves_the_signal_approximately():
    """μ-law is lossy by design — 8 bits standing in for 16 — so this asserts
    the error stays small rather than zero. A sign or bias error would show up
    here as an enormous deviation even though the shape looked plausible."""
    original = _tone(800, amplitude=12000)
    restored = mulaw_to_pcm16(pcm16_to_mulaw(original))
    assert len(restored) == len(original)

    pairs = [
        (
            struct.unpack_from("<h", original, i)[0],
            struct.unpack_from("<h", restored, i)[0],
        )
        for i in range(0, len(original), 2)
    ]
    worst = max(abs(a - b) for a, b in pairs)
    assert worst < 400, f"μ-law round trip deviated by {worst}, far beyond quantisation"
    assert all((a >= 0) == (b >= 0) or abs(a) < 200 for a, b in pairs), (
        "sign flipped on a sample — the classic μ-law bug"
    )


# --------------------------------------------------------------------------- #
# Resampling
# --------------------------------------------------------------------------- #


def test_downsampling_shortens_by_the_right_ratio():
    """24 kHz TTS into an 8 kHz carrier. Skipping this does not error — it plays
    at three times the speed, which is a bug that survives review."""
    pcm = _tone(2400)  # 2400 samples @ 24 kHz = 100 ms
    out = resample_pcm16(pcm, 24000, 8000)
    assert len(out) // 2 == 800, "100 ms at 8 kHz must be 800 samples"


def test_resampling_is_a_no_op_at_the_same_rate():
    pcm = _tone(160)
    assert resample_pcm16(pcm, 8000, 8000) == pcm


def test_downsampling_averages_rather_than_picking():
    """Naive decimation aliases — energy above the new Nyquist folds back as
    tones that were never in the speech. Averaging is a crude low-pass; picking
    every Nth sample is none at all.

    Constructed so the two strategies cannot agree: alternating +A/-A averages
    to ~0, while picking always lands on +A.
    """
    alternating = b"".join(
        struct.pack("<h", 10000 if n % 2 == 0 else -10000) for n in range(160)
    )
    out = resample_pcm16(alternating, 16000, 8000)
    peak = max(abs(struct.unpack_from("<h", out, i)[0]) for i in range(0, len(out), 2))
    assert peak < 1000, (
        f"downsampling preserved a {peak} peak from an alternating signal — it is "
        "picking samples, not averaging, and will alias on real speech"
    )


# --------------------------------------------------------------------------- #
# Frame parsing
# --------------------------------------------------------------------------- #


def test_start_frame_yields_the_identifiers_the_call_is_tracked_by():
    frame = parse_frame(json.dumps({
        "event": "start",
        "streamSid": "MZ123",
        "start": {"callSid": "CA456", "streamSid": "MZ123"},
    }))
    assert frame is not None
    assert frame.event is Event.START
    assert frame.stream_sid == "MZ123"
    assert frame.call_sid == "CA456"


def test_media_frame_is_decoded_all_the_way_to_pcm():
    """The caller of this should never see base64 or μ-law — an STT engine
    wants PCM16, and leaving the conversion to each call site is how one of
    them forgets."""
    mulaw = pcm16_to_mulaw(_tone(160))
    frame = parse_frame(json.dumps({
        "event": "media",
        "streamSid": "MZ1",
        "media": {"payload": base64.b64encode(mulaw).decode(), "timestamp": "340"},
    }))
    assert frame is not None and frame.event is Event.MEDIA
    assert frame.audio == mulaw_to_pcm16(mulaw)
    assert frame.timestamp_ms == 340


def test_a_malformed_frame_never_raises():
    """A bad frame mid-call must not end the call. Staying on the line IS the
    product — a honeypot that drops on one corrupt packet has failed."""
    for bad in ["", "not json", "[]", '{"event":', b"\xff\xfe", '{"event": "media"}']:
        parse_frame(bad)  # must not raise


def test_an_unknown_event_is_reported_rather_than_dropped():
    """Twilio adds event types. An unrecognised one is information, not an
    error — silently discarding it hides a protocol change until something
    downstream behaves oddly for reasons nobody can trace."""
    frame = parse_frame(json.dumps({"event": "someNewThing", "streamSid": "MZ1"}))
    assert frame is not None
    assert frame.event is None
    assert frame.unknown_event == "someNewThing"


def test_undecodable_audio_yields_silence_not_a_crash():
    frame = parse_frame(json.dumps({
        "event": "media", "streamSid": "MZ1", "media": {"payload": "!!!not base64!!!"},
    }))
    assert frame is not None and frame.audio == b""


# --------------------------------------------------------------------------- #
# Outbound frames
# --------------------------------------------------------------------------- #


def test_outbound_media_carries_the_stream_sid_and_encoded_audio():
    payload = json.loads(media_frame("MZ9", _tone(160)))
    assert payload["event"] == "media"
    assert payload["streamSid"] == "MZ9"
    assert base64.b64decode(payload["media"]["payload"])


def test_outbound_media_resamples_from_the_tts_rate():
    """A TTS provider returning 24 kHz must not be sent as-is."""
    at_24k = _tone(2400)
    payload = json.loads(media_frame("MZ9", at_24k, source_hz=24000))
    assert len(base64.b64decode(payload["media"]["payload"])) == 800


def test_utterances_are_chunked_so_they_can_be_interrupted():
    """One big frame is one big commitment: `clear` can only drop what has not
    been handed over, so a whole utterance in a single frame is
    un-interruptible and the persona talks over people."""
    chunks = chunk_pcm16(_tone(SAMPLE_RATE_HZ))  # one second
    assert len(chunks) > 10
    assert all(len(c) <= BYTES_PER_CHUNK * 2 for c in chunks)


def test_clear_and_mark_are_well_formed():
    assert json.loads(clear_frame("MZ1")) == {"event": "clear", "streamSid": "MZ1"}
    assert json.loads(mark_frame("MZ1", "reply-3"))["mark"]["name"] == "reply-3"


# --------------------------------------------------------------------------- #
# Turn-taking
# --------------------------------------------------------------------------- #


def _loud(ms: int) -> bytes:
    return _tone(SAMPLE_RATE_HZ * ms // 1000, amplitude=20000)


def _quiet(ms: int) -> bytes:
    return b"\x00\x00" * (SAMPLE_RATE_HZ * ms // 1000)


def test_silence_never_counts_as_an_interruption():
    t = TurnTaker()
    t.begin_speaking()
    for _ in range(50):
        assert t.observe(_quiet(20)) is False
    assert t.state is Turn.SPEAKING


def test_sustained_speech_takes_the_floor():
    t = TurnTaker(barge_in_ms=100, echo_guard_ms=0)
    t.begin_speaking()
    barged = any(t.observe(_loud(20)) for _ in range(10))
    assert barged, "the caller spoke over the persona and was ignored"
    assert t.state is Turn.LISTENING


def test_a_brief_noise_does_not_take_the_floor():
    """A cough or a line click must not stop the persona mid-word. This is the
    other failure mode, and it is just as bad as never yielding."""
    t = TurnTaker(barge_in_ms=240, echo_guard_ms=0)
    t.begin_speaking()
    assert t.observe(_loud(20)) is False
    assert t.observe(_loud(20)) is False
    assert t.observe(_quiet(20)) is False   # noise stops; the counter must reset
    for _ in range(5):
        t.observe(_quiet(20))
    assert t.state is Turn.SPEAKING


def test_the_echo_guard_stops_the_persona_interrupting_itself():
    """Our own audio leaks back through the carrier's echo path. Without a
    guard it reads as the caller talking and the persona cuts itself off on its
    own first syllable."""
    t = TurnTaker(barge_in_ms=40, echo_guard_ms=200)
    t.begin_speaking()
    early = [t.observe(_loud(20)) for _ in range(9)]  # 180 ms — inside the guard
    assert not any(early), "the persona interrupted itself on its own echo"


def test_nothing_can_be_interrupted_while_listening():
    """There is no floor to take. A caller speaking while we listen is simply
    the conversation working."""
    t = TurnTaker(barge_in_ms=20, echo_guard_ms=0)
    assert t.state is Turn.LISTENING
    assert not any(t.observe(_loud(20)) for _ in range(10))


def test_the_floor_returns_only_when_twilio_says_the_audio_played():
    """Not on a timer. Playback is buffered on Twilio's side, so wall-clock
    timing says the persona has finished while it is still audibly talking."""
    t = TurnTaker()
    t.begin_speaking()
    assert t.state is Turn.SPEAKING
    t.finished_speaking()
    assert t.state is Turn.LISTENING


def test_rms_distinguishes_speech_from_silence():
    assert rms(_quiet(20)) == 0
    assert rms(_loud(20)) > 1000
