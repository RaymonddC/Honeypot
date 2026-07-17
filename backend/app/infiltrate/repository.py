"""INFILTRATE persistence boundary (docs/Persistence-Plan.md P-2).

Repository interface behind the 4 intel stores (sessions/messages/entities/
syndicates) that ``infiltrate/service.py`` used to own as bare module-level
dicts. An in-memory impl backs the POC + the existing fast test suite today;
a Postgres impl lands in P-2b.

Persistence is selected by ``settings.persistence`` — a separate axis from the
poc/live MODE registry (``app.core.adapters``). MODE picks *which adapter*
answers an external boundary (channel/llm/tts/...); persistence picks *where
state lives*. The two are orthogonal, so this factory intentionally does NOT
go through ``app.core.adapters.register`` / ``get_adapter`` (P-2 lead call).
"""

import json
import uuid
from datetime import datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from fastapi import Depends
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.auth import get_optional_current_user as _get_optional_current_user
from app.core.config import get_settings
from app.core.db import get_optional_tenant_session
from app.infiltrate.custody import GENESIS, message_hash
from app.intel.models import CrimeClassification, Entity, Message, ScamSession, Syndicate, SyndicateMember

if TYPE_CHECKING:
    from app.infiltrate.service import (
        ClassificationOut,
        CustodyOut,
        EntityOut,
        EscalationOut,
        MessageOut,
        SessionOut,
        SignalOut,
        SyndicateOut,
    )


def _out_models():
    """Deferred import of the Pydantic response models.

    ``service.py`` imports THIS module at load time (for the Protocol/repo
    factory), so importing its models back at module scope here would be a
    circular import. Calling this from inside a method — after both modules
    have finished loading — sidesteps it. (Type hints above stay under
    ``TYPE_CHECKING``, which never executes, so they're exempt.)
    """
    from app.infiltrate import service as _service

    return _service


@runtime_checkable
class InfiltrateRepository(Protocol):
    """Storage surface ``infiltrate/service.py`` needs — derived from the
    actual read/write call sites of the 4 stores it used to own directly.
    Returns/accepts the SAME Pydantic models the service already builds
    (``SessionOut``/``MessageOut``/``EntityOut``/``SyndicateOut``); the
    contract at the service boundary does not change.

    Every read/write method is ``async`` (P-2b): the Postgres impl does real
    I/O over an ``AsyncSession``, and a Protocol can't have one impl awaiting
    and another not. ``InMemoryInfiltrateRepository``'s methods are ``async``
    too — trivial 1-line coroutines wrapping the same dict ops, no behavior
    change — so both impls satisfy one signature. ``reset()`` stays sync: it's
    a memory-only test hook (``service.reset_stores`` calls the singleton
    directly, never through this Protocol — see its docstring).
    """

    # -- sessions ----------------------------------------------------------- #
    async def save_session(self, session: "SessionOut") -> None: ...

    async def get_session(self, session_id: str) -> "SessionOut | None": ...

    async def list_sessions(self) -> list["SessionOut"]: ...

    # -- messages (keyed by session_id) -------------------------------------- #
    async def save_messages(self, session_id: str, messages: list["MessageOut"]) -> None:
        """Set/replace the full message list for a session (first assembly)."""
        ...

    async def append_messages(self, session_id: str, messages: list["MessageOut"]) -> None:
        """Add messages to an existing session's transcript (live ``/turn``)."""
        ...

    async def get_messages(self, session_id: str) -> list["MessageOut"] | None: ...

    # -- entities ------------------------------------------------------------- #
    async def save_entity(self, entity: "EntityOut") -> None:
        """Insert a new entity, or persist in-place edits (e.g. review-status
        updates — the service mutates the returned object, then re-saves)."""
        ...

    async def get_entity(self, entity_id: str) -> "EntityOut | None": ...

    async def list_entities(
        self, session_id: str | None = None, status: str | None = None
    ) -> list["EntityOut"]: ...

    # -- syndicates ------------------------------------------------------------ #
    async def save_syndicate(self, syndicate: "SyndicateOut") -> None: ...

    async def list_syndicates(self) -> list["SyndicateOut"]: ...

    # -- test/seed hook ---------------------------------------------------------- #
    def reset(self) -> None:
        """Clear all stored state — existing test hook (``service.reset_stores``).
        Sync, memory-only (see class docstring)."""
        ...


class InMemoryInfiltrateRepository:
    """POC impl — the 4 module-level dicts that used to live in service.py,
    unchanged in behavior, moved behind ``InfiltrateRepository``.

    Methods are ``async`` to satisfy the Protocol (P-2b) — trivial coroutines
    around the same synchronous dict ops, no actual I/O, no behavior change."""

    def __init__(self) -> None:
        self._sessions: dict[str, "SessionOut"] = {}
        self._messages: dict[str, list["MessageOut"]] = {}
        self._entities: dict[str, "EntityOut"] = {}
        self._syndicates: dict[str, "SyndicateOut"] = {}

    async def save_session(self, session: "SessionOut") -> None:
        self._sessions[session.id] = session

    async def get_session(self, session_id: str) -> "SessionOut | None":
        return self._sessions.get(session_id)

    async def list_sessions(self) -> list["SessionOut"]:
        return list(self._sessions.values())

    async def save_messages(self, session_id: str, messages: list["MessageOut"]) -> None:
        self._messages[session_id] = messages

    async def append_messages(self, session_id: str, messages: list["MessageOut"]) -> None:
        self._messages.setdefault(session_id, []).extend(messages)

    async def get_messages(self, session_id: str) -> list["MessageOut"] | None:
        return self._messages.get(session_id)

    async def save_entity(self, entity: "EntityOut") -> None:
        self._entities[entity.id] = entity

    async def get_entity(self, entity_id: str) -> "EntityOut | None":
        return self._entities.get(entity_id)

    async def list_entities(
        self, session_id: str | None = None, status: str | None = None
    ) -> list["EntityOut"]:
        items = list(self._entities.values())
        if session_id is not None:
            items = [e for e in items if e.session_id == session_id]
        if status is not None:
            items = [e for e in items if e.review_status == status]
        return items

    async def save_syndicate(self, syndicate: "SyndicateOut") -> None:
        self._syndicates[syndicate.id] = syndicate

    async def list_syndicates(self) -> list["SyndicateOut"]:
        return list(self._syndicates.values())

    def reset(self) -> None:
        self._sessions.clear()
        self._messages.clear()
        self._entities.clear()
        self._syndicates.clear()


@lru_cache
def _memory_repository() -> InMemoryInfiltrateRepository:
    """Process-wide singleton (mirrors ``get_settings()``'s caching) so the
    repo behaves exactly like the module dicts it replaces — one store per
    process, shared across requests, not re-created per call."""
    return InMemoryInfiltrateRepository()


# --------------------------------------------------------------------------- #
# Postgres impl (P-2b) — intel.scam_sessions/messages/entities/syndicates(+
# syndicate_members)/crime_classifications, RLS-scoped by an already-open
# AsyncSession (see app.core.db.get_optional_tenant_session).
#
# Id mapping (migration 20260716_07): every app-level id
# (``session.id``/``message.id``/etc, e.g. "sess_xxxx") is stored in that
# table's ``public_id`` column; the ``id uuid`` PK is a surrogate used only
# for FK plumbing and is never returned to a caller. Every lookup below is
# therefore keyed off ``public_id``, and every FK write first resolves the
# referenced row's surrogate uuid.
#
# Fields with no column of their own:
#   - ``persona`` (embedded PersonaOut)  -> scam_sessions.persona_snapshot (JSONB)
#   - ``escalations``/``scam_signals``   -> the referenced message's own
#     ``meta`` JSONB, under private keys ("escalations"/"scam_signals") that
#     are stripped back out before a MessageOut is returned to a caller.
#   - ``entity.context``                 -> entities.provenance["__context"],
#     stripped back out before an EntityOut is returned.
#   - ``classification.signals``         -> not stored at all — it's exactly
#     ``[s.signal for s in scam_signals]`` (see app/infiltrate/classifier.py),
#     so it's re-derived from the message-meta reconstruction above.
#   - ``custody.chain_intact``           -> never stored, always recomputed by
#     re-verifying the stored hash chain (the whole point of a custody chain).
#   - ``custody.genesis``                -> the fixed GENESIS constant.
#   - ``message_count``/``entity_count``/``syndicate.session_ids`` -> derived
#     via COUNT/DISTINCT over the stored rows.
# --------------------------------------------------------------------------- #


def _safe_uuid(value: str | None) -> uuid.UUID | None:
    """``session.case_id`` is a free-text business key elsewhere in this
    codebase (UNCOVER's "CASE-2026-0142", not a UUID) but ``scam_sessions.
    case_id`` is a uuid column pointing at a not-yet-wired-up ``core.cases``
    row (case management is a later phase — docs/Persistence-Plan.md). Store
    it when it happens to parse as a UUID, drop it silently otherwise rather
    than fail the whole session save over an optional, currently-unused field."""
    if not value:
        return None
    try:
        return uuid.UUID(value)
    except ValueError:
        return None


def _collect_message_annotations(session: "SessionOut") -> dict[str, dict]:
    """Group a session's escalations/scam_signals by the message they're
    attributed to — the shape that gets merged into that message's ``meta``."""
    patches: dict[str, dict] = {}
    for esc in session.escalations:
        if not esc.message_id:
            continue
        patches.setdefault(esc.message_id, {}).setdefault("escalations", []).append(
            {"reason": esc.reason, "detail": esc.detail, "ts": esc.ts.isoformat() if esc.ts else None}
        )
    for sig in session.scam_signals:
        if not sig.message_id:
            continue
        patches.setdefault(sig.message_id, {}).setdefault("scam_signals", []).append(
            {"signal": sig.signal, "detail": sig.detail}
        )
    return patches


def _extract_annotations(
    svc, rows: list[Message]
) -> tuple[list["EscalationOut"], list["SignalOut"]]:
    """Inverse of ``_collect_message_annotations`` — rebuild escalations/
    scam_signals from the messages' stored meta, in seq order."""
    escalations: list = []
    scam_signals: list = []
    for row in rows:
        meta = row.meta or {}
        for esc in meta.get("escalations", []):
            ts = esc.get("ts")
            escalations.append(svc.EscalationOut(
                reason=esc.get("reason", ""), detail=esc.get("detail", ""),
                message_id=row.public_id,
                ts=datetime.fromisoformat(ts) if ts else None,
            ))
        for sig in meta.get("scam_signals", []):
            scam_signals.append(svc.SignalOut(
                signal=sig.get("signal", ""), detail=sig.get("detail", ""),
                message_id=row.public_id,
            ))
    return escalations, scam_signals


def _clean_meta(meta: dict | None) -> dict:
    """Strip the repo-internal escalation/scam_signal annotation keys back
    out — a returned ``MessageOut.meta`` must match exactly what the service
    originally built, not our storage trick on top of it."""
    return {k: v for k, v in (meta or {}).items() if k not in ("escalations", "scam_signals")}


def _build_custody(svc, session_public_id: str, rows: list[Message]) -> "CustodyOut":
    """Re-verify the hash chain from the stored rows rather than trust a
    persisted flag — see the module docstring on why ``chain_intact`` is
    never stored."""
    chain_intact = True
    prev = GENESIS
    for row in rows:
        sha = row.sha256.hex()
        prevh = row.prev_sha256.hex()
        if prevh != prev:
            chain_intact = False
            break
        expected = message_hash(
            row.seq, session_public_id, row.direction, row.content or "", row.ts, prevh
        )
        if expected != sha:
            chain_intact = False
            break
        prev = sha
    head = rows[-1].sha256.hex() if rows else GENESIS
    return svc.CustodyOut(messages_logged=len(rows), chain_intact=chain_intact, head_sha256=head)


def _message_out_from_row(
    svc, row: Message, session_public_id: str, entities_by_message: dict[str, list],
) -> "MessageOut":
    return svc.MessageOut(
        id=row.public_id, session_id=session_public_id, seq=row.seq, direction=row.direction,
        content=row.content or "", ts=row.ts,
        sha256=row.sha256.hex(), prev_sha256=row.prev_sha256.hex(),
        meta=_clean_meta(row.meta), entities=entities_by_message.get(row.public_id, []),
    )


def _entity_out_from_row(
    svc, row: Entity, session_public_id: str | None, message_public_id: str | None,
) -> "EntityOut":
    provenance = dict(row.provenance or {})
    context = provenance.pop("__context", "")
    return svc.EntityOut(
        id=row.public_id, session_id=session_public_id or "", message_id=message_public_id,
        type=row.type, value=row.value, normalized_value=row.normalized_value or "",
        chain=row.chain, bank_name=row.bank_name, context=context, method=row.method,
        confidence=float(row.confidence) if row.confidence is not None else 0.0,
        review_status=row.review_status, provenance=provenance, data_mode=row.data_mode,
        created_at=row.created_at,
    )


class PostgresInfiltrateRepository:
    """Postgres impl (P-2b) — see the module-level notes above for the id and
    field mapping. Constructed PER REQUEST (or per lifespan-seed call) with an
    already RLS-scoped ``AsyncSession`` (``app.current_agency/user/role`` set
    by the caller) plus the ``agency_id``/``data_mode`` to stamp on every
    write. RLS filters reads by agency already; every query below ALSO filters
    by ``agency_id`` explicitly — defense in depth, per the P-2b brief."""

    def __init__(self, session: AsyncSession, *, agency_id: uuid.UUID, data_mode: str) -> None:
        self._session = session
        self._agency_id = agency_id
        self._data_mode = data_mode
        # message public_id -> annotation patch, for escalations/scam_signals
        # attached via save_session() BEFORE the referenced message row exists
        # yet (the first-assembly flow saves the session before its messages —
        # required by the messages.session_id FK). Drained by _insert_messages.
        self._pending_message_meta: dict[str, dict] = {}
        # entity public_id -> {"session_id"|"message_id": referenced public_id},
        # for FK fields save_entity() couldn't resolve yet. service.py's real
        # write order is entities FIRST, then the session, then the messages
        # (_build_session saves every turn's entities inside the loop, before
        # the session/messages exist at all) — so entities.session_id/
        # message_id routinely can't resolve at save_entity() time. Drained by
        # save_session() (resolves "session_id") and _insert_messages()
        # (resolves "message_id") once those rows actually exist.
        self._pending_entity_links: dict[str, dict[str, str]] = {}

    # -- id resolution (public_id -> surrogate uuid) -------------------------- #

    async def _get_session_uuid(self, public_id: str) -> uuid.UUID | None:
        return (
            await self._session.execute(
                select(ScamSession.id).where(ScamSession.public_id == public_id)
            )
        ).scalar_one_or_none()

    async def _get_message_uuid(self, public_id: str) -> uuid.UUID | None:
        return (
            await self._session.execute(select(Message.id).where(Message.public_id == public_id))
        ).scalar_one_or_none()

    async def _get_entity_uuid(self, public_id: str) -> uuid.UUID | None:
        return (
            await self._session.execute(select(Entity.id).where(Entity.public_id == public_id))
        ).scalar_one_or_none()

    async def _resolve_pending_entity_links(
        self, field: str, referenced_public_id: str, resolved_uuid: uuid.UUID,
    ) -> None:
        """Now that ``referenced_public_id`` (a session or message) has a real
        row, backfill it onto any entity that pointed at it before it existed
        (see ``_pending_entity_links``). ``field`` is always one of the two
        hardcoded literals below — never caller/user input — so the f-string
        column name is safe."""
        assert field in ("session_id", "message_id")
        to_clear = [
            entity_id
            for entity_id, pending in self._pending_entity_links.items()
            if pending.get(field) == referenced_public_id
        ]
        for entity_id in to_clear:
            await self._session.execute(
                text(f"UPDATE intel.entities SET {field} = :val WHERE public_id = :entity_id"),
                {"val": resolved_uuid, "entity_id": entity_id},
            )
            del self._pending_entity_links[entity_id][field]
            if not self._pending_entity_links[entity_id]:
                del self._pending_entity_links[entity_id]

    # -- sessions ----------------------------------------------------------- #

    async def save_session(self, session: "SessionOut") -> None:
        values = dict(
            public_id=session.id,
            case_id=_safe_uuid(session.case_id),
            agency_id=self._agency_id,
            persona_snapshot=session.persona.model_dump(),
            channel_type=session.channel_type,
            channel=session.channel,
            channel_ref=session.channel_ref,
            crime_type=session.crime_type,
            status=session.status,
            data_mode=self._data_mode,
            started_at=session.started_at,
            ended_at=session.ended_at,
        )
        stmt = pg_insert(ScamSession).values(id=uuid.uuid4(), **values)
        stmt = stmt.on_conflict_do_update(index_elements=[ScamSession.public_id], set_=values)
        await self._session.execute(stmt)

        session_uuid = await self._get_session_uuid(session.id)
        await self._resolve_pending_entity_links("session_id", session.id, session_uuid)

        if session.classification is not None:
            await self._session.execute(
                pg_insert(CrimeClassification).values(
                    id=uuid.uuid4(),
                    session_id=session_uuid,
                    agency_id=self._agency_id,
                    crime_type=session.classification.crime_type,
                    confidence=session.classification.confidence,
                    model_version=session.classification.model_version,
                    data_mode=self._data_mode,
                )
            )

        patches = _collect_message_annotations(session)
        if patches:
            applied = await self._apply_message_annotations(patches)
            for message_id in applied:
                patches.pop(message_id, None)
            self._pending_message_meta.update(patches)  # leftover: message not saved yet

    async def _apply_message_annotations(self, patches: dict[str, dict]) -> set[str]:
        """UPDATE-merge each patch into its message's meta; returns the
        public_ids that actually matched a row (so callers can tell which
        patches still need to wait for ``_insert_messages``)."""
        applied: set[str] = set()
        for message_id, patch in patches.items():
            result = await self._session.execute(
                text(
                    "UPDATE intel.messages "
                    "SET meta = COALESCE(meta, '{}'::jsonb) || CAST(:patch AS jsonb) "
                    "WHERE public_id = :public_id"
                ),
                {"patch": json.dumps(patch), "public_id": message_id},
            )
            if result.rowcount:
                applied.add(message_id)
        return applied

    async def get_session(self, session_id: str) -> "SessionOut | None":
        row = (
            await self._session.execute(
                select(ScamSession).where(
                    ScamSession.public_id == session_id, ScamSession.agency_id == self._agency_id
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return await self._session_out_from_row(row)

    async def list_sessions(self) -> list["SessionOut"]:
        rows = (
            await self._session.execute(
                select(ScamSession)
                .where(ScamSession.agency_id == self._agency_id)
                .order_by(ScamSession.started_at)
            )
        ).scalars().all()
        return [await self._session_out_from_row(row) for row in rows]

    async def _session_out_from_row(self, row: ScamSession) -> "SessionOut":
        svc = _out_models()
        msg_rows = (
            await self._session.execute(
                select(Message).where(Message.session_id == row.id).order_by(Message.seq)
            )
        ).scalars().all()

        ent_stmt = (
            select(Entity, ScamSession.public_id, Message.public_id)
            .select_from(Entity)
            .outerjoin(ScamSession, Entity.session_id == ScamSession.id)
            .outerjoin(Message, Entity.message_id == Message.id)
            .where(Entity.session_id == row.id, Entity.agency_id == self._agency_id)
        )
        ent_rows = (await self._session.execute(ent_stmt)).all()

        entities_by_message: dict[str, list] = {}
        entity_count = 0
        for ent, sess_pid, msg_pid in ent_rows:
            entity_count += 1
            if msg_pid:
                entities_by_message.setdefault(msg_pid, []).append(
                    _entity_out_from_row(svc, ent, sess_pid, msg_pid)
                )

        messages = [
            _message_out_from_row(svc, r, row.public_id, entities_by_message) for r in msg_rows
        ]
        escalations, scam_signals = _extract_annotations(svc, msg_rows)
        classification = await self._latest_classification(row.id, scam_signals)
        custody = _build_custody(svc, row.public_id, msg_rows)
        syndicate_id = await self._syndicate_id_for_session(row.id)

        snapshot = row.persona_snapshot or {}
        persona = svc.PersonaOut(
            id=snapshot.get("id", ""), name=snapshot.get("name", ""),
            age=snapshot.get("age", 0), occupation=snapshot.get("occupation", ""),
            region=snapshot.get("region", ""),
        )

        return svc.SessionOut(
            id=row.public_id,
            case_id=str(row.case_id) if row.case_id else None,
            persona=persona,
            channel_type=row.channel_type,
            channel=row.channel or "",
            channel_ref=row.channel_ref or "",
            status=row.status,
            crime_type=row.crime_type,
            classification=classification,
            data_mode=row.data_mode,
            started_at=row.started_at,
            ended_at=row.ended_at,
            message_count=len(messages),
            entity_count=entity_count,
            escalations=escalations,
            scam_signals=scam_signals,
            custody=custody,
            syndicate_id=syndicate_id,
        )

    async def _latest_classification(
        self, session_uuid: uuid.UUID, scam_signals: list,
    ) -> "ClassificationOut | None":
        row = (
            await self._session.execute(
                select(CrimeClassification)
                .where(CrimeClassification.session_id == session_uuid)
                .order_by(CrimeClassification.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        svc = _out_models()
        return svc.ClassificationOut(
            crime_type=row.crime_type,
            confidence=float(row.confidence) if row.confidence is not None else 0.0,
            model_version=row.model_version or "",
            signals=[s.signal for s in scam_signals],  # see module docstring — not stored
        )

    async def _syndicate_id_for_session(self, session_uuid: uuid.UUID) -> str | None:
        stmt = (
            select(Syndicate.public_id)
            .select_from(Syndicate)
            .join(SyndicateMember, SyndicateMember.syndicate_id == Syndicate.id)
            .join(Entity, Entity.id == SyndicateMember.entity_id)
            .where(Entity.session_id == session_uuid)
            .limit(1)
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    # -- messages (keyed by session_id) -------------------------------------- #

    async def save_messages(self, session_id: str, messages: list["MessageOut"]) -> None:
        await self._insert_messages(session_id, messages)

    async def append_messages(self, session_id: str, messages: list["MessageOut"]) -> None:
        await self._insert_messages(session_id, messages)

    async def _insert_messages(self, session_id: str, messages: list["MessageOut"]) -> None:
        if not messages:
            return
        session_uuid = await self._get_session_uuid(session_id)
        if session_uuid is None:
            raise ValueError(f"cannot save messages for unknown session {session_id!r}")
        for m in messages:
            patch = self._pending_message_meta.pop(m.id, None)
            meta = {**m.meta, **patch} if patch else dict(m.meta)
            values = dict(
                session_id=session_uuid,
                agency_id=self._agency_id,
                seq=m.seq,
                direction=m.direction,
                content=m.content,
                ts=m.ts,
                sha256=bytes.fromhex(m.sha256),
                prev_sha256=bytes.fromhex(m.prev_sha256),
                meta=meta,
                data_mode=self._data_mode,
            )
            stmt = pg_insert(Message).values(id=uuid.uuid4(), public_id=m.id, **values)
            stmt = stmt.on_conflict_do_update(index_elements=[Message.public_id], set_=values)
            await self._session.execute(stmt)
            message_uuid = await self._get_message_uuid(m.id)
            await self._resolve_pending_entity_links("message_id", m.id, message_uuid)

    async def get_messages(self, session_id: str) -> list["MessageOut"] | None:
        session_uuid = await self._get_session_uuid(session_id)
        if session_uuid is None:
            return None
        rows = (
            await self._session.execute(
                select(Message).where(Message.session_id == session_uuid).order_by(Message.seq)
            )
        ).scalars().all()

        ent_stmt = (
            select(Entity, ScamSession.public_id, Message.public_id)
            .select_from(Entity)
            .outerjoin(ScamSession, Entity.session_id == ScamSession.id)
            .outerjoin(Message, Entity.message_id == Message.id)
            .where(Entity.session_id == session_uuid, Entity.agency_id == self._agency_id)
        )
        svc = _out_models()
        entities_by_message: dict[str, list] = {}
        for ent, sess_pid, msg_pid in (await self._session.execute(ent_stmt)).all():
            if msg_pid:
                entities_by_message.setdefault(msg_pid, []).append(
                    _entity_out_from_row(svc, ent, sess_pid, msg_pid)
                )

        return [_message_out_from_row(svc, r, session_id, entities_by_message) for r in rows]

    # -- entities ------------------------------------------------------------- #

    async def save_entity(self, entity: "EntityOut") -> None:
        session_uuid = await self._get_session_uuid(entity.session_id) if entity.session_id else None
        message_uuid = await self._get_message_uuid(entity.message_id) if entity.message_id else None
        provenance = dict(entity.provenance)
        if entity.context:
            provenance["__context"] = entity.context
        values = dict(
            session_id=session_uuid,
            message_id=message_uuid,
            agency_id=self._agency_id,
            type=entity.type,
            value=entity.value,
            normalized_value=entity.normalized_value,
            chain=entity.chain,
            bank_name=entity.bank_name,
            method=entity.method,
            confidence=entity.confidence,
            review_status=entity.review_status,
            provenance=provenance,
            data_mode=self._data_mode,
            created_at=entity.created_at,
        )
        stmt = pg_insert(Entity).values(id=uuid.uuid4(), public_id=entity.id, **values)
        stmt = stmt.on_conflict_do_update(index_elements=[Entity.public_id], set_=values)
        await self._session.execute(stmt)

        # service.py's real write order saves every entity BEFORE its session
        # (and often before its message) exists — _build_session assembles
        # entities inside the per-turn loop, then saves the session/messages
        # only after the loop finishes. Remember what didn't resolve so
        # save_session()/_insert_messages() can backfill it once those rows
        # actually land (see _resolve_pending_entity_links).
        pending: dict[str, str] = {}
        if entity.session_id and session_uuid is None:
            pending["session_id"] = entity.session_id
        if entity.message_id and message_uuid is None:
            pending["message_id"] = entity.message_id
        if pending:
            self._pending_entity_links[entity.id] = pending

    async def get_entity(self, entity_id: str) -> "EntityOut | None":
        stmt = (
            select(Entity, ScamSession.public_id, Message.public_id)
            .select_from(Entity)
            .outerjoin(ScamSession, Entity.session_id == ScamSession.id)
            .outerjoin(Message, Entity.message_id == Message.id)
            .where(Entity.public_id == entity_id, Entity.agency_id == self._agency_id)
        )
        row = (await self._session.execute(stmt)).first()
        if row is None:
            return None
        ent, sess_pid, msg_pid = row
        return _entity_out_from_row(_out_models(), ent, sess_pid, msg_pid)

    async def list_entities(
        self, session_id: str | None = None, status: str | None = None
    ) -> list["EntityOut"]:
        stmt = (
            select(Entity, ScamSession.public_id, Message.public_id)
            .select_from(Entity)
            .outerjoin(ScamSession, Entity.session_id == ScamSession.id)
            .outerjoin(Message, Entity.message_id == Message.id)
            .where(Entity.agency_id == self._agency_id)
        )
        if session_id is not None:
            stmt = stmt.where(ScamSession.public_id == session_id)
        if status is not None:
            stmt = stmt.where(Entity.review_status == status)
        svc = _out_models()
        rows = (await self._session.execute(stmt)).all()
        return [_entity_out_from_row(svc, ent, sess_pid, msg_pid) for ent, sess_pid, msg_pid in rows]

    # -- syndicates ------------------------------------------------------------ #

    async def save_syndicate(self, syndicate: "SyndicateOut") -> None:
        values = dict(
            agency_id=self._agency_id,
            label=syndicate.label,
            notes=syndicate.notes,
            linguistic_fingerprint=syndicate.linguistic_fingerprint,
            data_mode=self._data_mode,
            created_at=syndicate.created_at,
        )
        stmt = pg_insert(Syndicate).values(id=uuid.uuid4(), public_id=syndicate.id, **values)
        stmt = stmt.on_conflict_do_update(index_elements=[Syndicate.public_id], set_=values)
        await self._session.execute(stmt)

        syndicate_uuid = (
            await self._session.execute(
                select(Syndicate.id).where(Syndicate.public_id == syndicate.id)
            )
        ).scalar_one()

        for member in syndicate.members:
            entity_uuid = await self._get_entity_uuid(member.entity_id)
            if entity_uuid is None:
                continue  # entity is always saved before its syndicate in practice
            m_values = dict(link_type=member.link_type, confidence=member.confidence)
            m_stmt = pg_insert(SyndicateMember).values(
                syndicate_id=syndicate_uuid, entity_id=entity_uuid, **m_values
            )
            m_stmt = m_stmt.on_conflict_do_update(
                index_elements=[SyndicateMember.syndicate_id, SyndicateMember.entity_id],
                set_=m_values,
            )
            await self._session.execute(m_stmt)

    async def list_syndicates(self) -> list["SyndicateOut"]:
        rows = (
            await self._session.execute(
                select(Syndicate)
                .where(Syndicate.agency_id == self._agency_id)
                .order_by(Syndicate.created_at)
            )
        ).scalars().all()
        return [await self._syndicate_out_from_row(row) for row in rows]

    async def _syndicate_out_from_row(self, row: Syndicate) -> "SyndicateOut":
        svc = _out_models()
        stmt = (
            select(SyndicateMember, Entity, ScamSession.public_id)
            .select_from(SyndicateMember)
            .join(Entity, Entity.id == SyndicateMember.entity_id)
            .outerjoin(ScamSession, Entity.session_id == ScamSession.id)
            .where(SyndicateMember.syndicate_id == row.id)
        )
        rows = (await self._session.execute(stmt)).all()
        members = [
            svc.SyndicateMemberOut(
                entity_id=ent.public_id, type=ent.type, value=ent.normalized_value or "",
                link_type=mem.link_type or "",
                confidence=float(mem.confidence) if mem.confidence is not None else 0.0,
            )
            for mem, ent, _sess_pid in rows
        ]
        session_ids = sorted({sess_pid for _mem, _ent, sess_pid in rows if sess_pid})
        return svc.SyndicateOut(
            id=row.public_id, label=row.label, notes=row.notes or "",
            linguistic_fingerprint=row.linguistic_fingerprint or {},
            session_ids=session_ids, entity_count=len(members), members=members,
            data_mode=row.data_mode, created_at=row.created_at,
        )

    # -- test/seed hook ---------------------------------------------------------- #

    def reset(self) -> None:
        raise NotImplementedError(
            "reset() is a memory-only test hook — see service.reset_stores(), "
            "which never routes through this class."
        )


async def get_infiltrate_repository(
    session: AsyncSession | None = Depends(get_optional_tenant_session),
    auth: AuthContext | None = Depends(_get_optional_current_user),
) -> InfiltrateRepository:
    """FastAPI dependency — selects the impl from ``settings.persistence``.

    "memory" (default) returns the process-wide in-memory singleton, exactly
    today's POC behavior — no DB, no auth required (matches the P-2b scope
    guard: today's unauthenticated read routes keep working). "postgres"
    builds a fresh ``PostgresInfiltrateRepository`` per request over the
    RLS-scoped session ``get_optional_tenant_session`` already opened (which
    itself 401s if postgres mode has no verified identity to scope to — by
    the time we get here with persistence=="postgres", ``session``/``auth``
    are guaranteed non-``None``)."""
    settings = get_settings()
    if settings.persistence != "postgres":
        return _memory_repository()
    if session is None or auth is None:  # pragma: no cover - get_optional_tenant_session already 401s
        raise RuntimeError("postgres persistence requires an authenticated, RLS-scoped session")
    return PostgresInfiltrateRepository(session, agency_id=auth.agency.id, data_mode=settings.mode)
