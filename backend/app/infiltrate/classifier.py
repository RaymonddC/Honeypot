"""Crime Classifier — investment_scam / judol_deposit / crypto_phishing / … .

POC: deterministic keyword + scam-signal rules over the transcript (offline).
LIVE: an LLM classifier with validation (docs/INFILTRATE-Design.md §6, target
>80% accuracy). Same return shape either mode.
"""

import re
from dataclasses import dataclass, field

CRIME_TYPES = ("investment_scam", "judol_deposit", "crypto_phishing", "romance_scam", "other")

# Weighted keyword cues per crime type (lowercased, word-ish match).
_CUES: dict[str, list[tuple[str, float]]] = {
    "investment_scam": [
        ("investasi", 2.0), ("profit", 1.5), ("per hari", 2.0), ("keuntungan", 1.5),
        ("dijamin", 1.5), ("member", 1.0), ("deposit", 1.0), ("slot", 1.0),
        ("trading", 1.5), ("modal", 1.0), ("roi", 1.5), ("bunga", 1.0),
    ],
    "judol_deposit": [
        ("judi", 2.5), ("judol", 2.5), ("slot online", 2.5), ("gacor", 2.5),
        ("maxwin", 2.5), ("taruhan", 2.0), ("bonus deposit", 1.5), ("scatter", 2.0),
        ("bet", 1.0), ("jackpot", 1.5),
    ],
    "crypto_phishing": [
        ("seed phrase", 3.0), ("private key", 3.0), ("wallet anda", 1.5),
        ("verifikasi wallet", 2.5), ("airdrop", 2.0), ("metamask", 2.0),
        ("connect wallet", 2.5), ("klaim token", 2.0),
    ],
    "romance_scam": [
        ("sayang", 1.5), ("cinta", 1.5), ("jodoh", 2.0), ("kesepian", 1.5),
        ("rindu", 1.5), ("menikah", 2.0),
    ],
}

# Scam-signal boosts (from the agent loop's flag_scam_signal tool).
_SIGNAL_BOOST: dict[str, dict[str, float]] = {
    "guaranteed_returns": {"investment_scam": 2.0},
    "deposit_request": {"investment_scam": 1.0, "judol_deposit": 1.0},
    "fake_legitimacy": {"investment_scam": 1.0, "crypto_phishing": 0.5},
    "urgency_pressure": {"investment_scam": 0.5, "judol_deposit": 0.5},
    # Seed-phrase / secret-recovery exfiltration is the crypto-phishing tell.
    "seed_phrase_probe": {"crypto_phishing": 3.0},
}


@dataclass
class Classification:
    crime_type: str
    confidence: float
    model_version: str = "poc-rules-1"
    signals: list[str] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)


def _word_hits(text: str, cue: str) -> int:
    return len(re.findall(re.escape(cue), text))


def classify(
    transcript: str,
    scam_signals: list[dict] | None = None,
    entity_types: list[str] | None = None,
) -> Classification:
    """Classify the conversation deterministically (POC).

    ``scam_signals`` are the ``flag_scam_signal`` dicts; ``entity_types`` the
    reconciled extracted entity types (a crypto_wallet nudges crypto typologies).
    """
    text = transcript.lower()
    scores: dict[str, float] = {k: 0.0 for k in CRIME_TYPES if k != "other"}

    for crime, cues in _CUES.items():
        for cue, weight in cues:
            scores[crime] += _word_hits(text, cue) * weight

    signals = [s.get("signal", "") for s in (scam_signals or [])]
    for sig in signals:
        for crime, boost in _SIGNAL_BOOST.get(sig, {}).items():
            scores[crime] += boost

    # A disclosed crypto wallet reinforces crypto-adjacent typologies.
    if entity_types and "crypto_wallet" in entity_types:
        scores["investment_scam"] += 0.5
        scores["crypto_phishing"] += 0.5

    top = max(scores, key=scores.get)
    top_score = scores[top]
    if top_score <= 0:
        return Classification(
            crime_type="other", confidence=0.3, signals=signals, scores=scores
        )

    total = sum(v for v in scores.values() if v > 0)
    # Confidence = dominance of the top class, floored so a clear winner reads high.
    share = top_score / total if total else 0.0
    confidence = round(min(0.98, 0.55 + share * 0.45), 3)
    return Classification(
        crime_type=top, confidence=confidence, signals=signals, scores=scores
    )
