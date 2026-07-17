"""intel.* SQLAlchemy models — INFILTRATE honeypot intelligence (docs/Data-Model.md).

``intel.personas``          — the honeypot victim persona pool.
``intel.scam_sessions``     — one engaged scammer conversation (text or voice).
``intel.messages``          — hash-chained (sha256 + prev_sha256) raw conversation
                              log; raw is immutable, enrichment lives elsewhere.
``intel.entities``          — extracted entities with method/confidence/provenance;
                              never actionable until validated + reviewed.
``intel.syndicates``        — clustered syndicate profiles (+ members link table).
``intel.crime_classifications`` — per-session crime-type classification.

Every data-producing table carries ``data_mode ∈ {poc, live}`` for evidentiary
isolation — LIVE evidence views never read POC rows. P4 endpoints compute
in-memory from the replay adapter (same POC pattern as P1–P3); these tables
are the persistence target for later phases.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, LargeBinary, Numeric, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SCHEMA = "intel"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Persona(Base):
    """A honeypot victim persona (persona pool — volume + variety)."""

    __tablename__ = "personas"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # {age, occupation, tech_literacy, region, dialect, financial_situation,
    #  backstory, register}
    profile: Mapped[dict | None] = mapped_column(JSONB)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class ScamSession(Base):
    """One engaged scammer conversation, tied to a persona + channel."""

    __tablename__ = "scam_sessions"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    case_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)  # may pre-date case
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core.agencies.id"), index=True
    )
    persona_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.personas.id"), index=True
    )
    channel_type: Mapped[str] = mapped_column(Text, nullable=False, default="text")  # text|voice
    channel: Mapped[str | None] = mapped_column(Text)  # telegram|whatsapp|forum|pstn|wa_call
    channel_ref: Mapped[str | None] = mapped_column(Text)  # scammer handle/number (itself intel)
    crime_type: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")  # poc|live
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Message(Base):
    """Hash-chained conversation log (custody). Raw is immutable."""

    __tablename__ = "messages"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.scam_sessions.id"), index=True, nullable=False
    )
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core.agencies.id"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)  # per-session ordering
    direction: Mapped[str] = mapped_column(Text, nullable=False)  # inbound|outbound
    content: Mapped[str | None] = mapped_column(Text)  # text, or STT transcript (voice)
    audio_ref: Mapped[str | None] = mapped_column(Text)  # object-store key (voice, P4b)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    sha256: Mapped[bytes | None] = mapped_column(LargeBinary)  # custody chain
    prev_sha256: Mapped[bytes | None] = mapped_column(LargeBinary)
    meta: Mapped[dict | None] = mapped_column(JSONB)  # {latency_applied, typos_injected, …}
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")


class Entity(Base):
    """An extracted entity — never actionable until validated + reviewed."""

    __tablename__ = "entities"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.scam_sessions.id"), index=True
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.messages.id"), index=True
    )
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core.agencies.id"), index=True
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_value: Mapped[str | None] = mapped_column(Text)  # E.164, checksummed wallet…
    chain: Mapped[str | None] = mapped_column(Text)  # crypto_wallet: btc|eth|tron|bsc
    bank_name: Mapped[str | None] = mapped_column(Text)  # bank_account: context anchor
    method: Mapped[str] = mapped_column(Text, nullable=False)  # regex|llm|ner|human
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))  # 0..1
    review_status: Mapped[str] = mapped_column(
        Text, nullable=False, default="unverified"
    )  # unverified|confirmed|rejected|poisoned
    provenance: Mapped[dict | None] = mapped_column(JSONB)  # {turn, method_detail, validators…}
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class Syndicate(Base):
    """A clustered syndicate profile (shared accounts / phone reuse / fingerprints)."""

    __tablename__ = "syndicates"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core.agencies.id"), index=True
    )
    label: Mapped[str] = mapped_column(Text, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    linguistic_fingerprint: Mapped[dict | None] = mapped_column(JSONB)
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class SyndicateMember(Base):
    """Entities clustered into a syndicate (link table)."""

    __tablename__ = "syndicate_members"
    __table_args__ = ({"schema": SCHEMA},)

    syndicate_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.syndicates.id"), primary_key=True
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.entities.id"), primary_key=True
    )
    link_type: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))


class CrimeClassification(Base):
    """Per-session crime-type classification (LLM/rules + validation)."""

    __tablename__ = "crime_classifications"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.scam_sessions.id"), index=True, nullable=False
    )
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core.agencies.id"), index=True
    )
    crime_type: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3))
    model_version: Mapped[str | None] = mapped_column(Text)
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
