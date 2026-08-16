"""honeypot.* SQLAlchemy models — outbound calling ops (docs/Voice-Honeypot-Outbound.md §3).

``honeypot.numbers``        — the Twilio number pool we dial FROM (rotated).
``honeypot.dial_campaigns`` — one uploaded batch of numbers to work through.
``honeypot.dial_targets``   — one row per number in a campaign + durable dial
                              status/retry bookkeeping.
``honeypot.dial_attempts``  — one row per DIAL ATTEMPT (the call log / CDR),
                              including the ones nobody answered.

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
for why). ``dial_attempts`` extends that one hop further (attempt → target →
campaign), for the same reason.

TWO LOGS, ONE CALL — the split that matters here (migration 20260816_15):

* ``honeypot.dial_attempts`` — the **call log (CDR)**: one row per attempt,
  whatever happened. A number tried three times has three rows, even if nobody
  ever picked up. This is what answers "when did we call, and what happened?".
* ``intel.scam_sessions``    — the **conversation**: one row per *connected*
  attempt, carrying the transcript, extracted intel, and custody chain.

They are deliberately not the same table. A no-answer has no transcript and no
intel, so recording it as a session would put empty rows in front of the triage
queue (design spec §5), which reads sessions as an analyst work queue. But it
still has to be recorded *somewhere*, because "tried five times, never answered"
is itself intel about a target — and before this table existed, that history was
lost to a bare ``attempt_count`` counter.
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
    # NB: there is deliberately NO session_id here (dropped in migration
    # 20260816_14). Requeue means one target is dialed many times, so the link is
    # one-to-MANY and lives on the other side: ``dial_attempts.session_id`` for
    # the per-attempt link, and ``intel.scam_sessions.dial_target_id`` for the
    # conversations. A single FK here could only ever name "first" or "latest"
    # and would silently lose history.
    #
    # `status`/`last_error` below are the LATEST outcome only. The full
    # attempt-by-attempt history is in ``honeypot.dial_attempts``.
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")  # poc|live
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow,
        nullable=False,
    )


class DialAttempt(Base):
    """One dial ATTEMPT — the call-detail record. Written for every outcome."""

    __tablename__ = "dial_attempts"
    __table_args__ = (
        # One row per attempt, enforced. Makes the actor's logging idempotent
        # under Dramatiq at-least-once redelivery: a replayed attempt collides
        # rather than quietly doubling the call history.
        UniqueConstraint("target_id", "attempt_no", name="uq_dial_attempts_target_attempt"),
        {"schema": SCHEMA},
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    target_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.dial_targets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Mirrors dial_targets.attempt_count at the moment of this attempt (1-based),
    # so the log reads "attempt 2 of 3" without a window function.
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    # engaged | no_answer | failed — the same vocabulary the dialer/target use.
    outcome: Mapped[str] = mapped_column(Text, nullable=False)
    # Carrier/transport reason on a failed attempt; NULL otherwise.
    error: Mapped[str | None] = mapped_column(Text)
    # 0 for an attempt nobody answered; the talk time for an engaged one.
    duration_seconds: Mapped[int | None] = mapped_column(Integer)
    # Set ONLY for `engaged` — the conversation this attempt produced. Unambiguous
    # here (unlike on dial_targets) precisely because a row IS a single attempt.
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("intel.scam_sessions.id"), index=True
    )
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")  # poc|live
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
