"""Channel boundary (text) — POC replay adapter + LIVE stubs.

The ``ChannelAdapter`` normalizes every transport (Telegram/WhatsApp/forum)
to turn-based messages so the agent loop is transport-agnostic
(docs/INFILTRATE-Design.md §1).

POC (``ReplayChannelAdapter``): replays a **scripted, deterministic** scam
conversation — a Telegram investment-scam operator working persona
"Bu Sari, 54". Fully offline, no network, no credentials; the transcript
doubles as the demo narrative + test fixture. It deliberately discloses the
TRON wallet ``TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6`` (the P1 Investigation fixture
source) and a BCA mule account, so extracted honeypot intel links straight
into the Investigation screen.

LIVE (``TelegramChannelAdapter``): clean stub — fails loudly at construction.
Real Telethon/Bot-API integration is gated behind credentials + Polri
supervision and lands with the LIVE rollout.
"""

from typing import Protocol

from pydantic import BaseModel, Field

from app.core.adapters import register
from app.core.config import Mode, Settings

# --------------------------------------------------------------------------- #
# Message + script shapes
# --------------------------------------------------------------------------- #


class ChannelMessage(BaseModel):
    """One normalized turn on a channel (internal Message schema)."""

    direction: str  # inbound | outbound
    content: str
    meta: dict = Field(default_factory=dict)


class ScriptTurn(BaseModel):
    """One scripted exchange: scammer inbound → persona reply (+ covert tools).

    ``tool_calls`` are the covert side-effect calls the scripted "LLM" makes
    on this turn (OLAF ``flag_emotional_distress`` pattern) — silent to the
    scammer, dispatched by the agent loop.
    """

    scammer: str
    persona_reply: str
    tool_calls: list[dict] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# The scripted scam conversation (deterministic POC fixture)
#
# Narrative: "Andi" from ProfitMax Investa (Telegram) pitches a 10%/day
# investment scheme to Bu Sari. Over 6 turns he voluntarily discloses:
#   url          https://profit-maxx-invest.com
#   phones       0813-9988-7766 and +62 812-3344-5566  (→ E.164 +62…)
#   bank account BCA 5271038462 a.n. Rudi Hartono
#   TRON wallet  TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6  (P1 fixture source → links
#                honeypot intel to the Investigation graph)
# The persona stays strictly reactive: never initiates, never sends funds.
# --------------------------------------------------------------------------- #

DEMO_TRON_WALLET = "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6"
DEMO_BCA_ACCOUNT = "5271038462"
SCAMMER_HANDLE = "@ProfitMax_Andi"

REPLAY_SCRIPT: list[ScriptTurn] = [
    ScriptTurn(
        scammer=(
            "Selamat siang Bu! Saya Andi dari ProfitMax Investa. Selamat, nomor Ibu "
            "terpilih untuk program investasi eksklusif kami — profit 10% PER HARI, "
            "dijamin, sudah dibuktikan ratusan member. Slot terbatas hari ini ya Bu!"
        ),
        persona_reply=(
            "waduh selamat siang nak.. profit 10% sehari? kok bisa ya, saya guru "
            "pensiunan, gaptek soal beginian hehe. itu aman tidak ya nak?"
        ),
        tool_calls=[
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "guaranteed_returns",
                    "detail": "Claims guaranteed 10%/day profit + limited-slot urgency",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Aman 100% Bu, sudah terdaftar resmi! Ibu bisa cek sendiri website kami "
            "https://profit-maxx-invest.com — semua legal Bu. Mulai bisa dari "
            "Rp 2.000.000 saja, besok sudah jadi Rp 2.200.000."
        ),
        persona_reply=(
            "oh ada websitenya toh.. nanti saya minta tolong anak saya bukakan ya, "
            "hp saya suka lemot. kalau saya mau tanya2 dulu boleh nak?"
        ),
        tool_calls=[
            {
                "name": "record_entity",
                "args": {
                    "type": "url",
                    "value": "https://profit-maxx-invest.com",
                    "context": "Claimed official website of ProfitMax Investa",
                },
            },
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "fake_legitimacy",
                    "detail": "Unverifiable 'terdaftar resmi' claim + fake platform site",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Tentu Bu! Ibu bisa WA admin kami di 0813-9988-7766, atau langsung ke "
            "nomor pribadi saya +62 812-3344-5566 biar cepat saya proses slotnya."
        ),
        persona_reply=(
            "iya nak makasih ya nomornya, saya catat dulu di buku. terus kalau "
            "misalnya saya ikut, caranya bagaimana ya nak bayarnya?"
        ),
        tool_calls=[
            {
                "name": "record_entity",
                "args": {
                    "type": "phone",
                    "value": "0813-9988-7766",
                    "context": "WhatsApp admin number for ProfitMax Investa",
                },
            },
            {
                "name": "record_entity",
                "args": {
                    "type": "phone",
                    "value": "+62 812-3344-5566",
                    "context": "Personal number of operator 'Andi'",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Gampang Bu. Deposit awal transfer ke rekening BCA 5271038462 a.n. "
            "Rudi Hartono. Setelah transfer, kirim bukti ke sini ya Bu biar langsung "
            "saya aktifkan akunnya hari ini juga."
        ),
        persona_reply=(
            "oh ke rekening BCA ya.. aduh nak, kebetulan m-banking BCA saya lagi "
            "keblokir dari kemarin, kata banknya harus ke kantor cabang dulu. "
            "ada cara lain tidak ya? anak saya pernah bilang bisa pakai itu lho, "
            "uang crypto?"
        ),
        tool_calls=[
            {
                "name": "record_entity",
                "args": {
                    "type": "bank_account",
                    "value": "5271038462",
                    "bank_name": "BCA",
                    "context": "Deposit account, a.n. Rudi Hartono (likely mule)",
                },
            },
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "deposit_request",
                    "detail": "Money question reached — deposit demanded to a personal account",
                },
            },
            {
                "name": "escalate_to_analyst",
                "args": {
                    "reason": "high_value_turn",
                    "detail": "Scammer disclosed deposit bank account; money question in play",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Bisa banget Bu, malah lebih cepat! Kirim USDT jaringan TRC20 ke wallet "
            "resmi kami: TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6 — ingat ya Bu harus network "
            "TRON (TRC20), jangan salah pilih. Kurs sudah saya hitungkan nanti."
        ),
        persona_reply=(
            "baik nak, saya screenshot dulu ya alamatnya panjang sekali soalnya. "
            "nanti sore saya minta tolong anak saya, dia yang paham beginian."
        ),
        tool_calls=[
            {
                "name": "record_entity",
                "args": {
                    "type": "crypto_wallet",
                    "value": "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6",
                    "chain": "tron",
                    "context": "USDT-TRC20 deposit wallet disclosed for 'investment'",
                },
            },
            {
                "name": "escalate_to_analyst",
                "args": {
                    "reason": "wallet_disclosure",
                    "detail": "Primary USDT-TRC20 collection wallet disclosed",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Siap Bu, saya tunggu ya. Jangan lama-lama Bu, slot promo profit 10% "
            "cuma sampai jam 8 malam ini. Sudah 3 member lain antri slot Ibu."
        ),
        persona_reply=(
            "iya nak iya, sabar ya.. namanya juga orang tua, semua harus pelan2. "
            "nanti kalau anak saya sudah pulang kerja saya kabari lagi ya."
        ),
        tool_calls=[
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "urgency_pressure",
                    "detail": "Artificial deadline + fake competition for the 'slot'",
                },
            },
        ],
    ),
]


# --------------------------------------------------------------------------- #
# Channel adapter interface + implementations
# --------------------------------------------------------------------------- #


class ChannelAdapter(Protocol):
    """Text-channel boundary. POC: scripted replay; LIVE: Telegram/WhatsApp."""

    data_mode: Mode
    channel: str  # telegram | whatsapp | forum
    channel_ref: str  # scammer handle/number (itself intel)

    async def receive(self) -> ChannelMessage | None:
        """Next inbound scammer message, or None when the conversation ends."""
        ...

    async def send(self, text: str, meta: dict | None = None) -> ChannelMessage:
        """Send the persona's reply outbound (POC: recorded, goes nowhere)."""
        ...


@register("channel", "poc")
@register("channel_text", "poc")  # framework alias (docs list the boundary as channel_text)
class ReplayChannelAdapter:
    """POC: deterministic offline replay of ``REPLAY_SCRIPT`` (no network)."""

    data_mode: Mode = "poc"
    channel = "telegram"
    channel_ref = SCAMMER_HANDLE

    def __init__(self, settings: Settings | None = None, script: list[ScriptTurn] | None = None):
        self._script = script if script is not None else REPLAY_SCRIPT
        self._cursor = 0
        self.sent: list[ChannelMessage] = []

    async def receive(self) -> ChannelMessage | None:
        if self._cursor >= len(self._script):
            return None
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


@register("channel", "live")
@register("channel_text", "live")
class TelegramChannelAdapter:
    """LIVE stub — real Telegram (Telethon/Bot API) engagement.

    Fails loudly: LIVE channels require credentials, the human-realism send
    layer, and Polri supervision gating. Never silently degrades to POC.
    """

    data_mode: Mode = "live"
    channel = "telegram"
    channel_ref = ""

    def __init__(self, settings: Settings | None = None):
        raise NotImplementedError(
            "LIVE Telegram channel adapter is not wired in this build: it requires "
            "Telethon/Bot-API credentials, the human-realism layer, and Polri "
            "supervision gating. Run INFILTRATE in POC mode (ITTU_MODE=poc)."
        )

    async def receive(self) -> ChannelMessage | None:  # pragma: no cover - stub
        raise NotImplementedError

    async def send(self, text: str, meta: dict | None = None) -> ChannelMessage:  # pragma: no cover
        raise NotImplementedError
