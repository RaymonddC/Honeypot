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

from typing import Protocol

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
    the browser's SpeechSynthesis speaks the line); LIVE = provider audio."""

    provider: str
    voice: str
    text: str
    duration_seconds: float
    audio_url: str | None = None


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


class GoogleTTSAdapter(_LiveTTSStub):
    """LIVE stub — Google Cloud Text-to-Speech (WaveNet id-ID voices)."""

    provider = "google"
    _requires = "Google Cloud TTS credentials (GOOGLE_APPLICATION_CREDENTIALS)"


class HiggsfieldTTSAdapter(_LiveTTSStub):
    """LIVE stub — Higgsfield speech synthesis."""

    provider = "higgsfield"
    _requires = "a Higgsfield API key"


class ElevenLabsTTSAdapter(_LiveTTSStub):
    """LIVE stub — ElevenLabs natural-voice synthesis."""

    provider = "elevenlabs"
    _requires = "an ElevenLabs API key (ELEVENLABS_API_KEY)"


# Provider registry: adding a provider later = one class + one entry here.
LIVE_TTS_PROVIDERS: dict[str, type] = {
    GoogleTTSAdapter.provider: GoogleTTSAdapter,
    HiggsfieldTTSAdapter.provider: HiggsfieldTTSAdapter,
    ElevenLabsTTSAdapter.provider: ElevenLabsTTSAdapter,
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
