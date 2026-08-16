"""chain.* SQLAlchemy models — TRACE ingestion + TAKEDOWN analytics.

See docs/Data-Model.md (chain schema) and docs/TAKEDOWN-Design.md.
``chain.wallet_features`` carries Gary's canonical 12 features (features ≠
patterns: mixer/counterparty exposure live in ``chain.address_tags``; the 5
typology patterns are detectors, recorded in ``wallet_risk_scores.typology_flags``).

Every data-producing table carries ``data_mode ∈ {poc, live}`` for evidentiary
isolation — LIVE evidence views never read POC rows.
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
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

SCHEMA = "chain"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Wallet(Base):
    __tablename__ = "wallets"
    __table_args__ = (
        UniqueConstraint("address", "chain", name="uq_wallets_address_chain"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    address: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    chain: Mapped[str] = mapped_column(Text, nullable=False)  # btc|eth|tron|bsc
    first_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    native_balance: Mapped[float | None] = mapped_column(Numeric)
    source: Mapped[str | None] = mapped_column(Text)  # honeypot | iasc | manual
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")  # poc|live
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class Transaction(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint(
            "chain", "tx_hash", "from_addr", "to_addr", name="uq_transactions_ingest"
        ),  # idempotent ingest
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    tx_hash: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    chain: Mapped[str] = mapped_column(Text, nullable=False)
    from_addr: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    to_addr: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    value: Mapped[float] = mapped_column(Numeric, nullable=False)
    token_symbol: Mapped[str | None] = mapped_column(Text)  # USDT
    token_contract: Mapped[str | None] = mapped_column(Text)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    block_number: Mapped[int | None] = mapped_column(BigInteger)
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")
    raw: Mapped[dict | None] = mapped_column(JSONB)  # normalized provider payload
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class WalletFeatures(Base):
    """Gary's canonical 12 features, computed per wallet (TAKEDOWN feature engine)."""

    __tablename__ = "wallet_features"
    __table_args__ = ({"schema": SCHEMA},)

    wallet_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.wallets.id"), primary_key=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, default=datetime.utcnow
    )
    tx_velocity: Mapped[float | None] = mapped_column(Numeric)  # 1 tx per active day
    total_volume: Mapped[float | None] = mapped_column(Numeric)  # 2 volume (total)
    mean_volume: Mapped[float | None] = mapped_column(Numeric)  # 2 volume (mean)
    unique_counterparties: Mapped[int | None] = mapped_column(Integer)  # 3
    rapid_relay_rate: Mapped[float | None] = mapped_column(Numeric)  # 4 forwarded quickly
    round_number_pct: Mapped[float | None] = mapped_column(Numeric)  # 5
    fan_ratio: Mapped[float | None] = mapped_column(Numeric)  # 6 fan-in/fan-out
    account_age_days: Mapped[int | None] = mapped_column(Integer)  # 7
    inout_ratio: Mapped[float | None] = mapped_column(Numeric)  # 8
    time_entropy: Mapped[float | None] = mapped_column(Numeric)  # 9
    chain_depth: Mapped[int | None] = mapped_column(Integer)  # 10 multi-hop position
    self_loop_count: Mapped[int | None] = mapped_column(Integer)  # 11
    max_tx_size: Mapped[float | None] = mapped_column(Numeric)  # 12
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")


class WalletRiskScore(Base):
    __tablename__ = "wallet_risk_scores"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    # Nullable because that is what the DB actually enforces: migration
    # 20260704_01 created this column without `nullable=False`, so NULL is
    # permitted. The non-Optional annotation this replaced implied NOT NULL and
    # was simply never true — the model documented a constraint the database has
    # never had. Tightening it (a `SET NOT NULL` migration) is a deliberate
    # product decision, not a drift fix: see docs/Backlog.md.
    wallet_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.wallets.id"), index=True
    )
    iso_forest_score: Mapped[float | None] = mapped_column(Numeric)  # anomaly triage 0..1
    typology_flags: Mapped[dict | None] = mapped_column(JSONB)  # detectors that fired
    composite_risk: Mapped[str | None] = mapped_column(Text)  # low|medium|high
    confidence: Mapped[float | None] = mapped_column(Numeric)
    reasoning: Mapped[str | None] = mapped_column(Text)  # Glass Box explicit reasoning
    model_version: Mapped[str | None] = mapped_column(Text)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")


class AddressTag(Base):
    """Attribution DB (the moat gap — seed early). Mode-independent reference data."""

    __tablename__ = "address_tags"
    __table_args__ = (
        UniqueConstraint("address", "chain", "source", name="uq_address_tags"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    address: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    chain: Mapped[str] = mapped_column(Text, nullable=False)
    tag: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "Indodax"
    category: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # exchange|mixer|scam|gambling|sanctioned|service|unknown
    source: Mapped[str] = mapped_column(Text, nullable=False)  # ofac_sdn|etherscan|...
    confidence: Mapped[float | None] = mapped_column(Numeric)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class GraphSnapshot(Base):
    """Cached per-case subgraph export. Agency-scoped (RLS, migration 20260715_06)
    — unlike the raw-ledger tables above, a graph export reveals which
    entities/wallets an agency is investigating, so it's agency-owned, not a
    shared public-ledger fact.
    """

    __tablename__ = "graph_snapshots"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    case_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core.agencies.id"), index=True
    )
    spec: Mapped[dict | None] = mapped_column(JSONB)  # projection params (depth, node types…)
    content_ref: Mapped[str | None] = mapped_column(Text)  # object-store key
    node_count: Mapped[int | None] = mapped_column(Integer)
    edge_count: Mapped[int | None] = mapped_column(Integer)
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")
    built_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
