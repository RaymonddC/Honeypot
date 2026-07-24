"""CASES persistence — memory (POC) + Postgres (RLS) dual over ``core.cases``,
selected by ``settings.persistence`` (same pattern as app/casedata)."""

import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol, runtime_checkable

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.cases.schemas import CaseOut, CreateCaseRequest, UpdateCaseRequest
from app.core.auth import AuthContext
from app.core.auth import get_optional_current_user as _get_optional_current_user
from app.core.config import get_settings
from app.core.db import get_optional_tenant_session
from app.core.models import Case


@runtime_checkable
class CaseRepository(Protocol):
    async def create_case(self, req: CreateCaseRequest) -> CaseOut: ...
    async def list_cases(self) -> list[CaseOut]: ...
    async def get_case(self, case_id: str) -> CaseOut | None: ...
    async def update_case(self, case_id: str, req: UpdateCaseRequest) -> CaseOut | None: ...

    def reset(self) -> None: ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# In-memory (POC)
# --------------------------------------------------------------------------- #


class InMemoryCaseRepository:
    def __init__(self) -> None:
        self._cases: dict[str, CaseOut] = {}

    async def create_case(self, req: CreateCaseRequest) -> CaseOut:
        cid = str(uuid.uuid4())
        now = _now()
        case = CaseOut(
            id=cid,
            title=req.title,
            status="open",
            stage=req.stage,
            crime_type=req.crime_type,
            summary=req.summary,
            data_mode=get_settings().mode,
            created_at=now,
            updated_at=now,
        )
        self._cases[cid] = case
        return case

    async def list_cases(self) -> list[CaseOut]:
        return sorted(self._cases.values(), key=lambda c: c.created_at, reverse=True)

    async def get_case(self, case_id: str) -> CaseOut | None:
        return self._cases.get(case_id)

    async def update_case(self, case_id: str, req: UpdateCaseRequest) -> CaseOut | None:
        case = self._cases.get(case_id)
        if case is None:
            return None
        data = case.model_dump()
        for field in ("title", "crime_type", "summary", "stage", "status"):
            val = getattr(req, field)
            if val is not None:
                data[field] = val
        data["updated_at"] = _now()
        updated = CaseOut(**data)
        self._cases[case_id] = updated
        return updated

    def reset(self) -> None:
        self._cases.clear()


@lru_cache
def _memory_repository() -> InMemoryCaseRepository:
    return InMemoryCaseRepository()


# --------------------------------------------------------------------------- #
# Postgres (RLS-scoped)
# --------------------------------------------------------------------------- #


def _case_out(row: Case) -> CaseOut:
    return CaseOut(
        id=str(row.id),
        title=row.title,
        status=row.status,  # type: ignore[arg-type]
        stage=row.stage,  # type: ignore[arg-type]
        crime_type=row.crime_type,
        summary=row.summary,
        data_mode=row.data_mode,  # type: ignore[arg-type]
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresCaseRepository:
    """RLS-scoped over ``core.cases`` (``app.current_agency`` set by the caller);
    every query also filters by ``agency_id`` explicitly (defense in depth)."""

    def __init__(
        self, session: AsyncSession, *, agency_id: uuid.UUID, user_id: uuid.UUID | None,
        data_mode: str,
    ) -> None:
        self._session = session
        self._agency_id = agency_id
        self._user_id = user_id
        self._data_mode = data_mode

    async def create_case(self, req: CreateCaseRequest) -> CaseOut:
        row = Case(
            id=uuid.uuid4(),
            agency_id=self._agency_id,
            title=req.title,
            status="open",
            stage=req.stage,
            crime_type=req.crime_type,
            summary=req.summary,
            data_mode=self._data_mode,
            created_by=self._user_id,
        )
        self._session.add(row)
        await self._session.flush()
        return _case_out(row)

    async def list_cases(self) -> list[CaseOut]:
        rows = (
            await self._session.execute(
                select(Case)
                .where(Case.agency_id == self._agency_id, Case.deleted_at.is_(None))
                .order_by(Case.created_at.desc())
            )
        ).scalars().all()
        return [_case_out(r) for r in rows]

    async def _row(self, case_id: str) -> Case | None:
        try:
            cid = uuid.UUID(case_id)
        except ValueError:
            return None
        return (
            await self._session.execute(
                select(Case).where(Case.id == cid, Case.agency_id == self._agency_id)
            )
        ).scalar_one_or_none()

    async def get_case(self, case_id: str) -> CaseOut | None:
        row = await self._row(case_id)
        return _case_out(row) if row else None

    async def update_case(self, case_id: str, req: UpdateCaseRequest) -> CaseOut | None:
        row = await self._row(case_id)
        if row is None:
            return None
        for field in ("title", "crime_type", "summary", "stage", "status"):
            val = getattr(req, field)
            if val is not None:
                setattr(row, field, val)
        row.updated_at = _now()
        await self._session.flush()
        return _case_out(row)

    def reset(self) -> None:
        raise NotImplementedError("reset() is a memory-only test hook.")


async def get_case_repository(
    session: AsyncSession | None = Depends(get_optional_tenant_session),
    auth: AuthContext | None = Depends(_get_optional_current_user),
) -> CaseRepository:
    """Memory singleton (POC) or per-request RLS Postgres repo (postgres mode)."""
    settings = get_settings()
    if settings.persistence != "postgres":
        return _memory_repository()
    if session is None or auth is None:  # pragma: no cover - tenant session 401s first
        raise RuntimeError("postgres persistence requires an authenticated, RLS-scoped session")
    return PostgresCaseRepository(
        session, agency_id=auth.agency.id, user_id=auth.user.id, data_mode=settings.mode
    )


def reset_stores() -> None:
    """Sync test hook — resets the in-memory singleton."""
    _memory_repository().reset()
