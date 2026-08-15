"""Voice channel boundary — POC call replay + STT/TTS adapters (P4b).

Voice = the same honeypot pipeline over a **call** instead of a chat
(docs/INFILTRATE-Design.md §1a: STT → same agent loop → TTS). The channel is
the only new transport piece; agent loop, extraction, custody, classifier and
syndicate clustering are reused verbatim.

POC (all offline, deterministic, no keys):
- ``VOICE_SCRIPT`` — a phone-call-framed scam transcript (spoken Bahasa
  cadence). The scammer calls from ``+62 858-7766-1122`` and voluntarily
  discloses the P1 fixture TRON wallet ``TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6`` and
  the BCA mule account, so voice intel links into the Investigation graph.
  Includes a **read-back confirmation** beat (the persona repeats the wallet /
  account back — natural on a call, and the demo moment).
- ``VoiceReplayChannelAdapter`` — mirrors ``ReplayChannelAdapter`` for the
  ``channel_voice`` boundary (``channel="voice"``, caller number as ref).
- ``PassthroughSTTAdapter`` — STT boundary; POC "transcription" is the
  scripted transcript itself (browser/no audio in POC).
- ``VoiceMarkTTSAdapter`` — TTS boundary; returns per-line **voice marks**
  (speaker + estimated spoken duration, no real audio) — the browser's
  SpeechSynthesis produces the actual sound in the POC demo.

LIVE (clean stubs, fail loud, never silently degrade):
- ``PstnChannelAdapter`` — PSTN/WA-call bridge, Polri-gated.
- ``WhisperSTTAdapter`` — real speech-to-text.
- ``GoogleTTSAdapter`` / ``HiggsfieldTTSAdapter`` / ``ElevenLabsTTSAdapter``
  — pluggable natural-voice providers behind the same ``TTSAdapter``
  Protocol, selected by ``ITTU_TTS_PROVIDER`` (config.py). Adding a provider
  later = one adapter class + an env var — zero changes to the agent loop,
  session assembly, or UI.
"""

import base64
import hashlib
import struct
from collections import OrderedDict
from typing import Protocol

import httpx
from pydantic import BaseModel

from app.core.adapters import register
from app.core.config import Mode, Settings, get_settings
from app.infiltrate.channels import ChannelMessage, ScriptTurn

# --------------------------------------------------------------------------- #
# Spoken-duration estimation (deterministic voice marks)
# --------------------------------------------------------------------------- #

# Conversational Bahasa Indonesia ≈ 2.3 words/second on a phone call.
_WORDS_PER_SECOND = 2.3
_MIN_LINE_SECONDS = 2.0


def estimate_duration(text: str) -> float:
    """Deterministic spoken-duration estimate (seconds) for one line."""
    words = len(text.split())
    return round(max(_MIN_LINE_SECONDS, words / _WORDS_PER_SECOND), 1)


# --------------------------------------------------------------------------- #
# The scripted scam CALL (deterministic POC fixture)
#
# Narrative: "Pak Dimas" from ProfitMax Investa cold-calls Bu Sari from
# +62 858-7766-1122 with the same 10%/day pitch, spoken register. Over 6
# exchanges he discloses:
#   phone        0812-7788-9900                     (admin WhatsApp)
#   bank account BCA 5271038462 a.n. Rudi Hartono   (mule)
#   TRON wallet  TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6      (P1 fixture source)
# Turn 5 is the read-back confirmation: the persona repeats the wallet and
# account back "so she doesn't mistype" — locking the disclosure on tape.
# --------------------------------------------------------------------------- #

VOICE_CALLER_NUMBER = "+62 858-7766-1122"
VOICE_SCAMMER_NAME = "Pak Dimas"

# Interactive (Tier-B) sessions: the persona answers the call with this line —
# custody message #1. Not fed to the LLM history (Anthropic-style providers
# require the first non-system message to be the user's).
VOICE_GREETING = "halo, selamat siang.. dengan ibu Sari di sini. ini siapa ya nak?"

VOICE_SCRIPT: list[ScriptTurn] = [
    ScriptTurn(
        scammer=(
            "Halo, selamat siang, benar ini dengan Ibu Sari? Perkenalkan saya Dimas "
            "dari kantor pusat ProfitMax Investa. Begini Bu, nomor Ibu terpilih untuk "
            "program investasi eksklusif — profitnya sepuluh persen per hari Bu, "
            "dijamin, sudah ratusan member membuktikan. Ibu ada waktu sebentar?"
        ),
        persona_reply=(
            "halo.. iya betul ini Ibu Sari. waduh nak Dimas, profit sepuluh persen "
            "per hari? kok besar sekali ya.. saya ini guru pensiunan nak, kurang "
            "paham investasi begituan. itu beneran aman?"
        ),
        tool_calls=[
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "guaranteed_returns",
                    "detail": "Cold call claims guaranteed 10%/day profit to a pensioner",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Aman seratus persen Bu, kami terdaftar resmi. Kalau Ibu mau tanya-tanya "
            "dulu, nanti saya minta admin kami hubungi Ibu lewat WhatsApp di nol "
            "delapan satu dua, tujuh tujuh delapan delapan, sembilan sembilan nol nol "
            "— saya ulangi ya Bu, 0812-7788-9900. Dicatat ya Bu."
        ),
        persona_reply=(
            "sebentar nak, saya ambil pulpen dulu.. iya, nol delapan satu dua tujuh "
            "tujuh delapan delapan sembilan sembilan nol nol ya. sudah saya catat di "
            "buku. terus kalau misalnya ibu ikut, bayarnya bagaimana nak?"
        ),
        tool_calls=[
            {
                "name": "record_entity",
                "args": {
                    "type": "phone",
                    "value": "0812-7788-9900",
                    "context": "Admin WhatsApp number dictated on the call",
                },
            },
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "fake_legitimacy",
                    "detail": "Unverifiable 'terdaftar resmi' claim on a cold call",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Gampang Bu. Deposit awalnya transfer ke rekening BCA, saya eja pelan- "
            "pelan ya Bu: lima dua tujuh satu, nol tiga delapan, empat enam dua — "
            "jadi 5271038462, atas nama Rudi Hartono. Minimal dua juta saja Bu, "
            "besok siang sudah jadi dua juta dua ratus."
        ),
        persona_reply=(
            "aduh nak, kebetulan m-banking BCA ibu lagi keblokir dari kemarin, "
            "harus ke kantor cabang dulu katanya. ada cara lain tidak ya? anak ibu "
            "pernah cerita katanya bisa pakai uang crypto itu lho.."
        ),
        tool_calls=[
            {
                "name": "record_entity",
                "args": {
                    "type": "bank_account",
                    "value": "5271038462",
                    "bank_name": "BCA",
                    "context": "Deposit account dictated on the call, a.n. Rudi Hartono (likely mule)",
                },
            },
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "deposit_request",
                    "detail": "Money question reached on the call — deposit demanded to a personal account",
                },
            },
            {
                "name": "escalate_to_analyst",
                "args": {
                    "reason": "high_value_turn",
                    "detail": "Caller dictated the deposit bank account; money question in play",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Bisa banget Bu, malah lebih cepat prosesnya! Ibu kirim USDT jaringan "
            "TRON ke wallet resmi kami. Alamatnya saya bacakan ya Bu, tulis baik- "
            "baik: TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6. Huruf besar-kecilnya harus persis "
            "ya Bu, dan harus jaringan TRC20, jangan salah pilih."
        ),
        persona_reply=(
            "waduh panjang sekali nak.. sebentar, ibu tulis pelan-pelan ya. T besar, "
            "X besar, t kecil, R besar, sembilan, d kecil.. iya iya, sudah ibu tulis "
            "semua. nanti ibu foto kertasnya buat anak ibu, dia yang paham beginian."
        ),
        tool_calls=[
            {
                "name": "record_entity",
                "args": {
                    "type": "crypto_wallet",
                    "value": "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6",
                    "chain": "tron",
                    "context": "USDT-TRC20 collection wallet dictated letter-by-letter on the call",
                },
            },
            {
                "name": "escalate_to_analyst",
                "args": {
                    "reason": "wallet_disclosure",
                    "detail": "Primary USDT-TRC20 collection wallet dictated on a voice call",
                },
            },
        ],
    ),
    # Read-back confirmation — the persona repeats wallet + account back,
    # locking the disclosure on the recorded line (natural voice beat).
    ScriptTurn(
        scammer=(
            "Nah supaya tidak salah transfer, coba Ibu bacakan ulang catatannya ya. "
            "Salah satu huruf saja uangnya hilang lho Bu."
        ),
        persona_reply=(
            "baik nak, ibu bacakan ya pelan-pelan: wallet-nya "
            "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6, terus rekening BCA-nya 5271038462 atas "
            "nama Rudi Hartono. betul semua kan nak? maklum mata ibu sudah plus."
        ),
        tool_calls=[
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "deposit_request",
                    "detail": "Caller demanded a read-back of the payment coordinates",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Betul semua Bu, pintar sekali. Tapi ingat ya Bu, slot promo profit "
            "sepuluh persen ini hangus jam tiga sore ini. Sudah ada tiga calon "
            "member lain menunggu slot Ibu, jangan sampai keduluan ya Bu."
        ),
        persona_reply=(
            "iya nak iya, sabar ya.. namanya juga orang tua, semua harus pelan- "
            "pelan. nanti sore anak ibu pulang kerja, ibu kabari lagi ya nak. "
            "terima kasih sudah telepon."
        ),
        tool_calls=[
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "urgency_pressure",
                    "detail": "Artificial 3pm deadline + fake queue of competing members",
                },
            },
        ],
    ),
]


# --------------------------------------------------------------------------- #
# Voice channel adapter (channel_voice boundary)
# --------------------------------------------------------------------------- #


@register("channel_voice", "poc")
class VoiceReplayChannelAdapter:
    """POC: deterministic offline replay of ``VOICE_SCRIPT`` as a call.

    Mirrors ``ReplayChannelAdapter`` (channels.py) — same turn-based contract,
    so ``agent.run_session`` drives it unchanged. ``channel="voice"``, and the
    caller's number is the ``channel_ref`` (itself intel).
    """

    data_mode: Mode = "poc"
    channel = "voice"
    channel_ref = VOICE_CALLER_NUMBER

    def __init__(self, settings: Settings | None = None, script: list[ScriptTurn] | None = None):
        self._script = script if script is not None else VOICE_SCRIPT
        self._cursor = 0
        self.sent: list[ChannelMessage] = []

    async def receive(self) -> ChannelMessage | None:
        if self._cursor >= len(self._script):
            return None  # caller hangs up
        turn = self._script[self._cursor]
        self._cursor += 1
        return ChannelMessage(
            direction="inbound",
            content=turn.scammer,
            meta={"channel": self.channel, "sender": self.channel_ref, "turn": self._cursor},
        )

    async def send(self, text: str, meta: dict | None = None) -> ChannelMessage:
        msg = ChannelMessage(
            direction="outbound",
            content=text,
            meta={"channel": self.channel, "turn": self._cursor, **(meta or {})},
        )
        self.sent.append(msg)  # POC sink — nothing leaves the system
        return msg


@register("channel_voice", "live")
class PstnChannelAdapter:
    """LIVE stub — real inbound call bridge (PSTN / WhatsApp-call).

    Fails loudly: LIVE voice requires a telephony bridge (SIP/PSTN or WA-call),
    real STT/TTS credentials, and Polri supervision gating. Never silently
    degrades to POC.
    """

    data_mode: Mode = "live"
    channel = "voice"
    channel_ref = ""

    def __init__(self, settings: Settings | None = None):
        raise NotImplementedError(
            "LIVE PSTN/voice channel adapter is not wired in this build: it requires "
            "a telephony bridge (SIP/PSTN or WhatsApp-call), streaming STT/TTS "
            "credentials, and Polri supervision gating. Run INFILTRATE in POC mode "
            "(ITTU_MODE=poc)."
        )

    async def receive(self) -> ChannelMessage | None:  # pragma: no cover - stub
        raise NotImplementedError

    async def send(self, text: str, meta: dict | None = None) -> ChannelMessage:  # pragma: no cover
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# STT boundary (speech → text)
# --------------------------------------------------------------------------- #


class STTAdapter(Protocol):
    """Speech-to-text boundary. POC: transcript passthrough; LIVE: Whisper/Google."""

    data_mode: Mode

    async def transcribe(self, audio: bytes | str) -> str:
        """Turn one utterance into text (POC: the scripted line IS the text)."""
        ...


@register("stt", "poc")
class PassthroughSTTAdapter:
    """POC: the replay script already IS the transcript — pass it through."""

    data_mode: Mode = "poc"

    def __init__(self, settings: Settings | None = None):
        pass

    async def transcribe(self, audio: bytes | str) -> str:
        return audio if isinstance(audio, str) else audio.decode("utf-8")


@register("stt", "live")
class WhisperSTTAdapter:
    """LIVE stub — real streaming speech-to-text (Whisper/Google STT)."""

    data_mode: Mode = "live"

    def __init__(self, settings: Settings | None = None):
        raise NotImplementedError(
            "LIVE Whisper/Google STT adapter is not wired in this build: it requires "
            "provider credentials and the streaming-audio ingest path. Run INFILTRATE "
            "in POC mode (ITTU_MODE=poc)."
        )

    async def transcribe(self, audio: bytes | str) -> str:  # pragma: no cover - stub
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# TTS boundary (text → speech) — pluggable providers
# --------------------------------------------------------------------------- #


class TTSResult(BaseModel):
    """Normalized synthesis result. POC = voice marks only (``audio_url=None``,
    the browser's SpeechSynthesis speaks the line); LIVE = provider audio —
    either raw ``audio_bytes`` (streamed by the audio endpoint) or a hosted
    ``audio_url``."""

    provider: str
    voice: str
    text: str
    duration_seconds: float
    audio_url: str | None = None
    audio_bytes: bytes | None = None
    mime_type: str = "audio/mpeg"


class VoiceMarkOut(BaseModel):
    """API shape for ``GET /api/sessions/{id}/audio/{seq}`` (POC voice marks).

    ``audio_url=None`` means "no server audio — the browser speaks ``text``";
    LIVE providers fill ``audio_url`` (or stream bytes) instead.
    """

    session_id: str
    seq: int
    speaker: str
    text: str
    duration_seconds: float
    offset_seconds: float
    audio_url: str | None = None
    provider: str


class TTSAdapter(Protocol):
    """Text-to-speech boundary. POC: deterministic voice marks; LIVE: a real
    provider (Google / Higgsfield / ElevenLabs) selected by ``ITTU_TTS_PROVIDER``."""

    data_mode: Mode
    provider: str

    async def synthesize(self, text: str, voice: str = "persona") -> TTSResult:
        """Synthesize one line. POC returns marks; LIVE returns audio bytes/url."""
        ...


@register("tts", "poc")
class VoiceMarkTTSAdapter:
    """POC: no real audio — per-line "voice marks" (speaker + est. duration).

    The browser speaks the line via SpeechSynthesis; these marks drive caption
    sync and the call timeline deterministically.
    """

    data_mode: Mode = "poc"
    provider = "poc-voice-marks"

    def __init__(self, settings: Settings | None = None):
        pass

    async def synthesize(self, text: str, voice: str = "persona") -> TTSResult:
        return TTSResult(
            provider=self.provider,
            voice=voice,
            text=text,
            duration_seconds=estimate_duration(text),
            audio_url=None,
        )


class _LiveTTSStub:
    """Shared shape for LIVE TTS provider stubs — each fails loud until keyed."""

    data_mode: Mode = "live"
    provider = ""
    _requires = ""

    def __init__(self, settings: Settings | None = None):
        raise NotImplementedError(
            f"LIVE {type(self).__name__} is not wired in this build: it requires "
            f"{self._requires}. Set ITTU_TTS_PROVIDER to a wired provider or run "
            "INFILTRATE in POC mode (ITTU_MODE=poc)."
        )

    async def synthesize(self, text: str, voice: str = "persona") -> TTSResult:  # pragma: no cover
        raise NotImplementedError


_TTS_TIMEOUT_SECONDS = 30.0


class ElevenLabsTTSAdapter:
    """LIVE — ElevenLabs natural-voice synthesis (#15, real audio bytes).

    Key: ``ITTU_ELEVENLABS_API_KEY`` — fails loudly at construction without it;
    the key is only ever sent as the ``xi-api-key`` request header, never
    returned in any API response.
    """

    data_mode: Mode = "live"
    provider = "elevenlabs"
    # https://elevenlabs.io/docs/api-reference/text-to-speech/convert — default
    # output_format the API itself uses; set explicitly rather than relying on
    # the provider default (belt-and-braces against a future default change).
    _OUTPUT_FORMAT = "mp3_44100_128"
    _VOICE_SETTINGS = {"stability": 0.5, "similarity_boost": 0.75}

    def __init__(self, settings: Settings | None = None):
        settings = settings or get_settings()
        self._api_key = settings.elevenlabs_api_key
        if not self._api_key:
            raise NotImplementedError(
                "LIVE ElevenLabsTTSAdapter is not usable in this build: no key is "
                "configured. Set ITTU_ELEVENLABS_API_KEY, or set "
                "ITTU_TTS_PROVIDER=browser for the keyless POC voice."
            )
        # Model + per-account voice IDs are env-configurable (config.py): the
        # flash model keeps call latency low, and the voice IDs can be pointed at
        # voices that actually exist in the operator's ElevenLabs library.
        self._model = settings.elevenlabs_model
        self._voice_ids = {
            "persona": settings.elevenlabs_voice_persona,
            "scammer": settings.elevenlabs_voice_scammer,
        }

    async def synthesize(self, text: str, voice: str = "persona") -> TTSResult:
        voice_id = self._voice_ids.get(voice, self._voice_ids["persona"])
        async with httpx.AsyncClient(timeout=_TTS_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                params={"output_format": self._OUTPUT_FORMAT},
                headers={"xi-api-key": self._api_key, "accept": "audio/mpeg"},
                json={
                    "text": text,
                    "model_id": self._model,
                    "voice_settings": self._VOICE_SETTINGS,
                },
            )
            resp.raise_for_status()
            audio = resp.content
        return TTSResult(
            provider=self.provider, voice=voice, text=text,
            duration_seconds=estimate_duration(text),
            audio_bytes=audio, mime_type="audio/mpeg",
        )


class GoogleTTSAdapter:
    """LIVE — Google Cloud Text-to-Speech (WaveNet id-ID voices, real audio).

    Key: ``ITTU_GOOGLE_TTS_API_KEY`` (a Cloud API key with the TTS API
    enabled) — fails loudly at construction without it. The key is only ever
    sent as a query param to Google, never returned in any API response.
    """

    data_mode: Mode = "live"
    provider = "google"
    _VOICE_NAMES = {
        "persona": "id-ID-Wavenet-A",   # female
        "scammer": "id-ID-Wavenet-B",   # male
    }

    def __init__(self, settings: Settings | None = None):
        settings = settings or get_settings()
        self._api_key = settings.google_tts_api_key
        if not self._api_key:
            raise NotImplementedError(
                "LIVE GoogleTTSAdapter is not usable in this build: no key is "
                "configured. Set ITTU_GOOGLE_TTS_API_KEY, or set "
                "ITTU_TTS_PROVIDER=browser for the keyless POC voice."
            )

    async def synthesize(self, text: str, voice: str = "persona") -> TTSResult:
        name = self._VOICE_NAMES.get(voice, self._VOICE_NAMES["persona"])
        async with httpx.AsyncClient(timeout=_TTS_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                "https://texttospeech.googleapis.com/v1/text:synthesize",
                params={"key": self._api_key},
                json={
                    "input": {"text": text},
                    "voice": {"languageCode": "id-ID", "name": name},
                    "audioConfig": {"audioEncoding": "MP3"},
                },
            )
            resp.raise_for_status()
            audio = base64.b64decode(resp.json()["audioContent"])
        return TTSResult(
            provider=self.provider, voice=voice, text=text,
            duration_seconds=estimate_duration(text),
            audio_bytes=audio, mime_type="audio/mpeg",
        )


def _pcm_rate_from_mime(mime: str) -> int:
    """Parse the sample rate out of a ``audio/L16;codec=pcm;rate=24000`` mime."""
    for chunk in mime.split(";"):
        chunk = chunk.strip()
        if chunk.startswith("rate="):
            try:
                return int(chunk[5:])
            except ValueError:
                break
    return 24000


def _pcm_to_wav(pcm: bytes, *, sample_rate: int = 24000, bits: int = 16, channels: int = 1) -> bytes:
    """Wrap raw little-endian PCM in a 44-byte WAV header so a browser
    ``<audio>`` can play it (Gemini returns headerless PCM)."""
    block_align = channels * bits // 8
    byte_rate = sample_rate * block_align
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + len(pcm), b"WAVE",
        b"fmt ", 16, 1, channels, sample_rate, byte_rate, block_align, bits,
        b"data", len(pcm),
    )
    return header + pcm


class GeminiTTSAdapter:
    """LIVE — Google **Gemini TTS** (AI Studio), generative + style-controllable.

    Key: ``ITTU_GEMINI_API_KEY`` (an AI Studio key, DISTINCT from the Cloud-TTS
    key ``GoogleTTSAdapter`` uses) — fails loudly at construction without it;
    sent only as the ``x-goog-api-key`` header, never returned in a response.

    Chosen for its **natural-language style control**: the persona voice is
    prompted to sound like a confused, hesitant elderly woman (a delivery the
    flat WaveNet voices can't produce) — the whole point of A/B-ing it against
    ElevenLabs. Gemini returns headerless PCM (24kHz/16-bit/mono) which we wrap
    as WAV; Indonesian is auto-detected from the text.
    """

    data_mode: Mode = "live"
    provider = "gemini"
    # Prebuilt-voice fallbacks (docs list 30) — warm for the persona, firmer for
    # the scammer. The effective per-role voice is read from settings in
    # __init__ (Control-Panel overridable); the style directive below does most
    # of the emotional work regardless.
    _VOICE_NAMES = {"persona": "Sulafat", "scammer": "Charon"}
    # Leading style instruction Gemini follows but does NOT read aloud.
    _STYLE = {
        "persona": "Ucapkan dengan lembut dan pelan, seperti seorang nenek tua "
                   "yang bingung dan ragu-ragu:",
        "scammer": "Ucapkan dengan percaya diri dan mendesak, seperti seorang "
                   "telemarketer yang memaksa:",
    }

    def __init__(self, settings: Settings | None = None):
        settings = settings or get_settings()
        self._api_key = settings.gemini_api_key
        self._model = settings.gemini_tts_model
        if not self._api_key:
            raise NotImplementedError(
                "LIVE GeminiTTSAdapter is not usable in this build: no key is "
                "configured. Set ITTU_GEMINI_API_KEY (a Google AI Studio key), "
                "or set ITTU_TTS_PROVIDER=browser for the keyless POC voice."
            )
        # Normalize + validate the model name early so operators get a clear
        # message rather than the API's "unexpected model name format" 400.
        # Accept EITHER a bare model id ("gemini-2.5-flash-preview-tts") or a
        # "models/..."-prefixed resource name; we strip the prefix because the
        # request URL below already includes "/models/" (keeping it would send
        # ".../models/models/..." → 404). The only hard error is an empty value
        # or the human display name (which contains spaces).
        model = str(self._model or "").strip()
        if model.startswith("models/"):
            model = model[len("models/"):]
        if not model or " " in model:
            raise NotImplementedError(
                "LIVE GeminiTTSAdapter requires ITTU_GEMINI_TTS_MODEL to be a\n"
                "Gemini TTS model id. Only the *-tts preview models return audio:\n"
                "  ITTU_GEMINI_TTS_MODEL=gemini-2.5-flash-preview-tts   (default)\n"
                "  ITTU_GEMINI_TTS_MODEL=gemini-2.5-pro-preview-tts\n"
                "Do NOT use a text model (e.g. 'gemini-2.5-flash') or the display\n"
                "name 'Gemini 2.5 Flash Native Audio Dialog'.\n"
                f"Current value: {self._model!r}"
            )
        self._model = model
        # Effective per-role voice: settings (Control-Panel overridable) →
        # class fallback. Blank settings fall back to the warm/firm defaults.
        self._voice_names = {
            "persona": settings.gemini_voice_persona or self._VOICE_NAMES["persona"],
            "scammer": settings.gemini_voice_scammer or self._VOICE_NAMES["scammer"],
        }

    async def synthesize(self, text: str, voice: str = "persona") -> TTSResult:
        voice_name = self._voice_names.get(voice, self._voice_names["persona"])
        style = self._STYLE.get(voice, "")
        prompt = f"{style} {text}".strip()
        async with httpx.AsyncClient(timeout=_TTS_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/"
                f"{self._model}:generateContent",
                headers={"x-goog-api-key": self._api_key},
                json={
                    "contents": [{"parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "responseModalities": ["AUDIO"],
                        "speechConfig": {
                            "voiceConfig": {
                                "prebuiltVoiceConfig": {"voiceName": voice_name}
                            }
                        },
                    },
                },
            )
            if not resp.is_success:
                # Surface Google's error body (model-not-found / key-invalid /
                # region-unsupported / quota) instead of a bare HTTPStatusError.
                raise RuntimeError(f"Gemini TTS {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            try:
                inline = data["candidates"][0]["content"]["parts"][0]["inlineData"]
            except (KeyError, IndexError, TypeError) as exc:
                # 200 but no audio (safety block / unexpected shape) — say so.
                raise RuntimeError(
                    f"Gemini TTS returned no audio: {str(data)[:300]}"
                ) from exc
            pcm = base64.b64decode(inline["data"])
            rate = _pcm_rate_from_mime(inline.get("mimeType", ""))
        return TTSResult(
            provider=self.provider, voice=voice, text=text,
            duration_seconds=estimate_duration(text),
            audio_bytes=_pcm_to_wav(pcm, sample_rate=rate), mime_type="audio/wav",
        )


class HiggsfieldTTSAdapter(_LiveTTSStub):
    """LIVE stub — Higgsfield speech synthesis (not wired yet, fails loud)."""

    provider = "higgsfield"
    _requires = "a Higgsfield API key"


# Provider registry: adding a provider later = one class + one entry here.
LIVE_TTS_PROVIDERS: dict[str, type] = {
    GoogleTTSAdapter.provider: GoogleTTSAdapter,
    HiggsfieldTTSAdapter.provider: HiggsfieldTTSAdapter,
    ElevenLabsTTSAdapter.provider: ElevenLabsTTSAdapter,
    GeminiTTSAdapter.provider: GeminiTTSAdapter,
}


@register("tts", "live")
def select_live_tts_adapter(settings: Settings | None = None) -> TTSAdapter:
    """LIVE TTS factory — resolve the provider named by ``ITTU_TTS_PROVIDER``.

    Registered as the ``("tts", "live")`` implementation so
    ``get_adapter("tts", "infiltrate")`` picks the configured provider. Every
    provider currently fails loud at construction (no keys wired).
    """
    settings = settings or get_settings()
    provider = settings.tts_provider.strip().lower()
    impl = LIVE_TTS_PROVIDERS.get(provider)
    if impl is None:
        raise LookupError(
            f"Unknown LIVE TTS provider {provider!r} (ITTU_TTS_PROVIDER). "
            f"Known providers: {sorted(LIVE_TTS_PROVIDERS)}."
        )
    return impl(settings)


def resolve_tts_adapter(
    provider: str | None, *, default: TTSAdapter, overrides: dict | None = None
) -> TTSAdapter:
    """Pick the TTS adapter for ONE request. ``provider`` is an optional
    per-request override (the Control Panel voice choice); ``default`` is the
    env-configured adapter (``ITTU_TTS_PROVIDER``). This is what lets an operator
    A/B ElevenLabs/Gemini/Google live from the portal with no backend restart —
    keys are still read once at startup, only the choice is per-request.

    ``overrides`` is an optional dict of ``Settings`` field names → values (e.g.
    a Control-Panel model / voice-id override). Applied via ``model_copy`` — a
    per-request COPY of the cached settings, never a mutation of the singleton —
    so adapters pick it up with no adapter-side changes.

    Unknown/empty → ``default``; "browser"/"poc" → voice marks; a known LIVE
    provider → its adapter (may raise ``NotImplementedError`` if its key is
    unset — the caller degrades to marks)."""
    if not provider:
        return default
    name = provider.strip().lower()
    if name in ("browser", "poc", "marks"):
        return VoiceMarkTTSAdapter()
    impl = LIVE_TTS_PROVIDERS.get(name)
    if impl is None:
        return default
    settings = get_settings()
    if overrides:
        settings = settings.model_copy(update=overrides)  # copy — never mutate the singleton
    return impl(settings)


# --------------------------------------------------------------------------- #
# Synthesized-audio cache (LIVE) — a real provider call costs money + latency;
# the same line (a persona greeting, a read-back) recurs across a call and
# across sessions, so cache the bytes by (provider, voice, text). Bounded LRU,
# process-local — fine for the single-worker POC/demo; a shared cache (Redis /
# object store) is the multi-worker production upgrade behind this same helper.
# --------------------------------------------------------------------------- #

_AUDIO_CACHE: "OrderedDict[str, TTSResult]" = OrderedDict()
_AUDIO_CACHE_CAP = 256


def _audio_cache_key(provider: str, voice: str, text: str, signature: str = "") -> str:
    return hashlib.sha256(
        f"{provider}\x1f{voice}\x1f{signature}\x1f{text}".encode()
    ).hexdigest()


def _adapter_cache_signature(tts: "TTSAdapter") -> str:
    """Fold per-request config (model / voice-id overrides) into the cache key so
    changing a voice from the Control Panel isn't masked by a stale cache hit for
    the same (provider, voice, text)."""
    return f"{getattr(tts, '_model', '')}\x1f{getattr(tts, '_voice_ids', '')}"


def reset_audio_cache() -> None:  # test hook
    _AUDIO_CACHE.clear()


async def synthesize_line(tts: TTSAdapter, text: str, voice: str = "persona") -> TTSResult:
    """Synthesize one line through ``tts``, caching LIVE audio bytes so a replay
    or a repeated line never re-hits (or re-pays) the provider. POC voice marks
    carry no bytes and are cheap, so they're passed straight through, uncached."""
    if getattr(tts, "data_mode", "poc") != "live":
        return await tts.synthesize(text, voice=voice)

    key = _audio_cache_key(
        tts.provider, voice, text, signature=_adapter_cache_signature(tts)
    )
    hit = _AUDIO_CACHE.get(key)
    if hit is not None:
        _AUDIO_CACHE.move_to_end(key)
        return hit

    result = await tts.synthesize(text, voice=voice)
    if result.audio_bytes:
        _AUDIO_CACHE[key] = result
        _AUDIO_CACHE.move_to_end(key)
        while len(_AUDIO_CACHE) > _AUDIO_CACHE_CAP:
            _AUDIO_CACHE.popitem(last=False)
    return result


async def list_elevenlabs_voices(settings: "Settings | None" = None) -> list[dict[str, str]]:
    """The voices the configured ElevenLabs key can synthesize (id + name).

    Empty if no key. Raises ``httpx.HTTPError`` on a transport/auth failure —
    the caller decides how to surface it. The key is only ever sent as the
    ``xi-api-key`` header, never returned. Powers the Control Panel's
    "Check voices" button (catch a bad voice ID before a call)."""
    settings = settings or get_settings()
    if not settings.elevenlabs_api_key:
        return []
    async with httpx.AsyncClient(timeout=_TTS_TIMEOUT_SECONDS) as client:
        resp = await client.get(
            "https://api.elevenlabs.io/v1/voices",
            headers={"xi-api-key": settings.elevenlabs_api_key},
        )
        resp.raise_for_status()
        return [
            {"id": v["voice_id"], "name": v.get("name", "")}
            for v in resp.json().get("voices", [])
        ]


async def check_elevenlabs_voice(
    voice_id: str,
    settings: "Settings | None" = None,
    text: str = "Halo, selamat siang, apa kabar?",
) -> dict:
    """Validate one ElevenLabs voice ID via a short synthesis, returning the
    audio so the Control Panel can PLAY a sample (not just validate).

    Uses the **Text-to-Speech** scope (the same call the honeypot makes), not
    the Voices-list endpoint — so it works even with a key restricted to TTS,
    and it tests the exact path a live call uses. Returns
    ``{ok: True, audio: bytes}`` on success, else
    ``{ok: False, status?: int, error?: str}``; the key is only ever sent as
    the ``xi-api-key`` header."""
    settings = settings or get_settings()
    if not settings.elevenlabs_api_key:
        return {"ok": False, "error": "no_key"}
    try:
        async with httpx.AsyncClient(timeout=_TTS_TIMEOUT_SECONDS) as client:
            resp = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
                params={"output_format": "mp3_44100_128"},
                headers={
                    "xi-api-key": settings.elevenlabs_api_key,
                    "accept": "audio/mpeg",
                },
                json={"text": text, "model_id": settings.elevenlabs_model},
            )
        if resp.is_success:
            return {"ok": True, "audio": resp.content}
        return {"ok": False, "status": resp.status_code, "error": f"http_{resp.status_code}"}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"transport:{type(exc).__name__}"}


async def check_gemini(
    settings: "Settings | None" = None,
    voice: str = "persona",
    text: str = "Halo, selamat siang, apa kabar?",
    voice_name: str = "",
) -> dict:
    """Readiness check for Gemini TTS via a short test synthesis, so the Control
    Panel can tell whether Gemini is usable BEFORE a call silently degrades.

    Runs the exact ``generateContent`` path a honeypot line uses and maps the
    outcome to a clear signal: ``{ok:True, audio}`` (ready — the WAV sample can
    be played), or ``{ok:False, status?, error?}`` where error is
    ``no_key`` | ``config:<msg>`` (bad model name) | ``http_<code>`` (e.g. 429 =
    quota, 400 = invalid voice name / bad model, 404 = region, 403 = key
    rejected) | ``transport:<Type>``. When ``voice_name`` is given, that exact
    prebuilt voice is tested (so the Control Panel can validate a just-typed
    voice); blank tests the role's configured default. The key is only ever sent
    as the ``x-goog-api-key`` header, never returned."""
    settings = settings or get_settings()
    if not settings.gemini_api_key:
        return {"ok": False, "error": "no_key"}
    try:
        adapter = GeminiTTSAdapter(settings)
    except NotImplementedError as exc:
        # Missing key is handled above; this is a bad model-name config.
        return {"ok": False, "error": f"config: {str(exc).splitlines()[0][:120]}"}
    if voice_name.strip():
        adapter._voice_names[voice] = voice_name.strip()
    try:
        result = await adapter.synthesize(text, voice)
        return {"ok": True, "audio": result.audio_bytes}
    except RuntimeError as exc:
        # GeminiTTSAdapter raises "Gemini TTS <status>: <body>" on HTTP errors,
        # or "Gemini TTS returned no audio: …" on a 200 with no audio part.
        msg = str(exc)
        status: int | None = None
        if msg.startswith("Gemini TTS "):
            head = msg[len("Gemini TTS ") :].split(":", 1)[0].strip()
            if head.isdigit():
                status = int(head)
        return {
            "ok": False,
            "status": status,
            "error": f"http_{status}" if status else msg[:160],
        }
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"transport:{type(exc).__name__}"}
