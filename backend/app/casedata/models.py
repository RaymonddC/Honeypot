"""casedata.* SQLAlchemy models — analyst-entered records (docs/Data-Model.md).

``casedata.bank_accounts``    — watchlisted bank accounts (→ TRACE Bridge).
``casedata.crypto_transfers`` — hand-entered transfers (→ TAKEDOWN graph).

Both are agency-owned (RLS by ``agency_id``, migration 20260723_10) and carry
``data_mode ∈ {poc, live}`` for evidentiary isolation, matching the intel.*
tables. Unlike the intel tables there is no ``public_id`` surrogate split — no
other table FKs these, so the ``id uuid`` PK IS the id returned over the API
(as its string form).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SCHEMA = "casedata"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class BankAccountRecord(Base):
    """A bank account an analyst is tracking (TRACE watchlist)."""

    __tablename__ = "bank_accounts"
    # The index carries the name migration 20260723_10 created it with — a
    # model/migration name mismatch reads as drift to `alembic check` (drop+create).
    __table_args__ = (
        Index("ix_casedata_bank_accounts_number", "account_number"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core.agencies.id"), nullable=False, index=True
    )
    bank_name: Mapped[str] = mapped_column(Text, nullable=False)
    account_number: Mapped[str] = mapped_column(Text, nullable=False)
    holder_name: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    case_id: Mapped[str | None] = mapped_column(Text)
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class CryptoTransferRecord(Base):
    """A hand-entered crypto transfer that feeds the TAKEDOWN graph."""

    __tablename__ = "crypto_transfers"
    # Names must match migration 20260723_10 exactly — see BankAccountRecord.
    __table_args__ = (
        Index("ix_casedata_crypto_transfers_from", "from_addr"),
        Index("ix_casedata_crypto_transfers_to", "to_addr"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core.agencies.id"), nullable=False, index=True
    )
    tx_hash: Mapped[str] = mapped_column(Text, nullable=False)
    from_addr: Mapped[str] = mapped_column(Text, nullable=False)
    to_addr: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[float] = mapped_column(Numeric, nullable=False)
    chain: Mapped[str] = mapped_column(Text, nullable=False, default="tron")
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False, default="unknown")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    case_id: Mapped[str | None] = mapped_column(Text)
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
