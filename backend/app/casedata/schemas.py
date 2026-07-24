"""CASEDATA API models — analyst-entered bank accounts + crypto transfers.

Two record types the investigator adds by hand and the app then tracks:
``BankAccountOut`` (watchlisted on TRACE) and ``CryptoTxOut`` (merged into the
TAKEDOWN graph). Input models validate the minimum a record needs to be useful
downstream; the ``id`` is a server-minted UUID string.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.chain.schemas import Transfer
from app.core.config import Mode

# Shared attribution label for a tracked record.
Category = Literal["scam", "mule", "victim", "suspect", "exchange", "unknown"]


# --------------------------------------------------------------------------- #
# Bank accounts (→ TRACE watchlist)
# --------------------------------------------------------------------------- #


class AddBankAccountRequest(BaseModel):
    """Add a bank account to track."""

    bank_name: str = Field(min_length=1, max_length=64)
    account_number: str = Field(min_length=3, max_length=40)
    holder_name: str | None = Field(default=None, max_length=120)
    category: Category = "unknown"
    note: str = Field(default="", max_length=500)
    case_id: str | None = None


class BankAccountOut(BaseModel):
    id: str
    bank_name: str
    account_number: str
    holder_name: str | None = None
    category: Category = "unknown"
    note: str = ""
    case_id: str | None = None
    data_mode: Mode = "poc"
    created_at: datetime


# --------------------------------------------------------------------------- #
# Crypto transfers (→ TAKEDOWN graph)
# --------------------------------------------------------------------------- #


class AddCryptoTxRequest(BaseModel):
    """Add a crypto transfer that will feed the Investigation graph.

    A hand-entered edge: ``from_addr → to_addr`` for ``value`` at ``ts``. Both
    addresses become investigable nodes. ``tx_hash`` is optional (auto-minted).
    """

    from_addr: str = Field(min_length=4, max_length=80)
    to_addr: str = Field(min_length=4, max_length=80)
    value: float = Field(gt=0)
    ts: datetime
    chain: str = "tron"
    tx_hash: str | None = Field(default=None, max_length=80)
    category: Category = "unknown"
    note: str = Field(default="", max_length=500)
    case_id: str | None = None


class CryptoTxOut(BaseModel):
    id: str
    tx_hash: str
    from_addr: str
    to_addr: str
    value: float
    chain: str = "tron"
    ts: datetime
    category: Category = "unknown"
    note: str = ""
    case_id: str | None = None
    data_mode: Mode = "poc"
    created_at: datetime

    def as_transfer(self) -> Transfer:
        """Project to a chain ``Transfer`` for the TAKEDOWN graph/scoring."""
        return Transfer(
            tx_hash=self.tx_hash,
            from_addr=self.from_addr,
            to_addr=self.to_addr,
            value=self.value,
            ts=self.ts,
            data_mode=self.data_mode,
        )
