"""action.* SQLAlchemy models — UNCOVER / Action Panel (docs/Data-Model.md).

``action.action_documents`` — every generated document is evidence: SHA-256
hashed, timestamped, status-tracked (draft → issued → acknowledged).
``action.notifications`` — multi-agency dispatch records; POC uses the mock
sink (status='mock', nothing leaves the system), LIVE dispatches for real.

Every data-producing table carries ``data_mode ∈ {poc, live}`` for
evidentiary isolation — LIVE evidence views never read POC rows.
P3 endpoints compute in-memory from generators (same POC pattern as P1/P2);
these tables are the persistence target for later phases.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, LargeBinary, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SCHEMA = "action"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class ActionDocument(Base):
    """A generated legal/regulatory document (freeze request, STR, evidence pack)."""

    __tablename__ = "action_documents"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    case_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    agency_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)  # account_blocking|str_report|summary
    format: Mapped[str | None] = mapped_column(Text)  # ppatk_str | iasc | generic
    content_ref: Mapped[str | None] = mapped_column(Text)  # object-store key (ReportLab PDF)
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
    case_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    target_agency_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
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
