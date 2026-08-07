"""UNCOVER persistence boundary (docs/Persistence-Plan.md P-3).

Repository interface behind the two in-memory stores
(``_ACTIONS: dict[str, ActionBundle]``, ``_DOCUMENTS: dict[str,
docs.GeneratedDocument]``) that ``uncover/service.py`` used to own as bare
module-level dicts. An in-memory impl backs the POC + the existing fast test
suite; a Postgres impl backs ``settings.persistence == "postgres"``.

Persistence is selected by ``settings.persistence`` — a separate axis from the
poc/live MODE registry (``app.core.adapters``), same as
``app.infiltrate.repository`` (P-2). This factory intentionally does NOT go
through ``app.core.adapters.register`` / ``get_adapter``.

**Schema note (bigger than P-2's):** unlike ``intel.scam_sessions``, no table
held the ``ActionBundle`` aggregate itself before migration ``20260717_08`` —
``action.action_documents``/``action.notifications`` only ever held
per-document/per-dispatch rows, with no envelope (status/outputs/routing
plan/totals) and no real grouping key (``case_id`` isn't unique). Confirmed
with the P-3 lead before writing this: give the aggregate a real table
(``action.action_bundles``) rather than smuggling its fields into a sibling
row. See that migration's docstring for the full reasoning, including why
``action_documents.pdf`` stores the rendered bytes directly (no object store
exists yet, and evidence must be stored, never re-derived) and the extra
scalar columns (``title``/``filename``/``template_version`` on documents,
``target_agency``/``agency_type`` on notifications) that mapping
``DocumentOut``/``NotificationOut`` onto the schema turned up.

Id mapping mirrors migration 07: every app-level id (``bundle.id``/
``document.id``/``notification.id``, e.g. "act_xxxx") lives in that table's
``public_id`` column; the ``id uuid`` PK is a surrogate for FK plumbing only,
never returned to a caller.

Fields with no column of their own:
  - ``GeneratedDocument.meta``   -> not stored. Write-time-only scratch data:
    ``goaml_draft`` is read out of it once, immediately, at generate time
    (``service.generate_bundle``), and never read again on any later fetch.
  - ``DocumentOut.size_bytes``   -> derived as ``len(pdf)`` on read (matches
    the dataclass's own ``size_bytes`` property — never stored redundantly).
  - ``ActionBundle.audit``       -> never stored here. It's the existing
    in-memory, hash-chained ``uncover.custody.audit_log`` (POC accumulator,
    explicitly out of scope for P-3 — left alone). The repository always
    returns an empty ``audit`` list; ``service.get_bundle`` fills it in from
    the audit log, exactly as it does today for the in-memory store.
  - ``NotificationOut.action_id``/``case_id`` -> derived via the
    ``bundle_id`` FK join back to the owning ``action_bundles`` row
    (``public_id``/``case_id``) rather than duplicated onto every
    notification row.
"""

import uuid
from functools import lru_cache
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from fastapi import Depends
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.action.models import ActionBundle as ActionBundleModel
from app.action.models import ActionDocument as ActionDocumentModel
from app.action.models import Notification as NotificationModel
from app.core.auth import AuthContext
from app.core.auth import get_optional_current_user as _get_optional_current_user
from app.core.config import get_settings
from app.core.db import get_optional_tenant_session
from app.uncover import documents as docs
from app.uncover.notifications import NotificationOut, RoutingTarget

if TYPE_CHECKING:
    from app.uncover.service import ActionBundle, DocumentOut


def _out_models():
    """Deferred import of the Pydantic response models — ``service.py``
    imports THIS module at load time, so importing its models back at module
    scope here would be a circular import (same pattern as
    ``app.infiltrate.repository._out_models``)."""
    from app.uncover import service as _service

    return _service


@runtime_checkable
class UncoverRepository(Protocol):
    """Storage surface ``uncover/service.py`` needs — derived from the actual
    read/write call sites of the 2 stores it used to own directly. Returns/
    accepts the SAME Pydantic models the service already builds
    (``ActionBundle``/``docs.GeneratedDocument``); the contract at the
    service boundary does not change.

    Every read/write method is ``async`` (P-2/P-2b precedent): the Postgres
    impl does real I/O over an ``AsyncSession``, and a Protocol can't have one
    impl awaiting and another not. ``reset()`` stays sync — a memory-only test
    hook, never routed through this Protocol (see ``service.reset_stores``).
    """

    # -- bundles -------------------------------------------------------------- #
    async def save_bundle(self, bundle: "ActionBundle") -> None:
        """Upsert the bundle envelope. Also persists any embedded
        ``bundle.notifications`` (dispatch always populates that list before
        calling this — see ``service.dispatch_bundle``); the in-memory impl
        needs no extra step since they're already part of the same object,
        the Postgres impl upserts each into its own ``notifications`` row."""
        ...

    async def get_bundle(self, action_id: str) -> "ActionBundle | None": ...

    async def list_bundles(self) -> list["ActionBundle"]: ...

    # -- documents (keyed by their own id, grouped under a bundle) ------------ #
    async def save_document(self, action_id: str, document: docs.GeneratedDocument) -> None:
        """Insert a newly generated document (incl. PDF bytes) under its bundle."""
        ...

    async def get_document(self, document_id: str) -> docs.GeneratedDocument | None: ...

    async def update_document_status(self, document_id: str, status: str) -> None:
        """Draft -> issued (dispatch) status transition only — a small
        targeted update so callers never have to re-supply PDF bytes just to
        flip a status flag."""
        ...

    # -- notifications (the dispatch outbox / feed, C1) ----------------------- #
    async def list_notifications(self) -> list["NotificationOut"]:
        """Every dispatch record the caller may see (RLS-scoped under
        Postgres), newest first — the Dispatch Log feed reads this."""
        ...

    async def get_notification(self, notification_id: str) -> "NotificationOut | None":
        """One notification by its ``ntf_…`` public id (for retry)."""
        ...

    async def update_notification(self, note: "NotificationOut") -> None:
        """Persist a single notification's delivery-lifecycle fields
        (status/attempt_count/last_error/sent_at) after a (re)dispatch —
        without rewriting the whole owning bundle."""
        ...

    # -- test/seed hook --------------------------------------------------------- #
    def reset(self) -> None:
        """Clear all stored state — existing test hook (``service.reset_stores``).
        Sync, memory-only (see class docstring)."""
        ...


class InMemoryUncoverRepository:
    """POC impl — the 2 module-level dicts that used to live in service.py,
    unchanged in behavior, moved behind ``UncoverRepository``.

    Methods are ``async`` to satisfy the Protocol — trivial coroutines around
    the same synchronous dict ops, no actual I/O, no behavior change."""

    def __init__(self) -> None:
        self._bundles: dict[str, "ActionBundle"] = {}
        self._documents: dict[str, docs.GeneratedDocument] = {}

    async def save_bundle(self, bundle: "ActionBundle") -> None:
        self._bundles[bundle.id] = bundle

    async def get_bundle(self, action_id: str) -> "ActionBundle | None":
        return self._bundles.get(action_id)

    async def list_bundles(self) -> list["ActionBundle"]:
        return list(self._bundles.values())

    async def save_document(self, action_id: str, document: docs.GeneratedDocument) -> None:
        self._documents[document.id] = document

    async def get_document(self, document_id: str) -> docs.GeneratedDocument | None:
        return self._documents.get(document_id)

    async def update_document_status(self, document_id: str, status: str) -> None:
        if document_id in self._documents:
            self._documents[document_id].status = status

    # -- notifications (embedded in their bundle in memory) ------------------- #
    async def list_notifications(self) -> list[NotificationOut]:
        # Flatten every bundle's notifications; newest bundles last → reverse
        # so the freshest dispatch is first, matching the Postgres ordering.
        notes: list[NotificationOut] = []
        for bundle in self._bundles.values():
            notes.extend(bundle.notifications)
        return list(reversed(notes))

    async def get_notification(self, notification_id: str) -> NotificationOut | None:
        for bundle in self._bundles.values():
            for n in bundle.notifications:
                if n.id == notification_id:
                    return n
        return None

    async def update_notification(self, note: NotificationOut) -> None:
        for bundle in self._bundles.values():
            for i, n in enumerate(bundle.notifications):
                if n.id == note.id:
                    bundle.notifications[i] = note
                    return

    def reset(self) -> None:
        self._bundles.clear()
        self._documents.clear()


@lru_cache
def _memory_repository() -> InMemoryUncoverRepository:
    """Process-wide singleton (mirrors ``get_settings()``'s caching) so the
    repo behaves exactly like the module dicts it replaces."""
    return InMemoryUncoverRepository()


# --------------------------------------------------------------------------- #
# Postgres impl (P-3) — action.action_bundles/action_documents/notifications,
# RLS-scoped by an already-open AsyncSession (see
# app.core.db.get_optional_tenant_session). See the module docstring +
# migration 20260717_08 for the schema reasoning.
# --------------------------------------------------------------------------- #


def _notification_out_from_row(
    n: NotificationModel, *, action_id: str, case_id: str | None
) -> NotificationOut:
    """Map a persisted notification row → the API model. ``action_id``/
    ``case_id`` come from the owning bundle (the FK join) rather than being
    duplicated on the row — see the module docstring."""
    return NotificationOut(
        id=n.public_id,
        action_id=action_id,
        case_id=case_id or "",
        target_agency=n.target_agency,
        agency_type=n.agency_type,
        channel=n.channel or "",
        status=n.status,
        data_mode=n.data_mode,
        sent_at=n.sent_at,
        payload=n.payload or {},
        idempotency_key=n.idempotency_key,
        attempt_count=n.attempt_count or 0,
        last_error=n.last_error,
    )


def _document_out_from_row(svc, row: ActionDocumentModel) -> "DocumentOut":
    return svc.DocumentOut(
        id=row.public_id,
        type=row.type,
        format=row.format or "",
        title=row.title,
        filename=row.filename,
        sha256=row.sha256.hex() if row.sha256 else "",
        size_bytes=len(row.pdf) if row.pdf else 0,  # derived — see module docstring
        status=row.status,
        template_version=row.template_version,
        generated_at=row.generated_at,
        data_mode=row.data_mode,
        download_url=f"/api/documents/{row.public_id}",
    )


class PostgresUncoverRepository:
    """Postgres impl (P-3) — see the module-level notes above for the id and
    field mapping. Constructed PER REQUEST with an already RLS-scoped
    ``AsyncSession`` (``app.current_agency/user/role`` set by the caller)
    plus the ``agency_id``/``data_mode`` to stamp on every write. RLS filters
    reads by agency already; every query below ALSO filters by ``agency_id``
    explicitly — defense in depth, same as ``PostgresInfiltrateRepository``."""

    def __init__(self, session: AsyncSession, *, agency_id: uuid.UUID, data_mode: str) -> None:
        self._session = session
        self._agency_id = agency_id
        self._data_mode = data_mode

    async def _get_bundle_uuid(self, public_id: str) -> uuid.UUID | None:
        return (
            await self._session.execute(
                select(ActionBundleModel.id).where(ActionBundleModel.public_id == public_id)
            )
        ).scalar_one_or_none()

    # -- bundles -------------------------------------------------------------- #

    async def save_bundle(self, bundle: "ActionBundle") -> None:
        values = dict(
            public_id=bundle.id,
            case_id=bundle.case_id,
            agency_id=self._agency_id,
            status=bundle.status,
            crime_type=bundle.crime_type,
            outputs=list(bundle.outputs),
            selected_entities=[e.model_dump(mode="json") for e in bundle.entities],
            goaml_draft=bundle.goaml_draft,
            routing_plan=[t.model_dump(mode="json") for t in bundle.routing_plan],
            totals=bundle.totals.model_dump(mode="json"),
            data_mode=self._data_mode,
            created_at=bundle.created_at,
            dispatched_at=bundle.dispatched_at,
        )
        stmt = pg_insert(ActionBundleModel).values(id=uuid.uuid4(), **values)
        stmt = stmt.on_conflict_do_update(index_elements=[ActionBundleModel.public_id], set_=values)
        await self._session.execute(stmt)

        bundle_uuid = await self._get_bundle_uuid(bundle.id)
        for n in bundle.notifications:
            n_values = dict(
                bundle_id=bundle_uuid,
                agency_id=self._agency_id,
                target_agency=n.target_agency,
                agency_type=n.agency_type,
                channel=n.channel,
                payload=n.payload,
                status=n.status,
                data_mode=self._data_mode,
                sent_at=n.sent_at,
                idempotency_key=n.idempotency_key,
                attempt_count=n.attempt_count,
                last_error=n.last_error,
            )
            n_stmt = pg_insert(NotificationModel).values(id=uuid.uuid4(), public_id=n.id, **n_values)
            n_stmt = n_stmt.on_conflict_do_update(
                index_elements=[NotificationModel.public_id], set_=n_values
            )
            await self._session.execute(n_stmt)

    async def get_bundle(self, action_id: str) -> "ActionBundle | None":
        row = (
            await self._session.execute(
                select(ActionBundleModel).where(
                    ActionBundleModel.public_id == action_id,
                    ActionBundleModel.agency_id == self._agency_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        return await self._bundle_out_from_row(row)

    async def list_bundles(self) -> list["ActionBundle"]:
        rows = (
            await self._session.execute(
                select(ActionBundleModel)
                .where(ActionBundleModel.agency_id == self._agency_id)
                .order_by(ActionBundleModel.created_at)
            )
        ).scalars().all()
        return [await self._bundle_out_from_row(row) for row in rows]

    async def _bundle_out_from_row(self, row: ActionBundleModel) -> "ActionBundle":
        svc = _out_models()

        doc_rows = (
            await self._session.execute(
                select(ActionDocumentModel)
                .where(ActionDocumentModel.bundle_id == row.id)
                .order_by(ActionDocumentModel.generated_at)
            )
        ).scalars().all()
        documents = [_document_out_from_row(svc, d) for d in doc_rows]

        ntf_rows = (
            await self._session.execute(
                select(NotificationModel)
                .where(NotificationModel.bundle_id == row.id)
                .order_by(NotificationModel.created_at)
            )
        ).scalars().all()
        notifications = [
            _notification_out_from_row(n, action_id=row.public_id, case_id=row.case_id)
            for n in ntf_rows
        ]

        return svc.ActionBundle(
            id=row.public_id,
            case_id=row.case_id,
            status=row.status,
            data_mode=row.data_mode,
            crime_type=row.crime_type,
            outputs=list(row.outputs or []),
            entities=[svc.ActionEntityIn(**e) for e in (row.selected_entities or [])],
            documents=documents,
            goaml_draft=row.goaml_draft,
            routing_plan=[RoutingTarget(**t) for t in (row.routing_plan or [])],
            notifications=notifications,
            totals=svc.BundleTotals(**(row.totals or {})),
            created_at=row.created_at,
            dispatched_at=row.dispatched_at,
            audit=[],  # derived by the caller from the in-memory audit_log — see module docstring
        )

    # -- documents -------------------------------------------------------------- #

    async def save_document(self, action_id: str, document: docs.GeneratedDocument) -> None:
        bundle_uuid = await self._get_bundle_uuid(action_id)
        if bundle_uuid is None:
            raise ValueError(f"cannot save document for unknown bundle {action_id!r}")
        values = dict(
            bundle_id=bundle_uuid,
            agency_id=self._agency_id,
            type=document.type,
            format=document.format,
            title=document.title,
            filename=document.filename,
            template_version=document.template_version,
            pdf=document.pdf,
            status=document.status,
            generated_at=document.generated_at,
            sha256=bytes.fromhex(document.sha256),
            data_mode=self._data_mode,
        )
        stmt = pg_insert(ActionDocumentModel).values(id=uuid.uuid4(), public_id=document.id, **values)
        stmt = stmt.on_conflict_do_update(
            index_elements=[ActionDocumentModel.public_id], set_=values
        )
        await self._session.execute(stmt)

    async def get_document(self, document_id: str) -> docs.GeneratedDocument | None:
        row = (
            await self._session.execute(
                select(ActionDocumentModel).where(
                    ActionDocumentModel.public_id == document_id,
                    ActionDocumentModel.agency_id == self._agency_id,
                )
            )
        ).scalar_one_or_none()
        if row is None or row.pdf is None:
            return None
        return docs.GeneratedDocument(
            id=row.public_id,
            type=row.type,
            format=row.format or "",
            title=row.title,
            filename=row.filename,
            pdf=row.pdf,
            sha256=row.sha256.hex() if row.sha256 else "",
            generated_at=row.generated_at,
            template_version=row.template_version,
            status=row.status,
            data_mode=row.data_mode,
            meta={},  # write-time-only scratch data — see module docstring
        )

    async def update_document_status(self, document_id: str, status: str) -> None:
        await self._session.execute(
            text(
                "UPDATE action.action_documents SET status = :status "
                "WHERE public_id = :pid AND agency_id = :aid"
            ),
            {"status": status, "pid": document_id, "aid": self._agency_id},
        )

    # -- notifications (join back to the owning bundle for action_id/case_id) - #

    def _notifications_select(self):
        # NotificationModel + the owning bundle's public_id/case_id, agency-scoped.
        return (
            select(
                NotificationModel,
                ActionBundleModel.public_id,
                ActionBundleModel.case_id,
            )
            .join(ActionBundleModel, NotificationModel.bundle_id == ActionBundleModel.id)
            .where(NotificationModel.agency_id == self._agency_id)
        )

    async def list_notifications(self) -> list[NotificationOut]:
        rows = (
            await self._session.execute(
                self._notifications_select().order_by(NotificationModel.created_at.desc())
            )
        ).all()
        return [
            _notification_out_from_row(n, action_id=pid, case_id=cid)
            for (n, pid, cid) in rows
        ]

    async def get_notification(self, notification_id: str) -> NotificationOut | None:
        row = (
            await self._session.execute(
                self._notifications_select().where(
                    NotificationModel.public_id == notification_id
                )
            )
        ).one_or_none()
        if row is None:
            return None
        n, pid, cid = row
        return _notification_out_from_row(n, action_id=pid, case_id=cid)

    async def update_notification(self, note: NotificationOut) -> None:
        await self._session.execute(
            text(
                "UPDATE action.notifications SET status = :status, "
                "attempt_count = :attempts, last_error = :err, sent_at = :sent_at, "
                "updated_at = now() WHERE public_id = :pid AND agency_id = :aid"
            ),
            {
                "status": note.status,
                "attempts": note.attempt_count,
                "err": note.last_error,
                "sent_at": note.sent_at,
                "pid": note.id,
                "aid": self._agency_id,
            },
        )

    # -- test/seed hook ---------------------------------------------------------- #

    def reset(self) -> None:
        raise NotImplementedError(
            "reset() is a memory-only test hook — see service.reset_stores(), "
            "which never routes through this class."
        )


async def get_uncover_repository(
    session: AsyncSession | None = Depends(get_optional_tenant_session),
    auth: AuthContext | None = Depends(_get_optional_current_user),
) -> UncoverRepository:
    """FastAPI dependency — selects the impl from ``settings.persistence``.

    "memory" (default) returns the process-wide in-memory singleton, exactly
    today's POC behavior — no DB, no auth required. "postgres" builds a fresh
    ``PostgresUncoverRepository`` per request over the RLS-scoped session
    ``get_optional_tenant_session`` already opened (which itself 401s if
    postgres mode has no verified identity to scope to)."""
    settings = get_settings()
    if settings.persistence != "postgres":
        return _memory_repository()
    if session is None or auth is None:  # pragma: no cover - get_optional_tenant_session already 401s
        raise RuntimeError("postgres persistence requires an authenticated, RLS-scoped session")
    return PostgresUncoverRepository(session, agency_id=auth.agency.id, data_mode=settings.mode)
