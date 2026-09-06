"""Twilio Media Streams — the wire format, the codec, and who may speak.

Phase 5's carrier-independent half. Everything here is a pure function or a
state machine over data, so it is tested against synthetic frames rather than
against a phone call. What genuinely needs a carrier — end-to-end latency, real
audio quality, barge-in against actual speech — is the WebSocket endpoint that
drives these pieces, not the pieces themselves.

That split matters. ``telephony.py`` argues that "a plausible-looking untested
media bridge is worse than none", and it is right about the media LOOP. It is
not right about μ-law decoding or frame parsing: those have exact answers, and
getting them wrong produces audio that sounds like static — a failure that is
expensive to diagnose down a phone line and trivial to catch in a unit test.

## The wire format

Twilio opens a WebSocket to us and sends JSON text frames, each with an
``event``:

* ``connected`` — handshake; no media yet.
* ``start`` — carries ``streamSid``, the ``callSid``, and the media format.
  Twilio sends ``audio/x-mulaw`` at 8000 Hz, mono. Assume nothing else: the
  format is stated in this frame precisely because it can differ.
* ``media`` — one ~20 ms chunk, base64 μ-law, with a monotonically increasing
  ``chunk`` counter and a ``timestamp`` in ms since the stream started.
* ``stop`` — the call ended.
* ``mark`` — echoed back to us after audio WE sent finishes playing. This is the
  only reliable "the persona has stopped talking" signal; wall-clock timing is
  not, because playback is buffered on Twilio's side.

We send ``media`` frames back with the same ``streamSid``, plus ``mark`` to be
told when they land and ``clear`` to abandon anything still queued — which is
what makes barge-in possible at all.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from enum import Enum

#: Twilio's PSTN media format. Not configurable — it is what the carrier sends.
SAMPLE_RATE_HZ = 8000
CHUNK_MS = 20
BYTES_PER_CHUNK = SAMPLE_RATE_HZ * CHUNK_MS // 1000  # 160 bytes of μ-law


# --------------------------------------------------------------------------- #
# Codec
# --------------------------------------------------------------------------- #


# G.711 μ-law, implemented here rather than taken from ``audioop``.
#
# ``audioop`` was REMOVED in Python 3.13, and this app runs on 3.13 in
# production while the test venv is 3.12 — so importing it would pass every
# test here and crash on startup there, which is the worst shape of dependency
# bug. ``audioop-lts`` exists but installs only on 3.13+, so it cannot be
# exercised by these tests either.
#
# μ-law is a fixed, exact algorithm (ITU-T G.711), so a local implementation is
# not an approximation of anything — and `test_media_stream.py` checks it
# byte-for-byte against stdlib ``audioop`` wherever that is still importable,
# which makes the stdlib the oracle rather than the dependency.

_MULAW_BIAS = 0x84
_MULAW_CLIP = 32635

#: index → PCM16 value. 256 entries; built once.
_ULAW_DECODE: tuple[int, ...] = tuple(
    (lambda u: (
        (lambda sign, exponent, mantissa: (
            (lambda magnitude: -magnitude if sign else magnitude)(
                (((mantissa << 3) + _MULAW_BIAS) << exponent) - _MULAW_BIAS
            )
        ))(~u & 0x80, (~u >> 4) & 0x07, ~u & 0x0F)
    ))(byte)
    for byte in range(256)
)


def mulaw_to_pcm16(payload: bytes) -> bytes:
    """μ-law → 16-bit signed PCM (little-endian), what an STT engine expects."""
    out = bytearray(len(payload) * 2)
    for i, byte in enumerate(payload):
        value = _ULAW_DECODE[byte]
        out[2 * i] = value & 0xFF
        out[2 * i + 1] = (value >> 8) & 0xFF
    return bytes(out)


#: Segment ends for the 14-bit search, from G.711's reference encoder.
_SEG_UEND = (0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF, 0x1FFF)
_MULAW_CLIP_14 = 8159


def _encode_sample(sample: int) -> int:
    """One PCM16 sample → one μ-law byte, matching G.711's reference encoder.

    This is the FOURTEEN-bit formulation: the input is shifted down two bits and
    the bias scaled to match. The 16-bit variant is also valid G.711 and is what
    a first attempt naturally produces — it agrees everywhere except the
    smallest magnitudes, where it differs by one in the last bit. Inaudible, and
    still worth matching: ``audioop`` (which this replaces, because Python 3.13
    removed it) uses the 14-bit form, so matching it means swapping the
    implementation changed nothing at all, and the exhaustive test against the
    stdlib can assert equality rather than closeness.
    """
    sample >>= 2  # 16-bit → 14-bit, arithmetic
    if sample < 0:
        sample = -sample
        mask = 0x7F
    else:
        mask = 0xFF
    if sample > _MULAW_CLIP_14:
        sample = _MULAW_CLIP_14
    sample += _MULAW_BIAS >> 2

    for segment, end in enumerate(_SEG_UEND):
        if sample <= end:
            return ((segment << 4) | ((sample >> (segment + 1)) & 0x0F)) ^ mask
    return 0x7F ^ mask


def pcm16_to_mulaw(payload: bytes) -> bytes:
    """16-bit signed PCM → μ-law, what the carrier expects back."""
    out = bytearray(len(payload) // 2)
    for i in range(0, len(payload) - 1, 2):
        sample = int.from_bytes(payload[i : i + 2], "little", signed=True)
        out[i // 2] = _encode_sample(sample)
    return bytes(out)


def resample_pcm16(payload: bytes, from_hz: int, to_hz: int) -> bytes:
    """Resample mono PCM16. TTS providers return 16/22/24 kHz; the PSTN is 8 kHz.

    Sending 24 kHz audio to Twilio without resampling does not error — it plays
    at three times the speed, which is the kind of bug that survives review.

    Downsampling AVERAGES the samples it collapses rather than picking one of
    them. Naive decimation aliases: energy above the new Nyquist folds back down
    as tones that were never in the speech, and on a phone line that is heard as
    a metallic rasp and blamed on the carrier. A box average is a crude
    low-pass, not as good as ``audioop.ratecv``'s filter, and honest about it —
    at 8 kHz telephony bandwidth the difference is small, and correctness on the
    deployment's Python matters more here than the last decibel.
    """
    if from_hz == to_hz or not payload:
        return payload

    samples = [
        int.from_bytes(payload[i : i + 2], "little", signed=True)
        for i in range(0, len(payload) - 1, 2)
    ]
    out_len = max(1, round(len(samples) * to_hz / from_hz))
    ratio = len(samples) / out_len

    resampled: list[int] = []
    for n in range(out_len):
        start = int(n * ratio)
        end = max(start + 1, int((n + 1) * ratio))
        window = samples[start:end] or samples[start : start + 1]
        resampled.append(sum(window) // len(window))

    out = bytearray()
    for value in resampled:
        out += max(-32768, min(32767, value)).to_bytes(2, "little", signed=True)
    return bytes(out)


def rms(pcm16: bytes) -> int:
    """Loudness of a PCM16 chunk — the input to speech detection."""
    if len(pcm16) < 2:
        return 0
    total = 0
    count = 0
    for i in range(0, len(pcm16) - 1, 2):
        sample = int.from_bytes(pcm16[i : i + 2], "little", signed=True)
        total += sample * sample
        count += 1
    return int((total / count) ** 0.5) if count else 0


# --------------------------------------------------------------------------- #
# Inbound frames
# --------------------------------------------------------------------------- #


class Event(str, Enum):
    CONNECTED = "connected"
    START = "start"
    MEDIA = "media"
    STOP = "stop"
    MARK = "mark"


@dataclass(frozen=True)
class InboundFrame:
    """One decoded frame from Twilio. ``audio`` is PCM16, already converted."""

    event: Event | None
    stream_sid: str | None = None
    call_sid: str | None = None
    audio: bytes = b""
    timestamp_ms: int | None = None
    mark_name: str | None = None
    #: Set when the frame was structurally valid JSON but not something we
    #: understand. Kept rather than raised: an unrecognised event must not drop
    #: a call, and Twilio adds event types over time.
    unknown_event: str | None = None


def parse_frame(raw: str | bytes) -> InboundFrame | None:
    """Decode one Twilio frame. ``None`` when it is not usable JSON at all.

    Never raises. A malformed frame on a live call must not take the call down —
    the honeypot's whole value is staying on the line.
    """
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    raw_event = data.get("event")
    try:
        event = Event(raw_event)
    except ValueError:
        return InboundFrame(event=None, unknown_event=str(raw_event))

    stream_sid = data.get("streamSid")

    if event is Event.START:
        start = data.get("start") or {}
        return InboundFrame(
            event=event,
            stream_sid=stream_sid or start.get("streamSid"),
            call_sid=start.get("callSid"),
        )

    if event is Event.MEDIA:
        media = data.get("payload") or (data.get("media") or {}).get("payload") or ""
        try:
            mulaw = base64.b64decode(media, validate=True)
        except Exception:  # noqa: BLE001 - a bad chunk is not worth ending a call
            mulaw = b""
        ts = (data.get("media") or {}).get("timestamp")
        return InboundFrame(
            event=event,
            stream_sid=stream_sid,
            audio=mulaw_to_pcm16(mulaw) if mulaw else b"",
            timestamp_ms=int(ts) if str(ts).isdigit() else None,
        )

    if event is Event.MARK:
        return InboundFrame(
            event=event,
            stream_sid=stream_sid,
            mark_name=(data.get("mark") or {}).get("name"),
        )

    return InboundFrame(event=event, stream_sid=stream_sid)


# --------------------------------------------------------------------------- #
# Outbound frames
# --------------------------------------------------------------------------- #


def media_frame(stream_sid: str, pcm16: bytes, *, source_hz: int = SAMPLE_RATE_HZ) -> str:
    """One outbound audio frame, resampled and encoded for the carrier."""
    resampled = resample_pcm16(pcm16, source_hz, SAMPLE_RATE_HZ)
    payload = base64.b64encode(pcm16_to_mulaw(resampled)).decode()
    return json.dumps(
        {"event": "media", "streamSid": stream_sid, "media": {"payload": payload}}
    )


def mark_frame(stream_sid: str, name: str) -> str:
    """Ask Twilio to tell us when everything queued so far has played."""
    return json.dumps({"event": "mark", "streamSid": stream_sid, "mark": {"name": name}})


def clear_frame(stream_sid: str) -> str:
    """Abandon audio still queued for playback.

    This is what makes barge-in real rather than cosmetic. Without it, the
    persona keeps talking over the person for as long as its buffered reply
    lasts — several seconds, which is exactly when a scammer hangs up.
    """
    return json.dumps({"event": "clear", "streamSid": stream_sid})


def chunk_pcm16(pcm16: bytes, *, source_hz: int = SAMPLE_RATE_HZ) -> list[bytes]:
    """Split PCM16 into carrier-sized pieces, resampling first.

    Twilio accepts larger writes, but sending a whole utterance as one frame
    makes it un-interruptible: `clear` can only drop what has not yet been
    handed over, so one big frame is one big commitment.
    """
    resampled = resample_pcm16(pcm16, source_hz, SAMPLE_RATE_HZ)
    # μ-law is 1 byte/sample; PCM16 is 2, so a 20 ms PCM chunk is twice as long.
    step = BYTES_PER_CHUNK * 2
    return [resampled[i : i + step] for i in range(0, len(resampled), step)] or []


# --------------------------------------------------------------------------- #
# Turn-taking
# --------------------------------------------------------------------------- #


class Turn(str, Enum):
    LISTENING = "listening"
    SPEAKING = "speaking"


@dataclass
class TurnTaker:
    """Who currently holds the floor, and when to yield it.

    Deliberately a state machine over measurements rather than anything
    cleverer. The design note is blunt about the failure — "the persona talks
    over people" — and the two ways to get there are symmetrical:

    * never yielding, so the persona finishes its sentence regardless; and
    * yielding to any noise at all, so line hiss cuts it off mid-word and the
      call becomes unusable in the other direction.

    So speech is ``silence_threshold`` sustained over ``barge_in_ms`` — long
    enough that a cough or a click does not count, short enough to feel like
    being interrupted rather than ignored. Both are constructor arguments
    because the right values depend on the line, and neither has been validated
    against a real call yet.
    """

    silence_threshold: int = 500
    barge_in_ms: int = 240
    #: Ignore the caller for this long after we start speaking. Without it, the
    #: persona's own audio leaking back through the carrier's echo path reads as
    #: the caller talking, and it interrupts itself on the first syllable.
    echo_guard_ms: int = 200

    state: Turn = Turn.LISTENING
    _loud_ms: int = field(default=0, repr=False)
    _spoken_ms: int = field(default=0, repr=False)

    def begin_speaking(self) -> None:
        self.state = Turn.SPEAKING
        self._loud_ms = 0
        self._spoken_ms = 0

    def finished_speaking(self) -> None:
        """Called when Twilio marks our audio as played — not on a timer."""
        self.state = Turn.LISTENING
        self._loud_ms = 0

    def observe(self, pcm16: bytes, *, chunk_ms: int = CHUNK_MS) -> bool:
        """Feed one inbound chunk. Returns True when the caller has barged in.

        Only ever True while SPEAKING: while listening there is no floor to take.
        """
        loud = rms(pcm16) >= self.silence_threshold

        if self.state is Turn.SPEAKING:
            self._spoken_ms += chunk_ms
            if self._spoken_ms < self.echo_guard_ms:
                return False
            self._loud_ms = self._loud_ms + chunk_ms if loud else 0
            if self._loud_ms >= self.barge_in_ms:
                self.state = Turn.LISTENING
                self._loud_ms = 0
                return True
            return False

        self._loud_ms = self._loud_ms + chunk_ms if loud else 0
        return False
