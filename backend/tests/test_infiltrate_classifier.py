"""Crime classifier — deterministic rules over transcript + scam signals."""

from app.infiltrate import classifier
from app.infiltrate.channels import REPLAY_SCRIPT


def test_investment_scam_from_replay():
    transcript = " ".join(t.scammer for t in REPLAY_SCRIPT)
    signals = [
        {"signal": "guaranteed_returns"}, {"signal": "deposit_request"},
        {"signal": "fake_legitimacy"}, {"signal": "urgency_pressure"},
    ]
    c = classifier.classify(transcript, signals, ["crypto_wallet", "bank_account"])
    assert c.crime_type == "investment_scam"
    assert c.confidence >= 0.8            # proposal KPI: >80%
    assert c.model_version == "poc-rules-1"


def test_judol_deposit_detected():
    c = classifier.classify("ayo main slot online gacor maxwin bonus deposit taruhan jackpot")
    assert c.crime_type == "judol_deposit"


def test_crypto_phishing_detected():
    c = classifier.classify("verifikasi wallet anda, masukkan seed phrase untuk klaim airdrop token")
    assert c.crime_type == "crypto_phishing"


def test_empty_transcript_is_other_low_confidence():
    c = classifier.classify("halo apa kabar")
    assert c.crime_type == "other"
    assert c.confidence < 0.5


def test_signals_included_in_result():
    c = classifier.classify("investasi profit per hari dijamin", [{"signal": "guaranteed_returns"}])
    assert "guaranteed_returns" in c.signals
