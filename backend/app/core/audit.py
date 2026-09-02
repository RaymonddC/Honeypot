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

**Denied actions are recorded too** — see ``record_denial`` at the bottom of
this module. A 403 an authenticated user collects while reaching for something
their role forbids is often the most security-relevant line in the whole trail,
and it used to vanish without trace.

**Why the audit trail is NOT mode-filtered** (and is the one agency-scoped table
migration ``20260823_18`` deliberately skipped). Every other table gained a
``data_mode = core.current_mode()`` RLS predicate for POC/LIVE evidentiary
isolation. Adding one here makes the trail report itself as TAMPERED, because
``verify_chain`` reads every row for the agency in ``seq`` order and walks
``prev_sha256`` — hiding any entry breaks the linkage. Measured over a chain of
poc,poc,live,live::

    unfiltered (owner):            (True, None)
    LIVE session, poc hidden:      (False, 3)    <- false tamper alarm
    POC session, live hidden:      (True, None)  <- SILENT TRUNCATION

The second is the dangerous one: truncating the TAIL of a hash chain is
undetectable — it verifies clean while records are missing, reintroducing
precisely the gap ``ittu_audit_entries_dropped_total`` exists to close.

It is also arguably wrong on the merits, not merely impractical. This trail
answers "everything that happened in this tenant", and an investigator asking
"was this case built from demo data" needs the POC and the LIVE actions in ONE
ordered sequence — the moment of transition is the most interesting entry in the
log, and a mode-partitioned trail is exactly where it would be invisible.
Provenance belongs IN the record; it must not decide who may read the record.

So mode is recorded as ``detail['_data_mode']`` (see ``_stamp_mode``) — inside
``entry_hash``, hence tamper-evident, and still filterable via
``detail->>'_data_mode'`` when a CALLER wants to narrow by mode. If you are here
to add the "missing" predicate: ``test_mode_isolation_pg.py`` will stop you, and
explains why in its failure message.

Memory mode keeps an in-process chain so POC demos and tests exercise the same
code path; only Postgres persists.
"""

import asyncio
import hashlib
import json
import logging
import random
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol, runtime_checkable

from sqlalchemy import or_, select, text
from sqlalchemy.exc import IntegrityError

from app.core import metrics
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
# Evidence LEAVING the system. The only READ we audit, deliberately: everything
# else here is a mutation, but "who downloaded the evidence pack" is a top
# insider-risk question in forensics — arguably more important than who edited a
# case title — and it was previously possible with no trace at all.
EVIDENCE_EXPORTED = "evidence.exported"
# User access management. Role grants and deactivations are the textbook reason
# an audit trail exists: they change who can do what, and the person best placed
# to hide such a change is the admin making it.
USER_CREATED = "user.created"
USER_ROLE_CHANGED = "user.role_changed"
USER_DEACTIVATED = "user.deactivated"
USER_REACTIVATED = "user.reactivated"
TRIAGE_ATTACHED = "triage.attached"
TRIAGE_PROMOTED = "triage.promoted"
# Route-level RBAC refusal. Every other constant here names a domain action, and
# a DENIED one keeps that name (``user.role_changed`` denied is still
# ``user.role_changed`` — see ``record_denial``). This one is the exception
# because there is no domain action to name: ``require_role`` rejects the caller
# during dependency resolution, so the handler — and with it any notion of what
# was being attempted beyond "this endpoint" — never runs.
ACCESS_FORBIDDEN = "access.forbidden"


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

    async def list_for_target(
        self, *, agency_id: str, target_id: str, limit: int = 100
    ) -> list[AuditEntry]: ...

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

    async def list_for_target(
        self, *, agency_id: str, target_id: str, limit: int = 100
    ) -> list[AuditEntry]:
        chain = self._by_agency.get(str(agency_id), [])
        return [e for e in chain if _targets(e, target_id)][:limit]

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


def _targets(entry: AuditEntry, target_id: str) -> bool:
    """Does this entry describe ``target_id``? Checks both the uuid column and
    the preserved business key, so memory and Postgres agree."""
    return entry.target_id == str(target_id) or (
        (entry.detail or {}).get("_target_id") == str(target_id)
    )


def _row_to_entry(row) -> AuditEntry:
    return AuditEntry(
        id=str(row.id), agency_id=str(row.agency_id), seq=row.seq or 0,
        action=row.action, actor_user_id=str(row.actor_user_id) if row.actor_user_id else None,
        target_type=row.target_type, target_id=str(row.target_id) if row.target_id else None,
        detail=row.detail or {}, ts=row.ts,
        sha256=(row.sha256 or b"").hex(), prev_sha256=(row.prev_sha256 or b"").hex(),
    )


# How many times to re-read the chain head and try again when another writer
# beat us to a sequence number.
#
# A linear hash chain cannot be appended to in parallel — writers to one agency
# MUST serialise — so the worst case is inherently "roughly one attempt per
# contending writer", and this budget is what actually decides whether an entry
# survives contention.
#
# Measured against pgserver with 8 simultaneous writers on one agency
# (tests/test_audit_denials_pg.py), 3 runs each:
#     5 attempts, no backoff  -> 0/3 runs kept all 8 entries
#     5 attempts, backoff     -> 1/3
#    10 attempts, no backoff  -> 3/3
#    10 attempts, backoff     -> 3/3
# So the budget dominates and the backoff is a secondary help, not the fix.
# Beyond ~10 concurrent writers on a SINGLE agency's chain an entry can still be
# dropped (loudly — see the ERROR at the bottom of record()). That is far past
# anything one agency's audit trail should be generating; if it is ever reached,
# the answer is to look at why, not to keep raising this number.
SEQ_RETRY_ATTEMPTS = 10

# Jittered backoff between attempts. Contending writers otherwise re-read the
# head in lockstep, pick the same next number, and collide again. Randomised
# rather than fixed, because a fixed delay just relocates the lockstep. Kept
# despite being secondary to the budget: it costs nothing and removes wasted
# round trips under contention.
SEQ_RETRY_BACKOFF_MAX_S = 0.02


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
        """Append one entry, re-trying if another writer took our slot.

        ``seq`` and ``prev_sha256`` are both derived from the chain head read at
        the top of this method, so two transactions that read the same head
        don't merely collide on a number — they produce two entries claiming the
        same position AND the same predecessor, which is a FORK. ``verify_chain``
        then reports the log as broken, and a reader has no way to tell a
        routine concurrent write from someone tampering with the record. That
        is the failure this loop and the ``uq_audit_log_agency_seq`` index
        (migration 20260822_17) exist to prevent.

        The index makes the collision loud; this loop makes it survivable. Each
        attempt runs inside a SAVEPOINT because a unique violation aborts the
        surrounding transaction in Postgres — without one, the caller's whole
        request would be poisoned by a conflict we intend to recover from.
        """
        from app.core.models import AuditLog

        last_error: Exception | None = None
        for attempt in range(1, SEQ_RETRY_ATTEMPTS + 1):
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
            ts, entry_detail = _now(), detail or {}
            digest = entry_hash(
                seq=seq, action=action, actor_user_id=actor_user_id,
                target_type=target_type, target_id=target_id, detail=entry_detail,
                ts=ts, prev_sha256=prev,
            )
            # Built fresh per attempt: rolling back to the savepoint expunges the
            # pending object, and re-adding a stale one would re-insert the seq
            # we just lost.
            row = AuditLog(
                id=uuid.uuid4(), agency_id=uuid.UUID(str(agency_id)),
                actor_user_id=uuid.UUID(str(actor_user_id)) if actor_user_id else None,
                action=action, target_type=target_type,
                target_id=uuid.UUID(str(target_id)) if _is_uuid(target_id) else None,
                detail=entry_detail, ts=ts, seq=seq,
                sha256=bytes.fromhex(digest), prev_sha256=bytes.fromhex(prev),
            )
            try:
                async with self._session.begin_nested():
                    self._session.add(row)
                    await self._session.flush()
                return _row_to_entry(row)
            except IntegrityError as exc:
                # Someone committed this seq while we were building ours.
                last_error = exc
                _log.info(
                    "audit: seq %s for agency %s was taken, re-reading the chain "
                    "head (attempt %d/%d)", seq, agency_id, attempt, SEQ_RETRY_ATTEMPTS,
                )
                await asyncio.sleep(random.uniform(0, SEQ_RETRY_BACKOFF_MAX_S))
            # Anything else propagates untouched — in particular a lock_timeout
            # (a plain DBAPIError, not an IntegrityError), which means the
            # conflicting row is UNCOMMITTED and held by a transaction we cannot
            # outwait. Re-reading cannot help there: the blocker is invisible to
            # us by definition, so every retry would pick the same seq and time
            # out again. See _record_denial_postgres for when that arises.

        # Budget exhausted. The caller (record_action / record_denial) will
        # swallow this and let the action stand — but an evidentiary entry has
        # just been lost, which is an ERROR, not a routine warning: this log line
        # is the only remaining trace that the action happened at all.
        _log.error(
            "audit: GAVE UP recording %s for agency %s after %d attempts — the "
            "entry is LOST. Sustained contention on this agency's chain.",
            action, agency_id, SEQ_RETRY_ATTEMPTS,
        )
        metrics.audit_dropped.inc(metrics.DROP_SEQ_CONTENTION)
        raise last_error  # type: ignore[misc]  # unreachable with attempts >= 1

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

    async def list_for_target(
        self, *, agency_id: str, target_id: str, limit: int = 100
    ) -> list[AuditEntry]:
        """Entries about one thing, OLDEST first, agency-scoped.

        Matches either column: a uuid target lands in ``target_id``, a business
        key in ``detail->>'_target_id'`` (see ``_preserve_business_key``).
        Filtered in SQL rather than by listing the agency's chain and filtering
        in Python — an agency with a long trail would otherwise need its whole
        history read to answer "what happened to this bundle".

        Oldest first because this is read as a narrative of one artifact
        (generated, then dispatched), the reverse of the ``/audit`` feed.
        """
        from app.core.models import AuditLog

        clauses = [AuditLog.detail["_target_id"].astext == str(target_id)]
        if _is_uuid(target_id):
            clauses.append(AuditLog.target_id == uuid.UUID(str(target_id)))
        rows = (
            await self._session.execute(
                select(AuditLog)
                .where(AuditLog.agency_id == uuid.UUID(str(agency_id)))
                .where(or_(*clauses))
                .order_by(AuditLog.seq)
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


def _preserve_business_key(detail: dict, target_id: str | None) -> None:
    """Keep a non-uuid ``target_id`` in ``detail`` under ``_target_id``.

    ``core.audit_log.target_id`` is a uuid COLUMN, but half this codebase
    identifies things with business keys — ``act_9f3…`` (bundle), ``doc_…``,
    ``ent_…``, ``sess_…``. ``PostgresAuditRepository.record`` drops anything that
    is not a uuid, so under Postgres those entries stored **no reference to what
    they were about at all**: five of the wired actions (bundle generated,
    dispatch sent, evidence exported, entity reviewed, triage attached) lost
    their target. ``_is_uuid``'s docstring claimed the key was "kept in detail
    rather than dropped" — that was the intent, never the implementation, and it
    was verified dropped against a real Postgres before this was written.

    Kept in ``detail`` rather than widened into a text column because ``detail``
    is inside ``entry_hash``: the reference is tamper-evident for free, and no
    migration is needed. Entries written before this stay valid — they simply
    cannot be filtered by target, which is why this is not backfilled.
    """
    if target_id and not _is_uuid(target_id):
        detail["_target_id"] = str(target_id)


def _stamp_mode(detail: dict) -> None:
    """Record the writing deployment's mode as ``detail['_data_mode']``.

    **In ``detail`` rather than a column, and NOT an RLS predicate — both
    deliberate.** See this module's "Why the audit trail is not mode-filtered"
    note. In short: ``detail`` is inside ``entry_hash``, so the provenance is
    tamper-evident for free and needs no migration, and it is still filterable
    in SQL (``detail->>'_data_mode'``, the same trick ``list_for_target`` uses
    on ``_target_id``) — so the usual "hashed OR queryable" trade-off does not
    apply here. A column would have been outside the hash AND needed a backfill
    decision for existing rows that cannot be truthfully assigned a mode.

    Entries written before this simply lack the key. That asserts nothing
    retroactive, which is the point: back-stamping them would be a claim about
    an append-only evidentiary record that we cannot support.
    """
    detail["_data_mode"] = get_settings().mode


def _is_uuid(value: str | None) -> bool:
    """Whether ``target_id`` fits the uuid column. Business keys do not — see
    ``_preserve_business_key``, which keeps those in ``detail``."""
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
    request=None,
    detail: dict | None = None,
) -> AuditEntry | None:
    """Record one action. NEVER raises — see the module docstring.

    Pass the request's session in Postgres mode so the entry commits atomically
    with the change it describes; pass ``None`` to use the in-memory chain.

    ``request`` (when passed) adds ``_ip``/``_user_agent``/``_request_id`` —
    origin is corroboration, not proof: anything before our edge is outside our
    trust boundary. ``actor_name`` and ``target_label`` are SNAPSHOTS, stored in ``detail``
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
            metrics.audit_dropped.inc(metrics.DROP_NO_AGENCY)
            return None
        detail = dict(detail or {})
        if actor_name:
            detail["_actor"] = actor_name
        if target_label:
            detail["_target"] = target_label
        _preserve_business_key(detail, target_id)
        _stamp_mode(detail)
        # Where it came from, and the id tying this row to its request log line.
        # Standard audit practice records who acted AND from what device and
        # location (CloudTrail/SOC 2); we recorded only who and when.
        if request is not None:
            from app.core.requests import client_origin, current_request_id

            origin = client_origin(request)
            if origin.get("ip"):
                detail["_ip"] = origin["ip"]
            if origin.get("user_agent"):
                detail["_user_agent"] = origin["user_agent"]
            if current_request_id():
                detail["_request_id"] = current_request_id()
        entry = await repo.record(
            agency_id=agency_id, action=action, actor_user_id=actor_user_id,
            target_type=target_type, target_id=target_id, detail=detail,
        )
        metrics.audit_written.inc("success")
        return entry
    except Exception as exc:  # noqa: BLE001 - bookkeeping must not break the action
        _log.warning("audit: failed to record %s: %s: %s", action, type(exc).__name__, exc)
        # The action still stands (that is the contract), but an evidentiary
        # entry is now permanently missing and verify_chain CANNOT see that —
        # no gap appears in the prev-links for an entry that never existed. This
        # counter is the only thing that makes the loss detectable.
        metrics.audit_dropped.inc(
            metrics.DROP_SEQ_CONTENTION
            if isinstance(exc, IntegrityError)
            else metrics.DROP_ERROR
        )
        return None


# --------------------------------------------------------------------------- #
# Denied actions
# --------------------------------------------------------------------------- #

# ``detail["_outcome"]``. Absent means SUCCESS: every entry written before this
# existed is a success, and nothing had to be backfilled to say so. Recording
# the outcome in ``detail`` rather than in a new column is deliberate —
# ``entry_hash`` hashes ``detail``, so an outcome put there is tamper-evident
# for free, whereas a new column would be outside the hash unless ``entry_hash``
# changed, and changing ``entry_hash`` would break verification of every entry
# already written.
OUTCOME_DENIED = "denied"

# Volume cap: at most this many denials per (agency, actor, action) per window.
# A misconfigured client retrying a forbidden call in a loop must not be able to
# bury a year of real activity under its own 403s — the chain is evidence a
# human has to read. Five is enough to establish a pattern ("this is not a
# one-off fat-finger"); the sixth adds nothing the fifth didn't.
DENIAL_CAP = 5
DENIAL_WINDOW_SECONDS = 300

# How long the denial's own transaction will wait for a lock before giving up.
# Short on purpose: the only wait it can encounter that matters is one it can
# never win (see ``_record_denial_postgres``), so waiting longer buys nothing
# and stalls the 403 the caller is owed. Long enough to absorb an ordinary
# concurrent commit, short enough that a human never notices.
DENIAL_LOCK_TIMEOUT_MS = 750

# (agency, actor, action) -> (window start on the monotonic clock, count).
#
# In-process, and therefore PER WORKER: with N uvicorn workers the effective cap
# is DENIAL_CAP × N, because each worker keeps its own counter and a load
# balancer will spread one client's retries across them. That is accepted — the
# cap exists to bound volume, not to be exact, and the alternative (a shared
# counter in Postgres or Redis) buys precision we do not need at the price of a
# round trip on every 403. Monotonic clock so a system clock adjustment cannot
# freeze or reset the window.
_denial_counts: dict[tuple[str, str, str], tuple[float, int]] = {}


def _claim_denial_slot(agency_id: str, actor_user_id: str, action: str) -> int | None:
    """Take a slot in the current window. Returns the 1-based count, or ``None``
    when this denial is over the cap and must not be recorded."""
    key = (str(agency_id), str(actor_user_id or ""), action)
    now = time.monotonic()
    start, count = _denial_counts.get(key, (now, 0))
    if now - start >= DENIAL_WINDOW_SECONDS:
        start, count = now, 0  # window rolled over
    count += 1
    _denial_counts[key] = (start, count)
    return count if count <= DENIAL_CAP else None


def _is_lock_timeout(exc: BaseException) -> bool:
    """SQLSTATE 55P03 (``lock_not_available``) — matched on the code, not the
    message, so a driver upgrade or a non-English server locale can't silently
    turn this into an unrecognised generic failure."""
    return getattr(getattr(exc, "orig", None), "sqlstate", None) == "55P03"


def _already_recorded_this_request(request, signature: tuple) -> bool:
    """One request must not produce the same denial entry twice.

    It can otherwise: ``require_role(ADMIN_ROLES)`` is instantiated twice for the
    admin API (once on the router, once inside ``get_user_admin_repository``),
    and FastAPI's dependency cache does not dedupe two *distinct* closures, so
    both fire on the same rejected request.

    Keyed on ``request.state`` — server-side state belonging to this one
    request — and NOT on the request id, which is honoured from an inbound
    ``X-Request-ID`` header (see ``core/requests.py``) and would therefore let a
    client suppress its own denials by sending a constant one.
    """
    if request is None:
        return False
    seen = getattr(request.state, "audit_denials", None)
    if seen is None:
        seen = set()
        request.state.audit_denials = seen
    if signature in seen:
        return True
    seen.add(signature)
    return False


async def record_denial(
    *,
    agency_id: str | None,
    action: str,
    denial_code: str,
    actor_user_id: str | None = None,
    actor_name: str | None = None,
    actor_role: str | None = None,
    target_type: str | None = None,
    target_id: str | None = None,
    target_label: str | None = None,
    request=None,
    detail: dict | None = None,
) -> AuditEntry | None:
    """Record an action an authenticated actor was REFUSED. NEVER raises.

    Same never-raises guarantee as ``record_action``, and one more besides: this
    is called on a path that is already returning a clean 4xx, so a failure here
    must never turn that into a 500.

    **The action keeps its domain name.** A denied role change is
    ``user.role_changed`` with ``detail["_outcome"] = "denied"`` and
    ``detail["_denial_code"]``, not ``user.role_changed.denied`` — "everything
    Budi did" has to stay one query, which a parallel vocabulary of
    ``.denied`` action names would quietly break.

    **Takes no session, on purpose.** A request runs inside ONE transaction
    (``app/core/db.py``'s ``_tenant_scoped_session`` — ``async with
    SessionLocal() as session, session.begin():``). A guard raising
    ``HTTPException`` leaves that context with an exception, so the transaction
    ROLLS BACK — and a denial written on the request's session rolls back with
    it, leaving nothing. It would still pass in memory mode, where there is no
    transaction to lose, which is exactly how that bug reaches production. So
    this opens its own short-lived session and commits it independently, and
    refuses to accept a session argument at all rather than trust every call
    site to pass the right one.

    That is the opposite of the success path, deliberately: a success commits
    atomically WITH the change it describes (an entry for work that was then
    rolled back would be a lie). A denial describes something that did NOT
    happen, so it has nothing to be atomic with.

    **Which agency's chain.** The ACTOR's, even when they were reaching at
    another agency's resource — the reverse of the success path, which chains
    under the target. Nothing happened to the target, and writing into another
    tenant's evidentiary chain on the strength of an outsider's rejected attempt
    would let anyone with a login append rows to a chain a court reads. The
    target agency is named in ``detail`` when it is known and different.
    """
    try:
        if not agency_id:
            _log.warning("audit: dropping denied %s — no agency_id on the request", action)
            metrics.audit_dropped.inc(metrics.DROP_NO_AGENCY)
            return None

        signature = (action, denial_code, str(target_id or ""))
        if _already_recorded_this_request(request, signature):
            return None

        slot = _claim_denial_slot(str(agency_id), str(actor_user_id or ""), action)
        if slot is None:
            # Over the cap. Logged (not silent) so the volume is still visible
            # to operations even though it stays out of the evidentiary chain.
            _log.warning(
                "audit: suppressing denied %s (%s) by %s — over %d per %ds",
                action, denial_code, actor_user_id, DENIAL_CAP, DENIAL_WINDOW_SECONDS,
            )
            # Suppressed, not lost: a deliberate policy decision, counted
            # separately so it can never be mistaken for a failure to write.
            metrics.audit_denials_suppressed.inc()
            return None

        detail = dict(detail or {})
        detail["_outcome"] = OUTCOME_DENIED
        detail["_denial_code"] = denial_code
        if slot == DENIAL_CAP:
            # Make suppression visible IN the chain. Without this marker a
            # capped chain and a quiet one look identical, and a reader would
            # conclude the attempts stopped when they were merely no longer
            # being written down.
            detail["_denial_cap_reached"] = True
            detail["_denial_cap"] = f"{DENIAL_CAP} per {DENIAL_WINDOW_SECONDS}s per worker"
        if actor_name:
            detail["_actor"] = actor_name
        if actor_role:
            detail["_actor_role"] = actor_role
        if target_label:
            detail["_target"] = target_label
        _preserve_business_key(detail, target_id)
        _stamp_mode(detail)
        if request is not None:
            from app.core.requests import client_origin, current_request_id

            origin = client_origin(request)
            if origin.get("ip"):
                detail["_ip"] = origin["ip"]
            if origin.get("user_agent"):
                detail["_user_agent"] = origin["user_agent"]
            if current_request_id():
                detail["_request_id"] = current_request_id()

        if get_settings().persistence != "postgres":
            entry = await _memory_repository().record(
                agency_id=str(agency_id), action=action, actor_user_id=actor_user_id,
                target_type=target_type, target_id=target_id, detail=detail,
            )
        else:
            entry = await _record_denial_postgres(
                agency_id=str(agency_id), action=action, actor_user_id=actor_user_id,
                actor_role=actor_role, target_type=target_type, target_id=target_id,
                detail=detail,
            )
        metrics.audit_written.inc("denied")
        return entry
    except Exception as exc:  # noqa: BLE001 - must never turn a 403 into a 500
        if _is_lock_timeout(exc):
            # Not a generic failure — a specific, diagnosable one worth naming,
            # because the log line is the ONLY record that the attempt happened.
            _log.error(
                "audit: DROPPED denied %s (%s) by %s — this agency's next chain "
                "position is held by an uncommitted row in the enclosing "
                "transaction, which cannot be waited out from here. The refusal "
                "still stands; the attempt is NOT in the trail.",
                action, denial_code, actor_user_id,
            )
            metrics.audit_dropped.inc(metrics.DROP_CHAIN_HEAD_UNCOMMITTED)
        else:
            _log.warning(
                "audit: failed to record denied %s (%s): %s: %s",
                action, denial_code, type(exc).__name__, exc,
            )
            metrics.audit_dropped.inc(metrics.DROP_ERROR)
        return None


async def _record_denial_postgres(
    *, agency_id: str, action: str, actor_user_id: str | None, actor_role: str | None,
    target_type: str | None, target_id: str | None, detail: dict,
) -> AuditEntry:
    """The separate, self-committing transaction — see ``record_denial``.

    ``app.core.db`` is imported as a MODULE and ``SessionLocal`` read off it at
    call time, so a test can point it at another engine; binding the name at
    import time would freeze whichever sessionmaker existed then (the same
    reason ``worker_session`` consults its override at call time).

    The new session carries no request context, so it must set the RLS vars
    itself — ``core.audit_log``'s insert policy is ``agency_id =
    core.current_agency()``, which fails closed against an unset one.

    **``lock_timeout`` is set here and nowhere else, and it is load-bearing.**
    This is the only writer that opens a second connection from *inside* another
    open transaction, which creates a wait no database can resolve: if the
    enclosing request transaction has already written an uncommitted row at the
    chain position we want, our INSERT waits on that transaction's id — while
    that transaction waits on this ``await``. Postgres reports no deadlock,
    because the enclosing side is not blocked on a database resource at all; it
    is blocked in Python. Verified empirically: it hangs indefinitely rather
    than failing. (An advisory lock has exactly the same shape, which is why
    serialising allocation that way was rejected.)

    A short ``lock_timeout`` turns that hang into a fast, loud
    ``LockNotAvailableError``, which ``record_denial`` reports and drops. The
    denial is genuinely unserviceable in that state — the correct chain position
    is occupied by a row that has neither committed nor rolled back — so failing
    in under a second beats stalling a request forever. It is scoped ``LOCAL``
    to this throwaway transaction, so no business query ever inherits it.
    """
    from app.core import db as db_module

    async with db_module.SessionLocal() as session, session.begin():
        await session.execute(text(f"SET LOCAL lock_timeout = '{DENIAL_LOCK_TIMEOUT_MS}ms'"))
        for var, value in (
            ("app.current_agency", str(agency_id)),
            ("app.current_user", str(actor_user_id or "")),
            ("app.current_role", actor_role or ""),
        ):
            await session.execute(
                text("SELECT set_config(:var, :value, true)"),
                {"var": var, "value": value},
            )
        return await PostgresAuditRepository(session).record(
            agency_id=agency_id, action=action, actor_user_id=actor_user_id,
            target_type=target_type, target_id=target_id, detail=detail,
        )


def is_denied(entry_detail: dict | None) -> bool:
    """Whether a stored entry records a REFUSED action.

    Absence of ``_outcome`` reads as success — that is what makes every entry
    written before denials existed correct without a backfill.
    """
    return (entry_detail or {}).get("_outcome") == OUTCOME_DENIED


def reset_audit_store() -> None:
    """Sync test hook — clears the in-memory chain and the denial rate counters."""
    _memory_repository().reset()
    _denial_counts.clear()
