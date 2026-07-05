"""TAKEDOWN feature engine — Gary's canonical 12 features per wallet.

Pure functions over a wallet's USDT-TRC20 transfer set (docs/TAKEDOWN-Design.md).
Features feed the Isolation Forest; they are *not* the typology patterns
(those live in app/takedown/scoring.py detectors).
"""

import math
from collections import Counter
from datetime import timedelta

from pydantic import BaseModel

from app.chain.schemas import Transfer

RAPID_RELAY_WINDOW = timedelta(minutes=5)

FEATURE_ORDER = [
    "tx_velocity",
    "total_volume",
    "mean_volume",
    "unique_counterparties",
    "rapid_relay_rate",
    "round_number_pct",
    "fan_ratio",
    "account_age_days",
    "inout_ratio",
    "time_entropy",
    "chain_depth",
    "self_loop_count",
    "max_tx_size",
]


class FeatureVector(BaseModel):
    """The 12 canonical features (volume counts as one, split total/mean)."""

    tx_velocity: float = 0.0  # 1  tx per active day
    total_volume: float = 0.0  # 2  volume
    mean_volume: float = 0.0  # 2  volume
    unique_counterparties: int = 0  # 3
    rapid_relay_rate: float = 0.0  # 4  share of inflow forwarded ≤5 min
    round_number_pct: float = 0.0  # 5
    fan_ratio: float = 0.0  # 6  fan-in / fan-out
    account_age_days: int = 0  # 7
    inout_ratio: float = 0.0  # 8  out/in value (≈1.0 = pass-through)
    time_entropy: float = 0.0  # 9  hour-of-day Shannon entropy, normalized 0..1
    chain_depth: int = 0  # 10 hops from the investigated source
    self_loop_count: int = 0  # 11
    max_tx_size: float = 0.0  # 12

    def as_row(self) -> list[float]:
        """Feature row in canonical order (for the Isolation Forest matrix)."""
        return [float(getattr(self, name)) for name in FEATURE_ORDER]


def _is_round(value: float) -> bool:
    """Round-amount heuristic: whole multiple of 10 (structuring signature)."""
    return value > 0 and value % 10 == 0


def compute_features(
    address: str, transfers: list[Transfer], chain_depth: int = 0
) -> FeatureVector:
    """Compute the 12 features for `address` from transfers touching it."""
    own = [t for t in transfers if address in (t.from_addr, t.to_addr)]
    if not own:
        return FeatureVector(chain_depth=chain_depth)

    inbound = [t for t in own if t.to_addr == address and t.from_addr != address]
    outbound = [t for t in own if t.from_addr == address and t.to_addr != address]
    self_loops = [t for t in own if t.from_addr == t.to_addr == address]

    values = [t.value for t in own]
    total_in = sum(t.value for t in inbound)
    total_out = sum(t.value for t in outbound)

    # 1 — velocity: txs per active (distinct UTC) day
    active_days = len({t.ts.date() for t in own})
    tx_velocity = len(own) / active_days if active_days else 0.0

    # 3 / 6 — counterparties + fan-in/fan-out ratio
    senders = {t.from_addr for t in inbound}
    receivers = {t.to_addr for t in outbound}
    fan_ratio = len(senders) / len(receivers) if receivers else float(len(senders))

    # 4 — rapid relay: share of inbound value followed by an outflow ≤5 min later
    relayed = sum(
        t.value
        for t in inbound
        if any(0 <= (o.ts - t.ts).total_seconds() <= RAPID_RELAY_WINDOW.total_seconds()
               for o in outbound)
    )
    rapid_relay_rate = relayed / total_in if total_in else 0.0

    # 7 — account age (observed activity window)
    first, last = min(t.ts for t in own), max(t.ts for t in own)
    account_age_days = (last - first).days

    # 9 — hour-of-day entropy, normalized by log(#bins used ceiling 24)
    hour_counts = Counter(t.ts.hour for t in own)
    n = len(own)
    entropy = -sum((c / n) * math.log2(c / n) for c in hour_counts.values())
    time_entropy = entropy / math.log2(24)

    return FeatureVector(
        tx_velocity=tx_velocity,
        total_volume=total_in + total_out,
        mean_volume=sum(values) / len(values),
        unique_counterparties=len(senders | receivers),
        rapid_relay_rate=min(rapid_relay_rate, 1.0),
        round_number_pct=sum(_is_round(v) for v in values) / len(values),
        fan_ratio=fan_ratio,
        account_age_days=account_age_days,
        inout_ratio=total_out / total_in if total_in else 0.0,
        time_entropy=time_entropy,
        chain_depth=chain_depth,
        self_loop_count=len(self_loops),
        max_tx_size=max(values),
    )
