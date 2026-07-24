"""Correlation engine — the fiat↔crypto bridge (docs/TRACE-Design.md §3).

Matches fiat outflows into known exchange bank accounts against USDT
deposits at the exchange hot wallet:

- **amount match within fee tolerance**: expected USDT = amount_idr / rate;
  |expected − observed| / expected ≤ ``AMOUNT_TOLERANCE`` (exchange fees +
  spread shave a fraction of a percent off the conversion), and
- **timing within a 30-minute window**: deposit lands 0 < Δt ≤ 1800 s
  *after* the fiat transfer.

Candidate pairs are ranked by confidence and matched greedily 1:1 —
each fiat tx and each deposit correlates at most once. Pure in-memory
computation (POC pattern, mirrors P1).
"""

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.chain.schemas import Transfer
from app.core.config import Mode
from app.fiat.generator import IDR_PER_USDT
from app.fiat.schemas import FiatAccountOut, FiatTransactionOut

TIME_WINDOW_SECONDS = 30 * 60
AMOUNT_TOLERANCE = 0.02  # 2% relative — covers 0.4–0.9% exchange fee + spread
METHOD = "amount_time_window"

_NS = uuid.uuid5(uuid.NAMESPACE_URL, "ittu:correlation")


class FiatLeg(BaseModel):
    fiat_tx_id: uuid.UUID
    from_account_number: str
    from_bank: str
    from_holder: str
    to_account_number: str
    to_bank: str
    to_holder: str = ""  # exchange name (holder of the receiving account)
    amount_idr: float
    ts: datetime


class CryptoLeg(BaseModel):
    tx_hash: str
    from_addr: str
    to_addr: str  # the exchange hot wallet
    amount_usdt: float
    ts: datetime


class CorrelationOut(BaseModel):
    id: uuid.UUID
    fiat: FiatLeg
    crypto: CryptoLeg
    time_delta_seconds: int
    amount_match: float  # 1 − relative amount difference (1.0 = exact)
    confidence: float    # 0..1 blend of amount + time proximity
    method: str = METHOD
    data_mode: Mode = "poc"


def correlate(
    transactions: list[FiatTransactionOut],
    accounts: list[FiatAccountOut],
    deposits: list[Transfer],
    *,
    rate: float = IDR_PER_USDT,
    window_seconds: int = TIME_WINDOW_SECONDS,
    tolerance: float = AMOUNT_TOLERANCE,
) -> list[CorrelationOut]:
    """Greedy best-confidence 1:1 matching of exchange inflows ↔ hot-wallet deposits."""
    by_id = {a.id: a for a in accounts}
    exchange_ids = {a.id for a in accounts if a.role == "exchange"}
    inflows = [t for t in transactions if t.to_account_id in exchange_ids]

    candidates: list[tuple[float, float, float, FiatTransactionOut, Transfer]] = []
    for f in inflows:
        expected_usdt = f.amount / rate
        for d in deposits:
            delta = (d.ts - f.ts).total_seconds()
            if not (0 < delta <= window_seconds):
                continue
            rel_diff = abs(expected_usdt - d.value) / expected_usdt
            if rel_diff > tolerance:
                continue
            confidence = 0.55 * (1 - rel_diff / tolerance) + 0.45 * (1 - delta / window_seconds)
            candidates.append((confidence, rel_diff, delta, f, d))

    # Greedy: highest confidence first, each leg used at most once.
    candidates.sort(key=lambda c: (-c[0], c[3].ts, c[4].tx_hash))
    used_fiat: set[uuid.UUID] = set()
    used_crypto: set[str] = set()
    out: list[CorrelationOut] = []
    for confidence, rel_diff, delta, f, d in candidates:
        if f.id in used_fiat or d.tx_hash in used_crypto:
            continue
        used_fiat.add(f.id)
        used_crypto.add(d.tx_hash)
        frm, to = by_id[f.from_account_id], by_id[f.to_account_id]
        out.append(CorrelationOut(
            id=uuid.uuid5(_NS, f"{f.id}:{d.tx_hash}"),
            fiat=FiatLeg(
                fiat_tx_id=f.id,
                from_account_number=frm.account_number,
                from_bank=frm.bank_name,
                from_holder=frm.holder_name,
                to_account_number=to.account_number,
                to_bank=to.bank_name,
                to_holder=to.holder_name,
                amount_idr=f.amount,
                ts=f.ts,
            ),
            crypto=CryptoLeg(
                tx_hash=d.tx_hash,
                from_addr=d.from_addr,
                to_addr=d.to_addr,
                amount_usdt=d.value,
                ts=d.ts,
            ),
            time_delta_seconds=int(delta),
            amount_match=round(1 - rel_diff, 4),
            confidence=round(confidence, 3),
        ))

    out.sort(key=lambda c: -c.confidence)
    return out


def unmatched_deposits(
    deposits: list[Transfer], correlations: list[CorrelationOut]
) -> list[Transfer]:
    """Hot-wallet deposits with no fiat counterpart — e.g. crypto-side
    cash-outs like the TAKEDOWN peeling chain's 86,200 USDT deposit."""
    matched = {c.crypto.tx_hash for c in correlations}
    return [d for d in deposits if d.tx_hash not in matched]
