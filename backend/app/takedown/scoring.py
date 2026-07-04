"""TAKEDOWN risk scoring — Isolation Forest triage + 5 deterministic typology
detectors → composite risk with Glass Box reasoning.

IF is anomaly *triage*, not a fraud classifier; the deterministic detectors +
attribution overlay carry the court-explainable signal (docs/TAKEDOWN-Design.md).
"""

from typing import Literal

import networkx as nx
import numpy as np
from pydantic import BaseModel
from sklearn.ensemble import IsolationForest

from app.chain.schemas import AddressTagOut, Transfer
from app.takedown.features import FEATURE_ORDER, FeatureVector, compute_features
from app.takedown.graph import build_digraph, hop_depths

MODEL_VERSION = "takedown-0.1.0/iforest-c0.05+5typologies"

# Detector thresholds (deterministic, explainable)
PEEL_FORWARD_SHARE = 0.7  # dominant hop forwards ≥70% of inflow
PEEL_MIN_HOPS = 2
RAPID_INOUT_MIN = 0.95  # near-pure pass-through
RAPID_RELAY_MIN = 0.5  # ≥half of inflow forwarded ≤5 min
STRUCTURING_MIN_CLUSTER = 3  # ≥3 similar-amount transfers
STRUCTURING_TOLERANCE = 0.05  # within ±5%
FAN_OUT_MIN = 10  # 1 input wallet → 10+ outputs
CYCLE_LENGTH_BOUND = 6

# Volume-scale features are log-scaled so IF isn't dominated by magnitude.
_LOG_SCALE = {"total_volume", "mean_volume", "max_tx_size"}
_LOG_IDX = [i for i, name in enumerate(FEATURE_ORDER) if name in _LOG_SCALE]


class PatternResult(BaseModel):
    name: str
    fired: bool
    score: float  # 0..1 strength
    evidence: dict
    description: str


class WalletScore(BaseModel):
    address: str
    chain: str = "tron"
    iso_forest_score: float  # 0..1 anomaly triage
    patterns: list[PatternResult]
    composite_risk: Literal["low", "medium", "high"]
    confidence: float
    reasoning: list[str]  # Glass Box — explicit, human-readable
    features: FeatureVector
    tags: list[AddressTagOut] = []
    model_version: str = MODEL_VERSION


# --- The 5 typology detectors ------------------------------------------------


def detect_peeling_chain(address: str, transfers: list[Transfer]) -> PatternResult:
    """Sequential chain: each hop forwards most value on, peeling a little off."""
    outflows: dict[str, list[Transfer]] = {}
    inflow_total: dict[str, float] = {}
    for t in transfers:
        outflows.setdefault(t.from_addr, []).append(t)
        inflow_total[t.to_addr] = inflow_total.get(t.to_addr, 0.0) + t.value

    hops: list[dict] = []
    cur, visited = address, {address}
    for _ in range(6):
        outs = outflows.get(cur, [])
        inflow = inflow_total.get(cur, 0.0)
        if not outs or inflow <= 0:
            break
        top = max(outs, key=lambda t: t.value)
        share = top.value / inflow
        if share < PEEL_FORWARD_SHARE or top.to_addr in visited:
            break
        peeled = sum(t.value for t in outs) - top.value
        hops.append(
            {
                "from": top.from_addr,
                "to": top.to_addr,
                "tx_hash": top.tx_hash,
                "forwarded": top.value,
                "forward_share": round(share, 4),
                "peeled_off": round(peeled, 2),
            }
        )
        visited.add(top.to_addr)
        cur = top.to_addr

    fired = len(hops) >= PEEL_MIN_HOPS
    return PatternResult(
        name="peeling_chain",
        fired=fired,
        score=min(len(hops) / 3, 1.0) if fired else 0.0,
        evidence={"hops": hops},
        description=(
            f"{len(hops)}-hop chain forwarding ≥{PEEL_FORWARD_SHARE:.0%} of inflow "
            "per hop while peeling small amounts off"
            if fired
            else "no sequential majority-forward chain from this wallet"
        ),
    )


def detect_rapid_relay(
    address: str, transfers: list[Transfer], features: FeatureVector
) -> PatternResult:
    """Funds forwarded within ~5 minutes; in/out ratio > 0.95 (pass-through)."""
    fired = (
        features.inout_ratio > RAPID_INOUT_MIN
        and features.inout_ratio <= 1.05  # forwarding, not net-emitting
        and features.rapid_relay_rate >= RAPID_RELAY_MIN
    )
    pairs = []
    if fired:
        inbound = [t for t in transfers if t.to_addr == address]
        outbound = [t for t in transfers if t.from_addr == address]
        for t in inbound:
            for o in outbound:
                delta = (o.ts - t.ts).total_seconds()
                if 0 <= delta <= 300:
                    pairs.append(
                        {"in_tx": t.tx_hash, "out_tx": o.tx_hash, "delta_seconds": delta}
                    )
    return PatternResult(
        name="rapid_relay",
        fired=fired,
        score=features.rapid_relay_rate if fired else 0.0,
        evidence={
            "inout_ratio": round(features.inout_ratio, 4),
            "rapid_relay_rate": round(features.rapid_relay_rate, 4),
            "relay_pairs": pairs[:10],
        },
        description=(
            f"{features.rapid_relay_rate:.0%} of inflow forwarded within 5 minutes at "
            f"in/out ratio {features.inout_ratio:.3f} (near-pure pass-through)"
            if fired
            else "no rapid pass-through behaviour"
        ),
    )


def detect_circular(address: str, g: nx.MultiDiGraph) -> PatternResult:
    """Cycles through the wallet (wash / mixing), via NetworkX simple_cycles."""
    cycles = [
        cycle
        for cycle in nx.simple_cycles(nx.DiGraph(g), length_bound=CYCLE_LENGTH_BOUND)
        if address in cycle and len(cycle) >= 2
    ]
    fired = bool(cycles)
    return PatternResult(
        name="circular",
        fired=fired,
        score=min(len(cycles) / 2, 1.0) if fired else 0.0,
        evidence={"cycles": cycles[:5]},
        description=(
            f"wallet participates in {len(cycles)} transaction cycle(s) "
            f"(e.g. {' → '.join(cycles[0] + [cycles[0][0]])})"
            if fired
            else "no transaction cycles through this wallet"
        ),
    )


def detect_structuring(address: str, transfers: list[Transfer]) -> PatternResult:
    """Clusters of similar-amount transfers (just-under-threshold / round)."""
    own = sorted(
        (t for t in transfers if address in (t.from_addr, t.to_addr)),
        key=lambda t: t.value,
    )
    best: list[Transfer] = []
    i = 0
    for j in range(len(own)):
        while own[j].value > own[i].value * (1 + STRUCTURING_TOLERANCE):
            i += 1
        if j - i + 1 > len(best):
            best = own[i : j + 1]
    fired = len(best) >= STRUCTURING_MIN_CLUSTER
    return PatternResult(
        name="structuring",
        fired=fired,
        score=min(len(best) / 10, 1.0) if fired else 0.0,
        evidence={
            "cluster_size": len(best),
            "amounts": sorted({t.value for t in best}),
            "tx_hashes": [t.tx_hash for t in best[:10]],
        },
        description=(
            f"{len(best)} transfers of near-identical amounts "
            f"(~{best[0].value:,.0f} USDT) — smurfing signature"
            if fired
            else "no similar-amount transfer clusters"
        ),
    )


def detect_fan_out(address: str, transfers: list[Transfer]) -> PatternResult:
    """One input wallet dispersing to 10+ output wallets (mule dispersal)."""
    receivers = {t.to_addr for t in transfers if t.from_addr == address}
    fired = len(receivers) >= FAN_OUT_MIN
    return PatternResult(
        name="fan_out",
        fired=fired,
        score=min(len(receivers) / 20, 1.0) if fired else 0.0,
        evidence={"unique_receivers": len(receivers), "receivers": sorted(receivers)[:20]},
        description=(
            f"disperses funds to {len(receivers)} distinct wallets"
            if fired
            else f"only {len(receivers)} outbound counterparties"
        ),
    )


# --- Isolation Forest triage --------------------------------------------------


def iso_forest_scores(features: dict[str, FeatureVector]) -> dict[str, float]:
    """Anomaly score 0..1 per wallet (population = this investigation)."""
    addresses = list(features)
    X = np.array([features[a].as_row() for a in addresses])
    if len(addresses) < 2:
        return {a: 0.0 for a in addresses}
    X[:, _LOG_IDX] = np.log1p(X[:, _LOG_IDX])  # tame volume magnitudes
    model = IsolationForest(contamination=0.05, random_state=42)
    model.fit(X)
    raw = -model.decision_function(X)  # higher = more anomalous
    lo, hi = raw.min(), raw.max()
    norm = (raw - lo) / (hi - lo) if hi > lo else np.zeros_like(raw)
    return {a: float(s) for a, s in zip(addresses, norm)}


# --- Composite ------------------------------------------------------------


def composite_risk(
    iso_score: float, patterns: list[PatternResult], tags: list[AddressTagOut]
) -> tuple[Literal["low", "medium", "high"], float, list[str]]:
    """Combine IF triage + fired typologies + attribution → risk/confidence/reasoning."""
    fired = [p for p in patterns if p.fired]
    categories = {t.category for t in tags}
    reasoning: list[str] = []

    score = 0.25 * iso_score + 0.75 * min(len(fired) / 2, 1.0)
    if "scam" in categories or "sanctioned" in categories:
        score = min(score + 0.25, 1.0)
    if "mixer" in categories:
        score = min(score + 0.15, 1.0)

    if iso_score >= 0.7:
        reasoning.append(
            f"Isolation Forest flags this wallet as a statistical outlier "
            f"(anomaly score {iso_score:.2f}) within the investigation population."
        )
    for p in fired:
        reasoning.append(f"Pattern [{p.name}] fired: {p.description}.")
    for t in tags:
        reasoning.append(
            f"Attribution: tagged '{t.tag}' ({t.category}, source={t.source}, "
            f"confidence={t.confidence})."
        )

    # A known exchange with no criminal patterns is a destination, not a suspect.
    if "exchange" in categories and not fired:
        reasoning.append(
            "Known exchange deposit address with no laundering patterns of its own — "
            "treated as cash-out destination (subpoena target), not a suspect wallet."
        )
        return "low", 0.9, reasoning

    level: Literal["low", "medium", "high"]
    level = "high" if score >= 0.6 else "medium" if score >= 0.3 else "low"
    if not fired and not reasoning:
        reasoning.append("No typology patterns fired and anomaly score is unremarkable.")
    confidence = round(min(0.5 + 0.15 * len(fired) + 0.1 * (len(tags) > 0), 0.95), 2)
    return level, confidence, reasoning


def score_investigation(
    source: str,
    transfers: list[Transfer],
    tags_lookup=None,
) -> dict[str, WalletScore]:
    """Full pipeline for one investigation: features → IF + detectors → composite."""
    from app.chain.adapters import tags_for

    tags_lookup = tags_lookup or tags_for
    g = build_digraph(transfers)
    depths = hop_depths(g, source)
    addresses = sorted(set(depths) | {source})

    features = {
        a: compute_features(a, transfers, chain_depth=depths.get(a, 0)) for a in addresses
    }
    iso = iso_forest_scores(features)

    scores: dict[str, WalletScore] = {}
    for a in addresses:
        patterns = [
            detect_peeling_chain(a, transfers),
            detect_rapid_relay(a, transfers, features[a]),
            detect_circular(a, g),
            detect_structuring(a, transfers),
            detect_fan_out(a, transfers),
        ]
        tags = list(tags_lookup(a))
        level, confidence, reasoning = composite_risk(iso[a], patterns, tags)
        scores[a] = WalletScore(
            address=a,
            iso_forest_score=round(iso[a], 4),
            patterns=patterns,
            composite_risk=level,
            confidence=confidence,
            reasoning=reasoning,
            features=features[a],
            tags=tags,
        )
    return scores
