"""Pydantic return models for the fiat boundary (TRACE / BridgeWatch).

Identical across POC and LIVE adapter implementations (contract rule —
docs/Adapter-MODE-Framework.md). POC rows carry generator ground truth
(``role``, ``cluster``, ``kind``) for demo legibility + tests; a LIVE bank
feed would fill ``role="unknown"`` — downstream detection never *uses*
ground truth, it has to rediscover it.
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.chain.schemas import Transfer
from app.core.config import Mode

AccountRole = Literal[
    "payer",            # gambler / mark making QRIS micro-deposits
    "shell_merchant",   # fake QRIS merchant collecting micro-deposits
    "mule",             # aggregation account (many-in / brief-hold / few-out)
    "collector_mule",   # cluster head that bulk-transfers to the exchange
    "exchange",         # crypto-exchange IDR bank account (known, KYC'd)
    "retail",           # legit exchange customer (noise — must NOT correlate)
    "unknown",          # LIVE feeds start here
]

TxKind = Literal[
    "qris_deposit",     # payer → shell merchant (Rp 10k–500k)
    "merchant_sweep",   # shell merchant → mules (aggregation)
    "mule_forward",     # mule → collector
    "bulk_to_exchange", # collector → exchange bank account (the on-ramp)
    "retail_noise",     # legit customer deposit (no crypto match)
]


class FiatAccountOut(BaseModel):
    id: UUID
    account_number: str
    bank_name: str
    holder_name: str
    role: AccountRole = "unknown"
    cluster: str | None = None  # ground-truth cluster (POC only), e.g. "C1"
    data_mode: Mode = "poc"


class FiatTransactionOut(BaseModel):
    id: UUID
    from_account_id: UUID
    to_account_id: UUID
    amount: float               # IDR
    ts: datetime
    channel: Literal["qris", "transfer", "ewallet"]
    kind: TxKind | None = None  # ground truth (POC only)
    data_mode: Mode = "poc"


class FiatGenParams(BaseModel):
    """Knobs for the synthetic PT A2Z generator. Deterministic per value set."""

    seed: int = 4656            # the case's 4,656 accounts — memorable seed
    n_merchants: int = 12
    n_clusters: int = 5
    n_payers: int = 110


class FiatDataset(BaseModel):
    """One generated PT A2Z scenario: fiat side + synthetic on-ramp deposits.

    ``crypto_deposits`` are the USDT-TRC20 deposits at the exchange hot wallet
    that the bulk fiat transfers *funded* (amount-conserving, fee-shaved,
    minutes later) — the ground truth the correlation engine must rediscover.
    """

    params: FiatGenParams
    accounts: list[FiatAccountOut]
    transactions: list[FiatTransactionOut]
    crypto_deposits: list[Transfer]
    idr_per_usdt: float
    hot_wallet: str
    case_framing: dict
    data_mode: Mode = "poc"

    # -- convenience lookups (not serialized as extra fields) ----------------

    def accounts_by_id(self) -> dict[UUID, FiatAccountOut]:
        return {a.id: a for a in self.accounts}

    def by_role(self, *roles: str) -> list[FiatAccountOut]:
        return [a for a in self.accounts if a.role in roles]

    def truth_clusters(self) -> dict[str, list[FiatAccountOut]]:
        out: dict[str, list[FiatAccountOut]] = {}
        for a in self.accounts:
            if a.cluster:
                out.setdefault(a.cluster, []).append(a)
        return out
