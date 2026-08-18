"""Counterparty exposure scoring (app/takedown/exposure.py).

Our scoring asked "how does this wallet behave?" and "is it itself tagged?".
Established blockchain-analytics practice asks a third question we never did:
**who did it transact with, and how closely?** — direct exposure weighted
heavily, indirect decaying by hop, scaled by value share, with category
severity (sanctions top, gambling weak).

The concrete gap that closed: a fresh mule one hop from a known scam address,
holding nothing but its money, previously scored LOW because it had no
laundering pattern *of its own* yet. That is the normal shape of a first-hop
mule and exactly the wallet an investigator wants surfaced.
"""

import pytest

from app.chain.schemas import AddressTagOut, Transfer
from app.takedown.exposure import CATEGORY_SEVERITY, compute_exposure
from app.takedown.scoring import composite_risk


def _tag(address: str, category: str, tag: str = "t") -> AddressTagOut:
    return AddressTagOut(
        address=address, tag=tag, category=category, source="test", confidence=1.0
    )


def _tx(frm: str, to: str, value: float, ts: str = "2026-01-01T00:00:00Z") -> Transfer:
    return Transfer(
        tx_hash=f"{frm}->{to}-{value}", chain="tron", from_addr=frm, to_addr=to,
        value=value, ts=ts,
    )


def _lookup(tags: dict[str, AddressTagOut]):
    return lambda address: [tags[address]] if address in tags else []


def test_direct_exposure_to_a_scam_source_is_detected():
    """The case that motivated this: a mule with NO pattern of its own."""
    tags = _lookup({"SCAM": _tag("SCAM", "scam")})
    result = compute_exposure("MULE", [_tx("SCAM", "MULE", 100)], tags)

    assert result.hops == 1
    assert result.category == "scam"
    assert result.value_share == 1.0
    assert result.severity == pytest.approx(CATEGORY_SEVERITY["scam"])  # full weight at 1 hop


def test_indirect_exposure_decays_with_distance():
    """Direct dealing is a strong claim; by several hops the funds have
    plausibly passed through parties with no knowledge of the origin, and
    treating those alike is how false positives are manufactured."""
    tags = _lookup({"SCAM": _tag("SCAM", "scam")})
    chain = [_tx("SCAM", "A", 100), _tx("A", "B", 100), _tx("B", "C", 100)]

    one = compute_exposure("A", chain, tags).severity
    two = compute_exposure("B", chain, tags).severity
    three = compute_exposure("C", chain, tags).severity

    assert one > two > three > 0, (one, two, three)


def test_category_severity_is_ordered_sanctions_first():
    """Sanctions top the scale; gambling is a real but weak signal; an exchange
    is not illicit at all — a wallet sending to one is cashing out, which is
    where investigations LEAD, not evidence against the sender."""
    assert CATEGORY_SEVERITY["sanctioned"] > CATEGORY_SEVERITY["scam"]
    assert CATEGORY_SEVERITY["scam"] > CATEGORY_SEVERITY["mixer"]
    assert CATEGORY_SEVERITY["mixer"] > CATEGORY_SEVERITY["gambling"]
    assert CATEGORY_SEVERITY["exchange"] == 0.0
    assert CATEGORY_SEVERITY["service"] == 0.0


def test_value_share_scales_exposure_but_never_erases_it():
    """A wallet funded 95% by a scam source is a different fact from one that
    received a single dust transaction — but dust from a sanctioned address
    still matters, so the share floors rather than zeroing the signal."""
    tags = _lookup({"SCAM": _tag("SCAM", "scam")})
    mostly = compute_exposure("A", [_tx("SCAM", "A", 95), _tx("CLEAN", "A", 5)], tags)
    dust = compute_exposure("B", [_tx("SCAM", "B", 1), _tx("CLEAN", "B", 999)], tags)

    assert mostly.severity > dust.severity
    assert dust.severity > 0, "dust from a tagged source must not vanish"


def test_exposure_takes_the_worst_link_not_a_sum():
    """Summing lets a scattering of weak associations imitate one damning direct
    link, and makes the score depend on how much unrelated history a wallet
    happens to have — which is not a property of its risk."""
    tags = _lookup({
        "SCAM": _tag("SCAM", "scam"),
        "GAMBLE1": _tag("GAMBLE1", "gambling"),
        "GAMBLE2": _tag("GAMBLE2", "gambling"),
    })
    transfers = [_tx("GAMBLE1", "W", 50), _tx("GAMBLE2", "W", 50), _tx("SCAM", "W", 50)]
    result = compute_exposure("W", transfers, tags)

    assert result.category == "scam", "the worst single link should drive the score"
    assert result.severity <= CATEGORY_SEVERITY["scam"]


def test_clean_wallet_has_no_exposure():
    tags = _lookup({"EXCH": _tag("EXCH", "exchange")})
    assert compute_exposure("W", [_tx("EXCH", "W", 100)], tags).severity == 0.0


def test_a_sanctioned_wallet_is_high_regardless_of_behaviour():
    """The defect this fixes (docs/Wallet-Risk-Scoring-Rules.md §4): sanctions
    used to add +0.25 to a score, so an OFAC-listed wallet with no detected
    pattern came out LOW while its own reasoning named the SDN listing.

    Transacting with a listed party is an offence regardless of typology, so it
    is a floor, not a term to be averaged.
    """
    level, confidence, reasoning = composite_risk(
        0.0, [], [_tag("W", "sanctioned", "OFAC SDN")]
    )
    assert level == "high"
    assert confidence >= 0.9
    assert "SANCTIONED" in reasoning[0]


def test_a_first_hop_mule_is_surfaced_even_with_no_patterns():
    """End to end: exposure alone lifts a behaviourally-clean mule off the floor.

    Not straight to high — association is weaker evidence than observed
    behaviour, and an innocent recipient of scam funds exists. Medium means
    "investigate", which is the correct disposition.
    """
    exposure = compute_exposure(
        "MULE", [_tx("SCAM", "MULE", 100)], _lookup({"SCAM": _tag("SCAM", "scam")})
    )
    level, _confidence, reasoning = composite_risk(0.0, [], [], exposure)

    assert level == "medium", "a first-hop mule must not sit at low"
    assert any("exposure" in r.lower() for r in reasoning)
