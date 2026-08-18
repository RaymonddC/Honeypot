"""Agency audit trail — who did what, when, tamper-evident.

``core.audit_log`` has existed (migrated, and documented as "append-only;
hash-chained per agency") since the core schema landed, but **nothing ever wrote
to it**: the only chain in the codebase was ``uncover.custody.audit_log``, a
process-local in-memory singleton covering document generation. For a platform
whose output is meant to survive court scrutiny, implying an audit capability
that produces no rows is worse than not claiming one. This module is the writer.

**Per-agency chain.** Each entry stores ``sha256`` over its own canonical
content plus the ``prev_sha256`` of that agency's previous entry, so removing or
editing any entry breaks every hash after it — the same construction
``uncover/custody.py`` uses for documents (UU ITE Pasal 5: alteration must be
detectable). The chain is per agency, not global, because agencies are isolated
by RLS: a global chain would force one tenant's verification to depend on rows
it is not allowed to read.

**Never fails the caller.** Recording an action is bookkeeping *about* work that
already happened; if the audit write fails, the action itself must still stand
(and the failure is logged loudly). The alternative — a failed audit insert
rolling back a completed case update — trades a missing log line for corrupted
state, which is the worse outcome. ``verify_chain`` exists so a gap is
detectable rather than silent.

Memory mode keeps an in-process chain so POC demos and tests exercise the same
code path; only Postgres persists.
"""

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol, runtime_checkable

from sqlalchemy import select

from app.core.config import get_settings

_log = logging.getLogger("uvicorn.error")

GENESIS = "0" * 64


# Actions worth reconstructing later. Free-form strings would drift into
# near-duplicates ("case.update" vs "case_updated") and make the log unqueryable.
AUTH_LOGIN = "auth.login"
CASE_CREATED = "case.created"
CASE_UPDATED = "case.updated"
ENTITY_REVIEWED = "entity.reviewed"
DISPATCH_SENT = "dispatch.sent"
# Evidence generation. The per-bundle chain in ``uncover/custody.py`` also
# records these, but it is an in-memory POC accumulator refilled per request
# (see uncover/repository.py) — it does not survive a restart. Recording them
# here is what makes the evidence trail DURABLE; custody remains the per-bundle
# presentation of the same events inside ``ActionBundle.audit``.
BUNDLE_GENERATED = "action.bundle.generated"
TRIAGE_ATTACHED = "triage.attached"
TRIAGE_PROMOTED = "triage.promoted"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def entry_hash(
    *,
    seq: int,
    action: str,
    actor_user_id: str | None,
    target_type: str | None,
    target_id: str | None,
    detail: dict,
    ts: datetime,
    prev_sha256: str,
) -> str:
    """SHA-256 over the entry's canonical JSON, chained to the previous hash.

    ``sort_keys`` + tight separators make the encoding canonical: the same entry
    must hash identically on any machine and any Python version, or verification
    fails for reasons that have nothing to do with tampering.
    """
    canonical = json.dumps(
        {
            "seq": seq,
            "action": action,
            "actor_user_id": actor_user_id,
            "target_type": target_type,
            "target_id": target_id,
            "detail": detail,
            "ts": ts.isoformat(),
            "prev_sha256": prev_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass
class AuditEntry:
    """One recorded action. ``seq`` is per-agency, starting at 1."""

    id: str
    agency_id: str
    seq: int
    action: str
    actor_user_id: str | None
    target_type: str | None
    target_id: str | None
    detail: dict
    ts: datetime
    sha256: str
    prev_sha256: str


@runtime_checkable
class AuditRepository(Protocol):
    async def record(
        self,
        *,
        agency_id: str,
        action: str,
        actor_user_id: str | None = None,
        target_type: str | None = None,
        target_id: str | None = None,
        detail: dict | None = None,
    ) -> AuditEntry | None: ...

    async def list_entries(self, *, agency_id: str, limit: int = 100) -> list[AuditEntry]: ...

    async def verify_chain(self, *, agency_id: str) -> tuple[bool, int | None]: ...


# --------------------------------------------------------------------------- #
# In-memory (POC / tests)
# --------------------------------------------------------------------------- #


@dataclass
class InMemoryAuditRepository:
    _by_agency: dict[str, list[AuditEntry]] = field(default_factory=dict)

    async def record(
        self, *, agency_id: str, action: str, actor_user_id: str | None = None,
        target_type: str | None = None, target_id: str | None = None,
        detail: dict | None = None,
    ) -> AuditEntry:
        chain = self._by_agency.setdefault(str(agency_id), [])
        seq = len(chain) + 1
        prev = chain[-1].sha256 if chain else GENESIS
        ts, detail = _now(), detail or {}
        entry = AuditEntry(
            id=str(uuid.uuid4()), agency_id=str(agency_id), seq=seq, action=action,
            actor_user_id=actor_user_id, target_type=target_type, target_id=target_id,
            detail=detail, ts=ts, prev_sha256=prev,
            sha256=entry_hash(
                seq=seq, action=action, actor_user_id=actor_user_id,
                target_type=target_type, target_id=target_id, detail=detail,
                ts=ts, prev_sha256=prev,
            ),
        )
        chain.append(entry)
        return entry

    async def list_entries(self, *, agency_id: str, limit: int = 100) -> list[AuditEntry]:
        return list(reversed(self._by_agency.get(str(agency_id), [])))[:limit]

    async def verify_chain(self, *, agency_id: str) -> tuple[bool, int | None]:
        return _verify(self._by_agency.get(str(agency_id), []))

    def reset(self) -> None:
        """Test hook — memory only."""
        self._by_agency.clear()


@lru_cache
def _memory_repository() -> InMemoryAuditRepository:
    return InMemoryAuditRepository()


def _verify(entries: list[AuditEntry]) -> tuple[bool, int | None]:
    """Walk the chain; return (ok, seq of the FIRST bad entry).

    Returning where it broke matters: "the log is invalid" is not actionable,
    "entry 47 is the first that doesn't verify" points at what to investigate.
    """
    prev = GENESIS
    for e in sorted(entries, key=lambda x: x.seq):
        expected = entry_hash(
            seq=e.seq, action=e.action, actor_user_id=e.actor_user_id,
            target_type=e.target_type, target_id=e.target_id, detail=e.detail,
            ts=e.ts, prev_sha256=prev,
        )
        if e.prev_sha256 != prev or e.sha256 != expected:
            return False, e.seq
        prev = e.sha256
    return True, None


# --------------------------------------------------------------------------- #
# Postgres
# --------------------------------------------------------------------------- #


def _row_to_entry(row) -> AuditEntry:
    return AuditEntry(
        id=str(row.id), agency_id=str(row.agency_id), seq=row.seq or 0,
        action=row.action, actor_user_id=str(row.actor_user_id) if row.actor_user_id else None,
        target_type=row.target_type, target_id=str(row.target_id) if row.target_id else None,
        detail=row.detail or {}, ts=row.ts,
        sha256=(row.sha256 or b"").hex(), prev_sha256=(row.prev_sha256 or b"").hex(),
    )


class PostgresAuditRepository:
    """Writes ``core.audit_log``. The session is the caller's, so an audit entry
    commits with the action it describes — a separate transaction could leave a
    log entry for work that was then rolled back."""

    def __init__(self, session) -> None:
        self._session = session

    async def record(
        self, *, agency_id: str, action: str, actor_user_id: str | None = None,
        target_type: str | None = None, target_id: str | None = None,
        detail: dict | None = None,
    ) -> AuditEntry:
        from app.core.models import AuditLog

        last = (
            await self._session.execute(
                select(AuditLog)
                .where(AuditLog.agency_id == uuid.UUID(str(agency_id)))
                .order_by(AuditLog.seq.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        seq = (last.seq or 0) + 1 if last else 1
        prev = (last.sha256 or b"").hex() if last else GENESIS
        ts, detail = _now(), detail or {}
        digest = entry_hash(
            seq=seq, action=action, actor_user_id=actor_user_id,
            target_type=target_type, target_id=target_id, detail=detail,
            ts=ts, prev_sha256=prev,
        )
        row = AuditLog(
            id=uuid.uuid4(), agency_id=uuid.UUID(str(agency_id)),
            actor_user_id=uuid.UUID(str(actor_user_id)) if actor_user_id else None,
            action=action, target_type=target_type,
            target_id=uuid.UUID(str(target_id)) if _is_uuid(target_id) else None,
            detail=detail, ts=ts, seq=seq,
            sha256=bytes.fromhex(digest), prev_sha256=bytes.fromhex(prev),
        )
        self._session.add(row)
        await self._session.flush()
        return _row_to_entry(row)

    async def list_entries(self, *, agency_id: str, limit: int = 100) -> list[AuditEntry]:
        from app.core.models import AuditLog

        rows = (
            await self._session.execute(
                select(AuditLog)
                .where(AuditLog.agency_id == uuid.UUID(str(agency_id)))
                .order_by(AuditLog.seq.desc())
                .limit(limit)
            )
        ).scalars().all()
        return [_row_to_entry(r) for r in rows]

    async def verify_chain(self, *, agency_id: str) -> tuple[bool, int | None]:
        from app.core.models import AuditLog

        rows = (
            await self._session.execute(
                select(AuditLog)
                .where(AuditLog.agency_id == uuid.UUID(str(agency_id)))
                .order_by(AuditLog.seq)
            )
        ).scalars().all()
        return _verify([_row_to_entry(r) for r in rows])


def _is_uuid(value: str | None) -> bool:
    """``target_id`` is a uuid column, but some targets are business keys
    (``sess_ab12…``). Those are kept in ``detail`` rather than dropped."""
    if not value:
        return False
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


async def record_action(
    session,
    *,
    agency_id: str | None,
    action: str,
    actor_user_id: str | None = None,
    actor_name: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    target_label: str | None = None,
    detail: dict | None = None,
) -> AuditEntry | None:
    """Record one action. NEVER raises — see the module docstring.

    Pass the request's session in Postgres mode so the entry commits atomically
    with the change it describes; pass ``None`` to use the in-memory chain.

    ``actor_name`` and ``target_label`` are SNAPSHOTS, stored in ``detail``
    under reserved keys. An audit row identified only by uuids answers "who did
    what" with ``9f79eb96-…`` — unreadable to the investigator or court the trail
    exists for. They are captured at write time rather than joined at read time
    on purpose: if a user is later renamed or removed, or a case retitled, the
    entry must still say who acted and on what **at the time**. Same reasoning as
    ``intel.scam_sessions.persona_snapshot`` elsewhere in this codebase.
    """
    try:
        repo: AuditRepository = (
            PostgresAuditRepository(session)
            if session is not None and get_settings().persistence == "postgres"
            else _memory_repository()
        )
        if not agency_id:
            # No tenant → nothing to chain onto. Worth a warning: an unattributed
            # action is exactly what an audit trail exists to prevent.
            _log.warning("audit: dropping %s — no agency_id on the request", action)
            return None
        detail = dict(detail or {})
        if actor_name:
            detail["_actor"] = actor_name
        if target_label:
            detail["_target"] = target_label
        return await repo.record(
            agency_id=agency_id, action=action, actor_user_id=actor_user_id,
            target_type=target_type, target_id=target_id, detail=detail,
        )
    except Exception as exc:  # noqa: BLE001 - bookkeeping must not break the action
        _log.warning("audit: failed to record %s: %s: %s", action, type(exc).__name__, exc)
        return None


def reset_audit_store() -> None:
    """Sync test hook — clears the in-memory chain."""
    _memory_repository().reset()
