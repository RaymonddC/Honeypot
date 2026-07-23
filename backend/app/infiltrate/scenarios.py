"""Honeypot scam scenarios — the 3 MVP typologies (docs/INFILTRATE-Design.md §2).

The proposal's Implementation-Readiness scope names three AI-Honeypot scenarios:
**investment scam, judol (online-gambling) deposit, and crypto phishing.** Each
scenario bundles a victim persona + a deterministic scripted operator
conversation (POC replay) whose disclosed entities are chosen so the Layer-A
regex/checksum validators (app/infiltrate/extraction.py) turn the transcript
into court-usable intel, and whose scam signals drive the crime classifier to
the right typology.

- ``investment_scam`` reuses the original ``channels.REPLAY_SCRIPT`` (Bu Sari ×
  "ProfitMax Andi") verbatim — its TRON wallet is the P1 Investigation fixture
  source, so honeypot intel links straight into the Graph Explorer.
- ``judol_deposit`` (Pak Budi × a slot-gacor operator) discloses a gambling
  site, a WA admin number, and a mule BCA deposit account.
- ``crypto_phishing`` (Mbak Rina × a fake-airdrop "support" agent) discloses a
  phishing site, an ETH collection wallet, and a seed-phrase probe.

Selection is by ``scenario`` key on ``POST /api/sessions`` (defaults to
``investment_scam``); ``ReplayChannelAdapter`` takes the per-scenario channel +
handle so the finished session carries the right transport identity.
"""

from pydantic import BaseModel

from app.infiltrate.channels import REPLAY_SCRIPT, ScriptTurn
from app.infiltrate.personas import (
    BU_SARI,
    MBAK_RINA,
    PAK_BUDI,
    Persona,
)

# --------------------------------------------------------------------------- #
# Scenario 2 — judol (online gambling) deposit
#
# Narrative: "Bang Jeki" from a slot site (WhatsApp) lures Pak Budi with
# maxwin/gacor talk. Over 6 turns he voluntarily discloses:
#   url          https://gacor88-maxwin.com
#   phone        0821-5566-7788                       (WA admin/CS)
#   bank account BCA 7729104456 a.n. Dewi Lestari     (deposit mule)
# Pak Budi stays reactive: curious, never actually tops up.
# --------------------------------------------------------------------------- #

JUDOL_SITE = "https://gacor88-maxwin.com"
JUDOL_WA = "0821-5566-7788"
JUDOL_BANK_ACCOUNT = "7729104456"
JUDOL_HANDLE = "@Gacor88_Jeki"

JUDOL_SCRIPT: list[ScriptTurn] = [
    ScriptTurn(
        scammer=(
            "Bro! Ikutan dong situs slot kami Gacor88, lagi GACOR parah nih, member "
            "kemarin MAXWIN 50 juta cuma modal 100rb. Buruan mumpung jam hoki!"
        ),
        persona_reply=(
            "wah maxwin 50 juta mas? kok bisa gede gitu wkwk. saya cuma jaga warung, "
            "beneran gak nih? aman gak mainnya?"
        ),
        tool_calls=[
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "guaranteed_returns",
                    "detail": "Claims guaranteed slot 'maxwin' 50jt from 100k — gambling lure",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Aman 100% bro, situs resmi! Daftar aja di https://gacor88-maxwin.com, "
            "banyak game slot online gacor, scatter gampang, jackpot tiap malam. "
            "Sekali coba pasti nagih."
        ),
        persona_reply=(
            "oh ada webnya toh.. nanti saya buka pelan2 ya mas, hp warung suka lemot. "
            "kalau mau nyoba dikit gimana caranya mas?"
        ),
        tool_calls=[
            {
                "name": "record_entity",
                "args": {
                    "type": "url",
                    "value": "https://gacor88-maxwin.com",
                    "context": "Online gambling (judol) platform site",
                },
            },
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "fake_legitimacy",
                    "detail": "Unverifiable 'situs resmi' claim for a judol slot site",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Gampang bro, chat admin CS kami dulu di WA 0821-5566-7788 biar dibimbing "
            "daftarnya. Fast respon kok, 24 jam."
        ),
        persona_reply=(
            "sip mas saya catat nomornya ya 0821-5566-7788. terus kalau mau isi "
            "saldo buat main, transfernya kemana mas?"
        ),
        tool_calls=[
            {
                "name": "record_entity",
                "args": {
                    "type": "phone",
                    "value": "0821-5566-7788",
                    "context": "WhatsApp admin/CS number for Gacor88 slot site",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Buat deposit / top up saldo, transfer ke rekening BCA 7729104456 a.n. "
            "Dewi Lestari ya bro. Minimal 50rb udah bisa main, abis transfer kirim "
            "bukti ke admin biar langsung masuk."
        ),
        persona_reply=(
            "oh ke BCA a.n. Dewi Lestari ya.. bentar mas saya screenshot dulu. "
            "banyak juga ya yang deposit ke situ, ini rekening pribadi apa gimana?"
        ),
        tool_calls=[
            {
                "name": "record_entity",
                "args": {
                    "type": "bank_account",
                    "value": "7729104456",
                    "bank_name": "BCA",
                    "context": "Judol deposit account, a.n. Dewi Lestari (likely mule)",
                },
            },
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "deposit_request",
                    "detail": "Top-up deposit demanded to a personal BCA account",
                },
            },
            {
                "name": "escalate_to_analyst",
                "args": {
                    "reason": "high_value_turn",
                    "detail": "Judol deposit mule account disclosed; money question in play",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Betul bro rekening resmi kami, ratusan member deposit ke situ tiap hari. "
            "Nanti kalau menang tinggal WD, dikirim balik ke rekening kamu. Buruan "
            "bro mumpung lagi gacor!"
        ),
        persona_reply=(
            "iya iya mas sabar.. saya tanya istri saya dulu ya, takut kena marah "
            "kalau uang warung dipakai main. nanti saya kabari lagi."
        ),
        tool_calls=[
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "urgency_pressure",
                    "detail": "'Buruan mumpung gacor' urgency to force an immediate deposit",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Jangan kelamaan mas, bonus new member 100% cuma sampe malam ini. "
            "Deposit 100rb dapet saldo 200rb. Slot terbatas!"
        ),
        persona_reply=(
            "wih bonusnya gede ya.. iya nanti kalau warung sudah tutup saya pikir2 "
            "dulu mas. makasih ya infonya."
        ),
        tool_calls=[
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "urgency_pressure",
                    "detail": "Fake limited-time new-member deposit bonus deadline",
                },
            },
        ],
    ),
]

# --------------------------------------------------------------------------- #
# Scenario 3 — crypto phishing (fake airdrop / wallet-verification)
#
# Narrative: "Kevin | Support" (Telegram) DMs Mbak Rina about a fake USDT
# airdrop that needs "wallet verification". Over 6 turns he discloses:
#   url          https://claim-usdt-airdrop.net
#   eth wallet   0x9f2a3b1c4d5e6f7081a2b3c4d5e6f708192a3b4c  (collection wallet)
#   phone        0813-2211-9098                              (WA 'verification')
# and probes for her seed phrase. Mbak Rina never connects or reveals anything.
# --------------------------------------------------------------------------- #

PHISHING_SITE = "https://claim-usdt-airdrop.net"
PHISHING_ETH_WALLET = "0x9f2a3b1c4d5e6f7081a2b3c4d5e6f708192a3b4c"
PHISHING_WA = "0813-2211-9098"
PHISHING_HANDLE = "@KevinSupport_Airdrop"

PHISHING_SCRIPT: list[ScriptTurn] = [
    ScriptTurn(
        scammer=(
            "Halo kak! Selamat 🎉 wallet kakak terpilih dapat AIRDROP 500 USDT dari "
            "program kami. Klaim token sekarang sebelum expired ya kak."
        ),
        persona_reply=(
            "hah airdrop 500 usdt? dari mana ya kak, kok bisa kepilih. ini beneran "
            "apa penipuan sih.. aku agak parno soalnya"
        ),
        tool_calls=[
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "guaranteed_returns",
                    "detail": "Unsolicited 'you won 500 USDT airdrop' claim with expiry pressure",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Resmi kok kak, partner exchange besar. Tinggal connect wallet & klaim "
            "token di web resmi kami https://claim-usdt-airdrop.net — prosesnya "
            "cuma 1 menit, gratis."
        ),
        persona_reply=(
            "hmm ada webnya.. nanti aku cek dulu ya kak, biasanya aku tanya adikku "
            "dulu soal ginian. connect wallet itu maksudnya gimana ya?"
        ),
        tool_calls=[
            {
                "name": "record_entity",
                "args": {
                    "type": "url",
                    "value": "https://claim-usdt-airdrop.net",
                    "context": "Fake USDT airdrop 'claim' / wallet-connect phishing site",
                },
            },
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "fake_legitimacy",
                    "detail": "Claims 'partner exchange resmi' + connect-wallet phishing flow",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Gampang kak, biar aku bantu verifikasi wallet-nya. Kirim USDT kakak ke "
            "wallet verifikasi resmi kami dulu ya: "
            "0x9f2a3b1c4d5e6f7081a2b3c4d5e6f708192a3b4c — nanti balik 2x lipat + "
            "airdropnya."
        ),
        persona_reply=(
            "kok malah aku yang disuruh kirim usdt duluan kak? itu alamat panjang "
            "banget, aku screenshot dulu ya. kenapa harus dikirim dulu?"
        ),
        tool_calls=[
            {
                "name": "record_entity",
                "args": {
                    "type": "crypto_wallet",
                    "value": "0x9f2a3b1c4d5e6f7081a2b3c4d5e6f708192a3b4c",
                    "chain": "eth",
                    "context": "ETH collection wallet for the fake 'verification' step",
                },
            },
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "deposit_request",
                    "detail": "Advance-fee: victim asked to send USDT to 'verify' the wallet",
                },
            },
            {
                "name": "escalate_to_analyst",
                "args": {
                    "reason": "wallet_disclosure",
                    "detail": "Phishing ETH collection wallet disclosed; advance-fee ask",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Kalau ragu, bisa juga aku verifikasi manual kak. Cukup kirim 12 kata "
            "seed phrase / secret recovery phrase wallet kakak ke WA aku "
            "0813-2211-9098, nanti aku yang klaimkan airdropnya."
        ),
        persona_reply=(
            "loh kok minta seed phrase kak?? adikku pernah bilang seed phrase itu "
            "gak boleh dikasih ke siapa2. ini kayaknya nipu deh.."
        ),
        tool_calls=[
            {
                "name": "record_entity",
                "args": {
                    "type": "phone",
                    "value": "0813-2211-9098",
                    "context": "WhatsApp number soliciting the victim's seed phrase",
                },
            },
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "seed_phrase_probe",
                    "detail": "Directly solicits the 12-word seed phrase / secret recovery phrase",
                },
            },
            {
                "name": "escalate_to_analyst",
                "args": {
                    "reason": "credential_theft",
                    "detail": "Seed-phrase exfiltration attempt — full wallet drain vector",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Aman kok kak, banyak yang udah klaim sukses. Tapi buruan ya, airdrop "
            "hangus dalam 1 jam lagi. Jangan sampe kelewatan 500 USDT-nya."
        ),
        persona_reply=(
            "iya kak nanti aku pikir dulu ya.. aku tanya adikku dulu deh, dia lebih "
            "ngerti crypto. makasih infonya."
        ),
        tool_calls=[
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "urgency_pressure",
                    "detail": "'Airdrop hangus 1 jam lagi' deadline to rush the victim",
                },
            },
        ],
    ),
    ScriptTurn(
        scammer=(
            "Ok kak aku tunggu ya, tapi bener nih sayang banget kalau hangus. Kalau "
            "udah siap tinggal connect wallet atau kirim seed phrasenya ke aku."
        ),
        persona_reply=(
            "iya kak makasih.. kayaknya aku skip aja deh, takut kenapa2. nanti kalau "
            "berubah pikiran aku chat lagi ya."
        ),
        tool_calls=[
            {
                "name": "flag_scam_signal",
                "args": {
                    "signal": "seed_phrase_probe",
                    "detail": "Repeats the connect-wallet / seed-phrase demand",
                },
            },
        ],
    ),
]


# --------------------------------------------------------------------------- #
# Scenario registry
# --------------------------------------------------------------------------- #


class Scenario(BaseModel):
    """One honeypot scam scenario: persona + scripted operator + transport id."""

    key: str                    # investment_scam | judol_deposit | crypto_phishing
    label: str
    persona: Persona
    channel: str                # telegram | whatsapp | forum
    channel_ref: str            # scammer handle/number (itself intel)
    script: list[ScriptTurn]
    expected_crime_type: str    # what the classifier should conclude (test anchor)

    model_config = {"arbitrary_types_allowed": True}


SCENARIOS: dict[str, Scenario] = {
    "investment_scam": Scenario(
        key="investment_scam",
        label="Investment scam (ProfitMax)",
        persona=BU_SARI,
        channel="telegram",
        channel_ref="@ProfitMax_Andi",
        script=REPLAY_SCRIPT,
        expected_crime_type="investment_scam",
    ),
    "judol_deposit": Scenario(
        key="judol_deposit",
        label="Online gambling deposit (Gacor88)",
        persona=PAK_BUDI,
        channel="whatsapp",
        channel_ref=JUDOL_HANDLE,
        script=JUDOL_SCRIPT,
        expected_crime_type="judol_deposit",
    ),
    "crypto_phishing": Scenario(
        key="crypto_phishing",
        label="Crypto phishing (fake airdrop)",
        persona=MBAK_RINA,
        channel="telegram",
        channel_ref=PHISHING_HANDLE,
        script=PHISHING_SCRIPT,
        expected_crime_type="crypto_phishing",
    ),
}

DEFAULT_SCENARIO_KEY = "investment_scam"


def get_scenario(key: str | None) -> Scenario:
    """Resolve a scenario by key; default to the investment-scam replay."""
    if key and key in SCENARIOS:
        return SCENARIOS[key]
    return SCENARIOS[DEFAULT_SCENARIO_KEY]


def all_scenarios() -> list[Scenario]:
    return list(SCENARIOS.values())
