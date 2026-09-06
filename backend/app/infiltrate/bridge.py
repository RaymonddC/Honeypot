"""The media bridge — one live call, held by the persona.

This is the loop `media_stream.py` provides the parts for: read Twilio's frames,
decide when the caller has finished a sentence, transcribe it, take one agent
turn, speak the reply back, and yield the floor when interrupted.

**Written against a socket-shaped PROTOCOL, not against FastAPI's WebSocket**, so
the whole conversation can be driven in a test with scripted frames. The endpoint
in the router is a thin adapter. That matters because everything interesting here
— when an utterance ends, what happens when the caller talks over the persona,
what happens when a provider returns the wrong audio format — is logic, and logic
tested only against a live phone call is logic tested once.

## What still cannot be proven here

Latency. A test can assert the reply is produced; it cannot assert it arrives
before the caller gives up and hangs up. `docs/Live-Voice-Calls.md` is right that
this is the real blocker, and it stays unproven until a real call happens.

## Audio format

Twilio speaks μ-law 8 kHz. TTS providers mostly return MP3, which this **refuses
to send** — MP3 bytes reinterpreted as μ-law are not quiet corruption, they are
loud static down a real phone line, and the caller hangs up on a bug that looks
like a bad connection. The provider must be configured for PCM (ElevenLabs
``pcm_16000``/``ulaw_8000``, Google ``LINEAR16``); anything else fails loudly
with a message naming the fix.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from app.infiltrate.media_stream import (
    CHUNK_MS,
    SAMPLE_RATE_HZ,
    Event,
    TurnTaker,
    chunk_pcm16,
    clear_frame,
    mark_frame,
    media_frame,
    parse_frame,
    rms,
)

_log = logging.getLogger("uvicorn.error")

#: Silence that ends an utterance. Long enough to survive the pause inside a
#: sentence, short enough that the persona does not feel slow. Unvalidated
#: against a real call — the first thing to tune once one happens.
END_OF_UTTERANCE_MS = 700

#: Below this we are not going to get a useful transcription, and sending it
#: wastes a provider call and a second of the caller's patience.
MIN_UTTERANCE_MS = 400

#: Stop buffering long before memory matters — a caller who talks for a minute
#: without pausing is a monologue, and the agent should answer what it has.
MAX_UTTERANCE_MS = 20_000


class Socket(Protocol):
    """The bit of a WebSocket this needs. FastAPI's satisfies it."""

    async def receive_text(self) -> str: ...
    async def send_text(self, data: str) -> None: ...


@dataclass
class CallState:
    stream_sid: str | None = None
    call_sid: str | None = None
    session_id: str | None = None
    turns: int = 0
    #: Marks we are waiting on. The floor returns when Twilio confirms playback,
    #: never on a timer — playback is buffered on their side, so wall-clock says
    #: the persona has finished while it is still audibly talking.
    pending_marks: set[str] = field(default_factory=set)


class MediaBridge:
    """Drives one call. Construct per connection; not reusable."""

    def __init__(
        self,
        *,
        transcribe,
        reply,
        synthesize,
        on_start=None,
        turn_taker: TurnTaker | None = None,
    ) -> None:
        # Injected rather than imported so a test can drive the conversation
        # without an LLM, an STT provider or a database.
        self._transcribe = transcribe          # (pcm16) -> str
        self._reply = reply                    # (session_id, text) -> str
        self._synthesize = synthesize          # (text) -> (pcm16, sample_rate)
        self._on_start = on_start              # (call_sid) -> session_id
        self._turn = turn_taker or TurnTaker()
        self.state = CallState()
        self._buffer = bytearray()
        self._voiced_ms = 0
        self._silence_ms = 0

    # -- inbound ---------------------------------------------------------- #

    async def handle(self, socket: Socket) -> CallState:
        """Run until the stream stops or the socket closes."""
        while True:
            try:
                raw = await socket.receive_text()
            except Exception:  # noqa: BLE001 - a closed socket is a hangup
                break
            if raw is None:
                break

            frame = parse_frame(raw)
            if frame is None:
                # Not usable JSON. Dropping ONE frame is right; ending the call
                # is not — staying on the line is the entire product.
                continue

            if frame.event is Event.START:
                self.state.stream_sid = frame.stream_sid
                self.state.call_sid = frame.call_sid
                if self._on_start is not None:
                    self.state.session_id = await self._on_start(frame.call_sid)
                _log.info("bridge: call %s started", frame.call_sid)

            elif frame.event is Event.MEDIA:
                await self._on_audio(socket, frame.audio)

            elif frame.event is Event.MARK:
                # Our audio finished playing. NOW the floor is free.
                self.state.pending_marks.discard(frame.mark_name or "")
                if not self.state.pending_marks:
                    self._turn.finished_speaking()

            elif frame.event is Event.STOP:
                _log.info("bridge: call %s ended", self.state.call_sid)
                break

        return self.state

    async def _on_audio(self, socket: Socket, pcm16: bytes) -> None:
        if not pcm16:
            return

        # Barge-in first: if the caller has taken the floor, abandon whatever is
        # still queued before doing anything else. `clear` only drops audio not
        # yet handed over, so every frame of delay is a frame we keep talking.
        if self._turn.observe(pcm16):
            if self.state.stream_sid:
                await socket.send_text(clear_frame(self.state.stream_sid))
            self.state.pending_marks.clear()
            self._reset_utterance()
            _log.info("bridge: caller interrupted; floor yielded")

        # While the persona is speaking, the caller's audio is not an utterance
        # being collected — it is either echo or an interruption, and the
        # interruption case was just handled.
        if self._turn.state.value == "speaking":
            return

        loud = rms(pcm16) >= self._turn.silence_threshold
        if loud:
            self._buffer += pcm16
            self._voiced_ms += CHUNK_MS
            self._silence_ms = 0
        elif self._voiced_ms:
            # Trailing silence is kept: cutting exactly at the last loud frame
            # clips the final consonant, and STT is measurably worse for it.
            self._buffer += pcm16
            self._silence_ms += CHUNK_MS

        ended = self._voiced_ms and self._silence_ms >= END_OF_UTTERANCE_MS
        too_long = self._voiced_ms >= MAX_UTTERANCE_MS
        if ended or too_long:
            await self._take_turn(socket)

    # -- one turn --------------------------------------------------------- #

    async def _take_turn(self, socket: Socket) -> None:
        utterance, voiced = bytes(self._buffer), self._voiced_ms
        self._reset_utterance()

        if voiced < MIN_UTTERANCE_MS:
            return  # a cough, a door, a line click

        try:
            text = (await self._transcribe(utterance)) or ""
        except Exception as exc:  # noqa: BLE001 - a failed turn is not a dropped call
            _log.warning("bridge: transcription failed (%s) — staying on the line", exc)
            return
        if not text.strip():
            return

        try:
            answer = await self._reply(self.state.session_id, text)
        except Exception as exc:  # noqa: BLE001
            _log.warning("bridge: agent turn failed (%s) — staying on the line", exc)
            return
        if not answer:
            return

        self.state.turns += 1
        await self._speak(socket, answer)

    async def _speak(self, socket: Socket, text: str) -> None:
        if not self.state.stream_sid:
            return
        try:
            pcm16, source_hz = await self._synthesize(text)
        except Exception as exc:  # noqa: BLE001
            _log.warning("bridge: synthesis failed (%s) — staying on the line", exc)
            return
        if not pcm16:
            return

        self._turn.begin_speaking()
        for chunk in chunk_pcm16(pcm16, source_hz=source_hz):
            await socket.send_text(
                media_frame(self.state.stream_sid, chunk, source_hz=SAMPLE_RATE_HZ)
            )

        # One mark after the whole utterance: Twilio echoes it when playback
        # finishes, which is the only honest "the persona has stopped" signal.
        name = f"turn-{self.state.turns}"
        self.state.pending_marks.add(name)
        await socket.send_text(mark_frame(self.state.stream_sid, name))

    def _reset_utterance(self) -> None:
        self._buffer = bytearray()
        self._voiced_ms = 0
        self._silence_ms = 0


def pcm_from_tts(audio: bytes, mime_type: str) -> tuple[bytes, int]:
    """Extract PCM16 and its sample rate from a TTS result, or refuse.

    **Refusing is the feature.** MP3 bytes written to a Twilio media stream are
    not silence or distortion — they are full-scale static, and the caller hangs
    up on what sounds like a broken line. That failure is expensive to diagnose
    from the far end of a phone call and trivial to prevent here.

    Configure the provider for PCM: ElevenLabs ``pcm_16000`` (or ``ulaw_8000``,
    which needs no conversion at all), Google ``LINEAR16``.
    """
    from app.infiltrate.voice import _pcm_rate_from_mime

    if mime_type.startswith("audio/L16") or "pcm" in mime_type:
        return audio, _pcm_rate_from_mime(mime_type)
    raise ValueError(
        f"TTS returned {mime_type!r}, which cannot be streamed to a phone call. "
        "Twilio needs μ-law 8 kHz, and sending compressed audio as raw samples "
        "produces static, not a bad-quality voice. Configure the provider for "
        "PCM output (ElevenLabs pcm_16000 or ulaw_8000; Google LINEAR16)."
    )
