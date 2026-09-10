"""Triage persistence — connected calls that arrived without a case
(docs/Voice-Honeypot-Outbound.md §5, phase 6).

A call reaches triage when auto-linking found nothing: the campaign wasn't
pinned to a case, and the exact-match rules in ``dialer.resolve_case_id`` didn't
fire. Triage is where a human places it — attach to an existing case, or open a
new one.

Why this lives in its own module rather than in ``repository.py``: the rows are
``intel.scam_sessions``, not ``honeypot.*``. The endpoints belong under
``/api/honeypot`` (§6) because triage is part of the calling workflow, but the
storage surface is a different table family, so it gets its own Protocol.

Why not reuse ``InfiltrateRepository.save_session()`` to attach a case: that
method upserts the whole session AND unconditionally inserts a
``CrimeClassification`` row when the session carries one — attaching a case
would silently duplicate the classification every time. Attaching is one column
on one row, so it is written as exactly that.
"""

import uuid
from typing import Protocol, runtime_checkable

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.casedata.schemas import AddBankAccountRequest
from app.core.auth import AuthContext
from app.core.auth import get_optional_current_user as _get_optional_current_user
from app.core.config import get_settings
from app.core.db import get_optional_tenant_session
from app.honeypot_ops.schemas import TriageSessionOut

# How much of the scammer's opening line to show in the queue.
_PREVIEW_CHARS = 160


@runtime_checkable
class TriageRepository(Protocol):
    """Storage surface for the triage queue."""

    async def list_triage(self) -> list[TriageSessionOut]: ...
    async def get_triage(self, session_id: str) -> TriageSessionOut | None: ...
    async def attach(self, session_id: str, case_id: str) -> TriageSessionOut | None: ...


def _truncate(text: str | None) -> str | None:
    if not text:
        return None
    text = text.strip()
    return text if len(text) <= _PREVIEW_CHARS else text[: _PREVIEW_CHARS - 1] + "…"


# --------------------------------------------------------------------------- #
# In-memory (POC)
# --------------------------------------------------------------------------- #


class InMemoryTriageRepository:
    """POC impl — reads the sessions the INFILTRATE memory store already holds.

    Triage owns no storage of its own in either mode; here it is a view over
    ``InMemoryInfiltrateRepository``, so a session created by the honeypot
    console shows up in triage without any syncing between two stores.
    """

    def _repo(self):
        from app.infiltrate.repository import _memory_repository

        return _memory_repository()

    def _out(self, sess) -> TriageSessionOut:
        repo = self._repo()
        msgs = repo._messages.get(sess.id, [])
        first_inbound = next((m for m in msgs if m.direction == "inbound"), None)
        return TriageSessionOut(
            id=sess.id,
            channel=sess.channel,
            channel_ref=sess.channel_ref,
            crime_type=sess.crime_type,
            status=sess.status,
            # SessionOut predates the phase-1 call columns, so a memory-mode
            # session simply has no disposition/duration to report.
            disposition=getattr(sess, "disposition", None),
            duration_seconds=getattr(sess, "duration_seconds", None),
            entity_count=sess.entity_count,
            preview=_truncate(first_inbound.content if first_inbound else None),
            data_mode=sess.data_mode,  # type: ignore[arg-type]
            started_at=sess.started_at,
        )

    async def list_triage(self) -> list[TriageSessionOut]:
        sessions = await self._repo().list_sessions()
        rows = [
            s for s in sessions if s.case_id is None and s.channel_type == "voice"
        ]
        rows.sort(key=lambda s: s.started_at, reverse=True)
        return [self._out(s) for s in rows]

    async def get_triage(self, session_id: str) -> TriageSessionOut | None:
        sess = await self._repo().get_session(session_id)
        if sess is None or sess.channel_type != "voice":
            return None
        return self._out(sess)

    async def attach(self, session_id: str, case_id: str) -> TriageSessionOut | None:
        repo = self._repo()
        sess = await repo.get_session(session_id)
        if sess is None or sess.channel_type != "voice":
            return None
        await repo.save_session(sess.model_copy(update={"case_id": case_id}))
        return self._out(await repo.get_session(session_id))


# --------------------------------------------------------------------------- #
# Postgres (RLS-scoped)
# --------------------------------------------------------------------------- #


class PostgresTriageRepository:
    """RLS-scoped over ``intel.scam_sessions``; every query ALSO filters by
    ``agency_id`` explicitly (defense in depth), like the sibling repos."""

    def __init__(self, session: AsyncSession, *, agency_id: uuid.UUID) -> None:
        self._session = session
        self._agency_id = agency_id

    async def _out(self, row) -> TriageSessionOut:
        from app.intel.models import Entity, Message

        entity_count = (
            await self._session.execute(
                select(func.count())
                .select_from(Entity)
                .where(Entity.session_id == row.id)
            )
        ).scalar_one()
        preview = (
            await self._session.execute(
                select(Message.content)
                .where(Message.session_id == row.id, Message.direction == "inbound")
                .order_by(Message.seq)
                .limit(1)
            )
        ).scalar_one_or_none()
        return TriageSessionOut(
            id=row.public_id,
            channel=row.channel,
            channel_ref=row.channel_ref,
            crime_type=row.crime_type,
            status=row.status,
            disposition=row.disposition,
            duration_seconds=row.duration_seconds,
            entity_count=int(entity_count),
            preview=_truncate(preview),
            data_mode=row.data_mode,  # type: ignore[arg-type]
            started_at=row.started_at,
        )

    async def _row(self, session_id: str):
        from app.intel.models import ScamSession

        return (
            await self._session.execute(
                select(ScamSession).where(
                    ScamSession.public_id == session_id,
                    ScamSession.agency_id == self._agency_id,
                    ScamSession.channel_type == "voice",
                )
            )
        ).scalar_one_or_none()

    async def list_triage(self) -> list[TriageSessionOut]:
        from app.intel.models import ScamSession

        rows = (
            await self._session.execute(
                select(ScamSession)
                .where(
                    ScamSession.agency_id == self._agency_id,
                    ScamSession.case_id.is_(None),
                    ScamSession.channel_type == "voice",
                )
                .order_by(ScamSession.started_at.desc())
            )
        ).scalars().all()
        return [await self._out(r) for r in rows]

    async def get_triage(self, session_id: str) -> TriageSessionOut | None:
        row = await self._row(session_id)
        return await self._out(row) if row is not None else None

    async def attach(self, session_id: str, case_id: str) -> TriageSessionOut | None:
        row = await self._row(session_id)
        if row is None:
            return None
        try:
            row.case_id = uuid.UUID(case_id)
        except ValueError:
            return None
        await self._session.flush()
        return await self._out(row)


async def get_triage_repository(
    session: AsyncSession | None = Depends(get_optional_tenant_session),
    auth: AuthContext | None = Depends(_get_optional_current_user),
) -> TriageRepository:
    """FastAPI dependency — memory view (POC) or per-request RLS Postgres repo."""
    settings = get_settings()
    if settings.persistence != "postgres":
        return InMemoryTriageRepository()
    if session is None or auth is None:  # pragma: no cover - tenant session 401s first
        raise RuntimeError("postgres persistence requires an authenticated, RLS-scoped session")
    return PostgresTriageRepository(session, agency_id=auth.agency.id)


# --------------------------------------------------------------------------- #
# Carrying a call's findings onto the case it is placed into
# --------------------------------------------------------------------------- #


async def copy_entities_to_case(
    session_id: str,
    case_id: str,
    *,
    infiltrate_repo,
    casedata_repo,
) -> int:
    """Copy a call's extracted bank accounts onto the case, as tracked accounts.

    Placing a call used to set ``session.case_id`` and nothing else. The account
    a scammer read out on the line stayed on ``intel.entities``, attached to the
    SESSION — while every downstream module reads ``casedata.bank_accounts``:
    TRACE's mule watchlist, the case view, and the freeze request UNCOVER
    renders into a PDF. So a real call produced a real entity and an empty case,
    and the golden thread broke at exactly the seam between INFILTRATE and
    everything after it.

    ``review_status`` is carried into the note rather than dropped. Extractions
    arrive ``unverified`` — a mis-transcribed digit is one wrong account — and a
    case that cannot show which of its accounts a human has confirmed invites
    someone to freeze the wrong one. The officer sees the account immediately;
    the record never claims more certainty than it has.

    Category is ``mule``: an account a scammer gives out to receive a victim's
    transfer is a receiving account, which is what that literal means here and
    what the rest of the demo data already uses (see ONRAMP_CATEGORY).

    Crypto wallets are deliberately NOT copied. ``casedata`` stores transfers —
    ``from_addr → to_addr`` for a value at a time — and a disclosed address is a
    node, not an edge. Writing one would mean inventing a transaction that
    nobody observed, which is worse than leaving the wallet on the session where
    it honestly sits.

    Returns how many accounts were added. Idempotent: attaching the same call
    twice, or two calls that disclosed the same account, will not duplicate it.
    """
    entities = await infiltrate_repo.list_entities(session_id)
    if not entities:
        return 0

    existing = {
        a.account_number for a in await casedata_repo.list_bank_accounts(case_id)
    }
    added = 0
    for e in entities:
        if e.type != "bank_account":
            continue
        number = (e.normalized_value or e.value or "").strip()
        if not number or number in existing:
            continue
        note = (
            f"Disclosed on honeypot call {session_id}"
            f" · extraction {e.method} conf {e.confidence:.2f}"
            f" · review: {e.review_status}"
        )
        await casedata_repo.add_bank_account(
            AddBankAccountRequest(
                # "TBC" not "Unknown": the bank was never said on the call,
                # so this is a field still to be confirmed rather than a
                # fact nobody knows. An investigator reads the difference.
                bank_name=e.bank_name or "TBC",
                account_number=number,
                holder_name=None,
                category="mule",
                note=note[:500],
                case_id=case_id,
            )
        )
        existing.add(number)
        added += 1
    return added
