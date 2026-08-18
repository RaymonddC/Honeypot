"""Counterparty exposure — the signal our scoring was missing entirely.

**Why this exists.** Our risk score asked "how does this wallet *behave*?"
(5 typology detectors + an anomaly score) and, for attribution, only "is this
wallet *itself* tagged?". The established methodology in this field asks a third
question we never asked: **who did it transact with, and how closely?**

That is *exposure*, and it is the backbone of how commercial blockchain-analytics
tools score an address:

* **Direct exposure** (funds received straight from a known-illicit address)
  carries the strongest weight; **indirect exposure** through intermediaries
  carries far less, decaying with hop distance.
* **Category severity** differs — sanctions sit at the top; gambling and
  unregulated services are much weaker signals.
* **Value share** matters — 90% of a wallet's inflow arriving from a scam
  cluster is a different fact from a single dust transaction.

Missing this meant a fresh mule wallet — one hop from a known scam address,
holding nothing but its money — scored **low**, because it had no laundering
*pattern of its own* yet. That is precisely the wallet an investigator most
wants surfaced, and it is the normal shape of a first-hop mule.

**What this is not.** It does not replace the typology detectors. Those carry
the court-explainable signal ("this wallet peeled 70% across three hops");
exposure carries the network signal ("and it received 90% of its funds directly
from a sanctions-listed address"). Both belong in the score, and each is
reported separately in the reasoning so a reader can see which did the work.
"""

from dataclasses import dataclass, field

from app.chain.schemas import AddressTagOut, Transfer

# How dangerous is an association with each tagged category?
#
# Ordering follows standard AML practice: sanctions are the top of the scale
# because dealing with a listed party is an offence in itself, not a risk to be
# weighed. Gambling and unregulated services are real signals but weak ones —
# they correlate with laundering without implying it. Exchanges and services are
# NOT illicit: a wallet sending to an exchange is cashing out, which is where
# investigations *lead*, not evidence against the sender.
CATEGORY_SEVERITY: dict[str, float] = {
    "sanctioned": 1.0,
    "scam": 0.8,
    "mixer": 0.6,
    "gambling": 0.3,
    "exchange": 0.0,
    "service": 0.0,
    "unknown": 0.0,
}

# Weight by distance. Direct dealing is a strong claim; by three hops the funds
# have plausibly passed through parties with no knowledge of the origin, and
# treating that as equivalent is how false positives are manufactured.
HOP_WEIGHT: dict[int, float] = {1: 1.0, 2: 0.4, 3: 0.15}
MAX_EXPOSURE_HOPS = 3


@dataclass
class ExposureResult:
    """The single strongest illicit association found, plus how it was reached."""

    severity: float = 0.0          # 0..1 after category, hop and value weighting
    category: str = ""             # which tagged category drove it
    counterparty: str = ""         # the tagged address
    hops: int = 0                  # 0 = the wallet itself is tagged
    value_share: float = 0.0       # fraction of this wallet's inflow from that source
    self_tagged: bool = False      # the wallet IS the listed party, not merely near one
    reasoning: list[str] = field(default_factory=list)


def _inflow_by_source(address: str, transfers: list[Transfer]) -> tuple[dict[str, float], float]:
    """Value this address received, per direct sender, plus its total inflow."""
    by_source: dict[str, float] = {}
    total = 0.0
    for t in transfers:
        if t.to_addr == address:
            by_source[t.from_addr] = by_source.get(t.from_addr, 0.0) + float(t.value)
            total += float(t.value)
    return by_source, total


def compute_exposure(
    address: str,
    transfers: list[Transfer],
    tags_lookup,
    *,
    max_hops: int = MAX_EXPOSURE_HOPS,
) -> ExposureResult:
    """Strongest illicit exposure for ``address``, weighted by category, hops and value.

    Takes the **maximum** rather than a sum: summing lets a scattering of weak,
    distant associations add up to a score that looks like one damning direct
    one, and an analyst reasons about the worst single exposure ("your biggest
    exposure is a sanctioned address, one hop, 90% of inflow"). Summation would
    also make the score depend on how much unrelated history a wallet happens to
    have, which is not a property of its risk.
    """
    result = ExposureResult()

    # 0 hops: the wallet is itself listed. Reported separately from proximity,
    # because "you ARE the sanctioned party" is a categorically different claim
    # from "you dealt with one" — see the band floor in scoring.composite_risk.
    for tag in tags_lookup(address) or []:
        severity = CATEGORY_SEVERITY.get(tag.category, 0.0)
        if severity > result.severity:
            result = ExposureResult(
                severity=severity, category=tag.category, counterparty=address,
                hops=0, value_share=1.0, self_tagged=True,
                reasoning=[
                    f"This address is itself tagged '{tag.tag}' ({tag.category}, "
                    f"source={tag.source})."
                ],
            )

    # 1..max_hops: walk backwards through who funded this wallet.
    inflow, total_in = _inflow_by_source(address, transfers)
    if total_in <= 0:
        return result

    frontier = {src: value / total_in for src, value in inflow.items()}
    seen = {address}
    for hop in range(1, max_hops + 1):
        hop_weight = HOP_WEIGHT.get(hop, 0.0)
        if not frontier or hop_weight == 0.0:
            break
        next_frontier: dict[str, float] = {}
        for counterparty, share in frontier.items():
            if counterparty in seen:
                continue
            seen.add(counterparty)
            for tag in tags_lookup(counterparty) or []:
                base = CATEGORY_SEVERITY.get(tag.category, 0.0)
                if base == 0.0:
                    continue
                # Value share scales the claim without erasing it: a 1% dust
                # transfer from a sanctioned address still matters, so the share
                # floors at 0.25 rather than driving severity to nothing.
                weighted = base * hop_weight * max(share, 0.25)
                if weighted > result.severity:
                    result = ExposureResult(
                        severity=round(weighted, 3), category=tag.category,
                        counterparty=counterparty, hops=hop,
                        value_share=round(share, 3), self_tagged=False,
                        reasoning=[
                            f"{'Direct' if hop == 1 else f'Indirect ({hop} hops)'} exposure: "
                            f"received {share:.0%} of inflow via {counterparty[:12]}…, "
                            f"tagged '{tag.tag}' ({tag.category})."
                        ],
                    )
            # Keep walking back: who funded THIS counterparty?
            upstream, upstream_total = _inflow_by_source(counterparty, transfers)
            if upstream_total > 0:
                for src, value in upstream.items():
                    contribution = share * (value / upstream_total)
                    next_frontier[src] = next_frontier.get(src, 0.0) + contribution
        frontier = next_frontier

    return result
