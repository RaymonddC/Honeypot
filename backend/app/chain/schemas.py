"""Pydantic return models for the blockchain boundary.

Identical across POC and LIVE adapter implementations (contract rule —
docs/Adapter-MODE-Framework.md).
"""

from datetime import datetime

from pydantic import BaseModel

from app.core.config import Mode


class Transfer(BaseModel):
    """A normalized token transfer (USDT-TRC20 for the MVP)."""

    tx_hash: str
    from_addr: str
    to_addr: str
    value: float
    token_symbol: str = "USDT"
    token_contract: str | None = None
    ts: datetime
    block_number: int | None = None
    data_mode: Mode = "poc"


class TransferPage(BaseModel):
    items: list[Transfer]
    next_cursor: str | None = None


class WalletBalance(BaseModel):
    address: str
    chain: str = "tron"
    native_balance: float = 0.0
    token_balance: float = 0.0  # USDT
    data_mode: Mode = "poc"


class AddressTagOut(BaseModel):
    address: str
    chain: str = "tron"
    tag: str
    category: str
    source: str
    confidence: float | None = None
