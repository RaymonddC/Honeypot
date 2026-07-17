"""User persistence boundary (P-4b, docs/Persistence-Plan.md P-4) — the login
paths' read/write surface over ``core.users``, mirroring the
``InfiltrateRepository``/``UncoverRepository`` memory+Postgres toggle.

**Why this can't reuse ``get_infiltrate_repository``'s shape:** that factory
selects its impl from an already-resolved (optional) ``AuthContext`` — but
login happens BEFORE there's one. The Postgres impl here is instead built over
``app.core.db.get_optional_session`` (a plain, unscoped session, persistence-
gated the same way) and calls the ``core.login_*`` ``SECURITY DEFINER``
functions (migration 20260717_09), which bypass RLS themselves — see that
migration's docstring for why a normal RLS-scoped session cannot do this
lookup at all.

The in-memory impl is a thin, behavior-preserving pass-through to the
existing module-level ``_USERS`` dict + its sync helper functions in
``app.core.auth`` (``find_user_by_email``/``register_user``) — those stay
exactly as they are today (still called directly and synchronously by
``tests/conftest.py``'s ``bearer()`` and ``tests/test_auth_api.py``), so
"memory" persistence is unchanged, no DB, by construction.
"""

import uuid
from functools import lru_cache
from typing import Protocol, runtime_checkable

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import SeedAgency, SeedUser, _user_id
from app.core.auth import find_user_by_email as _mem_find_by_email
from app.core.auth import register_user as _mem_register_user
from app.core.config import get_settings
from app.core.db import get_optional_session


@runtime_checkable
class UserRepository(Protocol):
    """Storage surface the auth router's login paths need. Both impls return
    the same ``SeedUser`` dataclass ``app/core/auth.py`` already defines —
    the login endpoints' contract doesn't change, only where the row lives."""

    async def find_by_email(self, email: str) -> SeedUser | None: ...

    async def find_by_agency_role(self, agency_id: uuid.UUID, role: str) -> SeedUser | None: ...

    async def upsert(self, user: SeedUser) -> SeedUser: ...


class InMemoryUserRepository:
    """POC impl — delegates to the existing module-level ``_USERS`` dict via
    ``app.core.auth``'s own helpers. No new state, no behavior change."""

    async def find_by_email(self, email: str) -> SeedUser | None:
        return _mem_find_by_email(email)

    async def find_by_agency_role(self, agency_id: uuid.UUID, role: str) -> SeedUser | None:
        from app.core.auth import _USERS

        return next(
            (u for u in _USERS.values() if u.agency_id == agency_id and u.role == role), None
        )

    async def upsert(self, user: SeedUser) -> SeedUser:
        return _mem_register_user(user)


@lru_cache
def _memory_repository() -> InMemoryUserRepository:
    return InMemoryUserRepository()


def _row_to_seed_user(row) -> SeedUser:
    return SeedUser(
        id=row.id, agency_id=row.agency_id, email=row.email,
        name=row.name or "", role=row.role,
    )


class PostgresUserRepository:
    """Postgres impl (P-4b) — every method calls one of the three
    ``core.login_*`` ``SECURITY DEFINER`` functions (migration 20260717_09)
    over an unscoped session (``app.core.db.get_optional_session``). No
    ``app.current_agency/user/role`` vars are set — these functions bypass
    RLS themselves by design (see the migration docstring); that's the whole
    point of the login boundary."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_email(self, email: str) -> SeedUser | None:
        row = (
            await self._session.execute(
                text("SELECT * FROM core.login_find_user_by_email(:email)"),
                {"email": email},
            )
        ).first()
        return _row_to_seed_user(row) if row is not None else None

    async def find_by_agency_role(self, agency_id: uuid.UUID, role: str) -> SeedUser | None:
        row = (
            await self._session.execute(
                text("SELECT * FROM core.login_find_user_by_agency_role(:agency_id, :role)"),
                {"agency_id": agency_id, "role": role},
            )
        ).first()
        return _row_to_seed_user(row) if row is not None else None

    async def upsert(self, user: SeedUser) -> SeedUser:
        row = (
            await self._session.execute(
                text(
                    "SELECT * FROM core.login_upsert_user("
                    ":id, :agency_id, :email, :name, :role, :oauth_sub)"
                ),
                {
                    "id": user.id,
                    "agency_id": user.agency_id,
                    "email": user.email,
                    "name": user.name,
                    "role": user.role,
                    "oauth_sub": None,
                },
            )
        ).first()
        return _row_to_seed_user(row)


async def get_user_repository(
    session: AsyncSession | None = Depends(get_optional_session),
) -> UserRepository:
    """FastAPI dependency — selects the impl from ``settings.persistence``,
    exactly like ``get_infiltrate_repository``. "memory" (default) returns the
    process-wide in-memory singleton, no DB. "postgres" builds a
    ``PostgresUserRepository`` over the unscoped session
    ``get_optional_session`` already opened."""
    settings = get_settings()
    if settings.persistence != "postgres":
        return _memory_repository()
    if session is None:  # pragma: no cover - get_optional_session yields non-None under postgres
        raise RuntimeError("postgres persistence requires a database session")
    return PostgresUserRepository(session)


async def resolve_demo_user(
    repo: UserRepository, agency: SeedAgency, role: str
) -> SeedUser:
    """Shared orchestration for the POC demo login path — same logic
    ``app.core.auth.upsert_demo_user`` runs against ``_USERS`` directly, but
    routed through ``UserRepository`` so it works identically over either
    backend: find an existing user for (agency, role) first (resolves to the
    canonical seeded person, e.g. Budi, rather than a synthesized duplicate),
    only minting+inserting a new one on a miss."""
    existing = await repo.find_by_agency_role(agency.id, role)
    if existing is not None:
        return existing
    email = f"{role}@{agency.slug}.demo.ittu.id"
    user = SeedUser(_user_id(email), agency.id, email, f"{agency.name} {role}", role)
    return await repo.upsert(user)
