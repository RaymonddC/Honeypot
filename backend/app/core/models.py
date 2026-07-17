"""core.* SQLAlchemy models — tenancy, identity, cases, audit (docs/Data-Model.md).

The RLS foundation: every agency-scoped table here gets Postgres Row-Level
Security in migration ``20260708_05`` (owning-agency OR explicit ``case_shares``
grant — never implicit). App-level checks (app/core/auth.py) are defense-in-depth
*on top of* RLS, never instead of it.

``core.audit_log`` is append-only and hash-chained (sha256 + prev_sha256) per
agency — tamper-evident custody (UU ITE Pasal 5).
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import BYTEA, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base

SCHEMA = "core"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Agency(Base):
    """Tenant. type drives role templates + visibility rules."""

    __tablename__ = "agencies"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    type: Mapped[str] = mapped_column(Text, nullable=False)  # regulator|police|bank|exchange|other
    onprem: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class User(Base):
    """Google OAuth (LIVE) / demo login (POC) → we mint our own JWT."""

    __tablename__ = "users"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.agencies.id"), nullable=False, index=True
    )
    oauth_sub: Mapped[str | None] = mapped_column(Text, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False, unique=True)  # citext in prod
    name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, nullable=False)  # RBAC role (see core/auth.py ROLES)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class Role(Base):
    """Role → permission templates, per agency type."""

    __tablename__ = "roles"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    agency_type: Mapped[str | None] = mapped_column(Text)
    permissions: Mapped[dict | None] = mapped_column(JSONB)


class Case(Base):
    """The investigation — the spine tying intel, chain, fiat, and actions together."""

    __tablename__ = "cases"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.agencies.id"), nullable=False, index=True
    )  # owning agency
    title: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, default="open"
    )  # open|active|closed|archived
    crime_type: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")  # poc|live
    created_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey(f"{SCHEMA}.users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CaseShare(Base):
    """EXPLICIT cross-agency sharing (e.g. bank → PPATK). No implicit visibility."""

    __tablename__ = "case_shares"
    __table_args__ = ({"schema": SCHEMA},)

    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.cases.id"), primary_key=True
    )
    agency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.agencies.id"), primary_key=True
    )  # grantee
    access: Mapped[str] = mapped_column(Text, nullable=False, default="read")  # read|contribute
    granted_by: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey(f"{SCHEMA}.users.id"))
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )


class AuditLog(Base):
    """Append-only; hash-chained per agency (sha256 + prev_sha256)."""

    __tablename__ = "audit_log"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    agency_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False, index=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    target_type: Mapped[str | None] = mapped_column(Text)
    target_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    detail: Mapped[dict | None] = mapped_column(JSONB)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
    seq: Mapped[int | None] = mapped_column(BigInteger)
    sha256: Mapped[bytes | None] = mapped_column(BYTEA)
    prev_sha256: Mapped[bytes | None] = mapped_column(BYTEA)


class EvidenceManifest(Base):
    """Per-session/case reproducibility manifest for court explainability
    (docs/Data-Model.md) — model/prompt/pipeline versions + hashes, RLS-scoped
    (migration 20260715_06; not in the app.core.db.get_tenant_session write path yet).
    """

    __tablename__ = "evidence_manifest"
    __table_args__ = ({"schema": SCHEMA},)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=_uuid)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("intel.scam_sessions.id"), index=True
    )
    case_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.cases.id"), index=True
    )
    agency_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey(f"{SCHEMA}.agencies.id"), index=True
    )
    model_versions: Mapped[dict | None] = mapped_column(
        JSONB
    )  # {orchestrator, extractor, classifier, stt, tts}
    prompt_versions: Mapped[dict | None] = mapped_column(JSONB)
    pipeline_config: Mapped[dict | None] = mapped_column(JSONB)
    hashes: Mapped[dict | None] = mapped_column(JSONB)  # {"transcript_sha256": "...", ...}
    data_mode: Mapped[str] = mapped_column(Text, nullable=False, default="poc")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=datetime.utcnow, nullable=False
    )
