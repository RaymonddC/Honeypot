"""fiat.* SQLAlchemy models — TRACE / BridgeWatch (docs/Data-Model.md).

``fiat.fiat_accounts`` + ``fiat.fiat_transactions`` hold the fiat side
(POC: synthetic PT A2Z generator; LIVE: bank/QRIS feed post-MoU).
``fiat.correlations`` is the bridge: a fiat outflow matched to a crypto
deposit by amount (fee-tolerant) + 30-min time window.

Every data-producing table carries ``data_mode ∈ {poc, live}`` for
evidentiary isolation — LIVE evidence views never read POC rows.
P2 endpoints compute in-memory from the generator (same pattern as P1);
these tables are the persistence target for later phases.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SCHEMA = "fiat"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class FiatAccount(Base):
    __tablename__ = "fiat_accounts"
    __table_args__ = (
        UniqueConstraint("account_number", "bank_name", name="uq_fiat_accounts_number_bank"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    account_number: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    bank_name: Mapped[str] = mapped_column(Text, nullable=False)
    holder_name: Mapped[str | None] = mapped_column(Text)
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")  # poc|live
    source: Mapped[str | None] = mapped_column(Text)  # synthetic_a2z | paysim | bank_feed
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class FiatTransaction(Base):
    __tablename__ = "fiat_transactions"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    from_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.fiat_accounts.id"), index=True
    )
    to_account_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.fiat_accounts.id"), index=True
    )
    amount: Mapped[float] = mapped_column(Numeric, nullable=False)  # IDR
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(Text, nullable=False)  # transfer|qris|ewallet
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")
    raw: Mapped[dict | None] = mapped_column(JSONB)  # generator ground truth / feed payload
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class Correlation(Base):
    """The bridge: fiat outflow ↔ crypto deposit (time window + amount match)."""

    __tablename__ = "correlations"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    case_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    fiat_tx_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.fiat_transactions.id"), index=True
    )
    crypto_tx_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chain.transactions.id"), index=True
    )
    time_delta_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    amount_match: Mapped[float] = mapped_column(Numeric, nullable=False)  # 0..1
    confidence: Mapped[float] = mapped_column(Numeric, nullable=False)  # 0..1
    method: Mapped[str] = mapped_column(Text, nullable=False)  # amount_time_window
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
