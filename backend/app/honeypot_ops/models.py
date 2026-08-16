"""honeypot.* SQLAlchemy models — outbound calling ops (docs/Voice-Honeypot-Outbound.md §3).

``honeypot.numbers``        — the Twilio number pool we dial FROM (rotated).
``honeypot.dial_campaigns`` — one uploaded batch of numbers to work through.
``honeypot.dial_targets``   — one row per number in a campaign + durable dial
                              status/retry bookkeeping.

``dial_targets`` deliberately mirrors ``action.notifications``'s delivery
lifecycle (``status``/``attempt_count``/``last_error``/``updated_at``): both are
"a queued unit of outbound work a Dramatiq actor retries", and reusing the shape
means the C1 delivery patterns (durable row status, bounded retry budget) carry
over unchanged.

Every data-producing table carries ``data_mode ∈ {poc, live}`` for evidentiary
isolation — LIVE evidence views never read POC rows. That matters here: a POC
campaign never actually dials Twilio (design spec §4), so its rows must never be
mistaken for real engagement evidence.

Agency ownership: ``numbers`` and ``dial_campaigns`` carry ``agency_id`` and are
RLS-scoped by it (migration 20260816_13). ``dial_targets`` has no ``agency_id``
— it is reached only through its campaign, and its RLS policy joins through
``campaign_id`` rather than denormalizing the owner (see the migration docstring
for why).
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SCHEMA = "honeypot"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class HoneypotNumber(Base):
    """One Twilio number the honeypot dials FROM (registered, not provisioned)."""

    __tablename__ = "numbers"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core.agencies.id"), nullable=False, index=True
    )
    # E.164, e.g. "+62812xxxxxxx". Globally unique: a physical phone number can
    # only be owned once, so this is a real-world constraint, not a tenant one.
    phone_number: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    # Twilio's number SID (PN...) — the handle for later API management. Nullable
    # because a POC/simulated pool entry has no Twilio counterpart.
    twilio_sid: Mapped[str | None] = mapped_column(Text)
    label: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # active   → eligible for rotation
    # retired  → kept for provenance (past calls reference it), never dialed from
    # rate_limited → temporarily benched (carrier/Twilio throttling)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="active")
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")  # poc|live
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow,
        nullable=False,
    )


class DialCampaign(Base):
    """One uploaded batch of numbers to dial, with a pacing cap."""

    __tablename__ = "dial_campaigns"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    public_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # "camp_..."
    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("core.agencies.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Optional: pre-attach every call in this batch to one case, skipping triage
    # (design spec §5 step 1). No FK — same reasoning as
    # ``intel.scam_sessions.case_id``: the link is advisory and may pre-date /
    # outlive the case row.
    case_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    # draft → running → (paused ⇄ running) → completed
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")
    # Dial-rate cap. Twilio's own per-account concurrency is the hard ceiling;
    # this is our self-imposed pacing so a campaign doesn't burst.
    pacing_per_minute: Mapped[int] = mapped_column(Integer, nullable=False, default=6)
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("core.users.id"))
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")  # poc|live
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class DialTarget(Base):
    """One number in a campaign + its durable dial status (retried by the actor)."""

    __tablename__ = "dial_targets"
    __table_args__ = (
        # A campaign never dials the same number twice (mirrors the migration).
        UniqueConstraint("campaign_id", "phone_number", name="uq_dial_targets_campaign_number"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    campaign_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.dial_campaigns.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    phone_number: Mapped[str] = mapped_column(Text, nullable=False)  # E.164, unique per campaign
    # queued → dialing → engaged | no_answer | failed
    status: Mapped[str] = mapped_column(Text, nullable=False, default="queued")
    # Dial attempts made; climbs on retry (mirrors notifications.attempt_count).
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Last failure reason (Twilio error / transport) — null while queued/on success.
    last_error: Mapped[str | None] = mapped_column(Text)
    # Set once the call connects and a session exists. Nullable + no FK cycle
    # problem because ``scam_sessions.dial_target_id`` is likewise nullable —
    # whichever row is written first leaves the other side NULL until linked.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("intel.scam_sessions.id"), index=True
    )
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")  # poc|live
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow,
        nullable=False,
    )
