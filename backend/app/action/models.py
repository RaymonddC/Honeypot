"""action.* SQLAlchemy models — UNCOVER / Action Panel (docs/Data-Model.md).

``action.action_bundles`` — the ``ActionBundle`` aggregate root (P-3,
docs/Persistence-Plan.md): identity, status lifecycle (draft → dispatched),
and JSONB *snapshots* of what was actually assembled/routed at generate-time
(``goaml_draft``/``routing_plan``/``totals``/``selected_entities`` — same
evidential reasoning as ``intel.scam_sessions.persona_snapshot``: a later
re-derivation could silently diverge from what a court exhibit actually said).
``action.action_documents`` — every generated document is evidence: SHA-256
hashed, timestamped, status-tracked (draft → issued → acknowledged), and now
stores the rendered ``pdf`` bytes directly (see migration 20260717_08 — no
object store exists yet, and evidence must be stored, never re-derived).
``action.notifications`` — multi-agency dispatch records; POC uses the mock
sink (status='mock', nothing leaves the system), LIVE dispatches for real.
Both link back to their bundle via ``bundle_id``.

Every data-producing table carries ``data_mode ∈ {poc, live}`` for
evidentiary isolation — LIVE evidence views never read POC rows.
``app/uncover/repository.py`` (P-3) is what actually writes these tables now.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SCHEMA = "action"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class ActionBundle(Base):
    """The action_bundle aggregate — one ``generate`` call's draft/dispatched envelope."""

    __tablename__ = "action_bundles"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    public_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # "act_..."
    case_id: Mapped[str] = mapped_column(Text, nullable=False)  # business key, NOT a uuid
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core.agencies.id"), index=True
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, default="draft")  # draft|dispatched
    crime_type: Mapped[str] = mapped_column(Text, nullable=False)
    outputs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    selected_entities: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    goaml_draft: Mapped[dict | None] = mapped_column(JSONB)
    routing_plan: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    totals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")  # poc|live
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ActionDocument(Base):
    """A generated legal/regulatory document (freeze request, STR, evidence pack)."""

    __tablename__ = "action_documents"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    public_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # "doc_..."
    bundle_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("action.action_bundles.id"), nullable=False, index=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)  # unpopulated — see docstring
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core.agencies.id"), index=True
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)  # account_blocking|str_report|summary
    format: Mapped[str | None] = mapped_column(Text)  # ppatk_str | iasc | generic
    title: Mapped[str] = mapped_column(Text, nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    template_version: Mapped[str] = mapped_column(Text, nullable=False)
    content_ref: Mapped[str | None] = mapped_column(Text)  # object-store key (future upgrade)
    pdf: Mapped[bytes | None] = mapped_column(LargeBinary)  # the rendered evidence itself
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="draft"
    )  # draft|issued|acknowledged
    generated_by: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    sha256: Mapped[bytes | None] = mapped_column(LargeBinary)  # doc is evidence → hashed
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")  # poc|live


class Notification(Base):
    """One dispatch record per target agency (POC: mock sink; LIVE: real channels)."""

    __tablename__ = "notifications"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    public_id: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # "ntf_..."
    bundle_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("action.action_bundles.id"), nullable=False, index=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)  # unpopulated — see docstring
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("core.agencies.id"), index=True
    )  # owning/dispatching agency (RLS) — distinct from the recipient below
    target_agency_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)  # unresolved, see docstring
    target_agency: Mapped[str] = mapped_column(Text, nullable=False)  # display name, e.g. "Bank BCA"
    agency_type: Mapped[str] = mapped_column(Text, nullable=False)  # bank|exchange|regulator|police
    channel: Mapped[str | None] = mapped_column(Text)  # goaml|iasc|webhook|email|mock
    payload: Mapped[dict | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="mock"
    )  # mock|queued|sent|failed
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
