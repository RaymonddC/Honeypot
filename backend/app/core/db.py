"""Async SQLAlchemy engine, session factory, and declarative Base.

Engine creation is lazy (no connection until first use), so the API can boot
and serve /health without Postgres running.
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.auth import AuthContext
from app.core.auth import get_current_user as _get_current_user
from app.core.auth import get_optional_current_user as _get_optional_current_user
from app.core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base — Alembic autogenerate targets Base.metadata."""


engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield a request-scoped async session."""
    async with SessionLocal() as session:
        yield session


async def get_tenant_session(
    auth: AuthContext = Depends(_get_current_user),
) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: an RLS-scoped session for the authenticated tenant.

    Opens ONE transaction for the request and sets the per-transaction vars the
    core.* RLS policies read (``set_config(..., is_local=true)`` ≡ ``SET LOCAL``,
    parameterizable — see migration 20260708_05)::

        app.current_agency / app.current_user / app.current_role

    RLS only bites when the app connects as a NON-superuser, non-owner role —
    superusers/table owners bypass policies (deployment invariant,
    docs/Security-Evidence.md §2). Runtime verification needs a Postgres
    instance; POC module endpoints stay in-memory and don't use this yet.
    """
    async for session in _tenant_scoped_session(auth):
        yield session


async def _tenant_scoped_session(auth: AuthContext) -> AsyncGenerator[AsyncSession, None]:
    """Shared body: open one transaction, set the RLS vars, yield. Factored out
    of ``get_tenant_session`` so ``get_optional_tenant_session`` (below) can
    reuse it without going through FastAPI's ``Depends(get_current_user)`` —
    it resolves auth itself, conditionally, per the persistence toggle."""
    async with SessionLocal() as session, session.begin():
        for var, value in (
            ("app.current_agency", str(auth.agency.id)),
            ("app.current_user", str(auth.user.id)),
            ("app.current_role", auth.role),
            # POC/LIVE evidentiary isolation (migration 20260823_18). ONE value
            # for the whole transaction — which is why per-module modes are
            # refused under Postgres (see config.assert_modes_are_coherent):
            # a request spans modules, so there is no honest per-module value
            # to put here.
            ("app.data_mode", get_settings().mode),
        ):
            await session.execute(
                text("SELECT set_config(:var, :value, true)"),
                {"var": var, "value": value},
            )
        yield session


async def get_optional_session() -> AsyncGenerator[AsyncSession | None, None]:
    """FastAPI dependency: a PLAIN (non-RLS-scoped) session, but ONLY under
    Postgres — same persistence-first-check invariant as
    ``get_optional_tenant_session`` (under "memory" this yields ``None`` and
    never touches the engine).

    Unlike ``get_optional_tenant_session``, this does NOT require an
    authenticated identity: it exists for the login boundary (P-4b,
    docs/Persistence-Plan.md P-4), which by definition runs BEFORE there's a
    verified identity to scope a tenant session to. No ``app.current_agency/
    user/role`` vars are set on this session — callers must only use it to
    invoke the ``core.login_*`` ``SECURITY DEFINER`` functions (migration
    20260717_09), which read/write ``core.users`` bypassing RLS themselves,
    precisely so a normal RLS-scoped session (which login can't have yet
    anyway) is never needed here.
    """
    settings = get_settings()
    if settings.persistence != "postgres":
        yield None
        return
    async with SessionLocal() as session, session.begin():
        yield session


async def get_optional_tenant_session(
    auth: AuthContext | None = Depends(_get_optional_current_user),
) -> AsyncGenerator[AsyncSession | None, None]:
    """FastAPI dependency: an RLS-scoped session, but ONLY under Postgres.

    ``settings.persistence`` is checked FIRST, before anything DB-shaped runs —
    under "memory" (default) this yields ``None`` and never touches the engine,
    not even a connection attempt. That's the hard invariant: the POC must run
    with NO database. A repository factory keyed off this dependency can select
    the in-memory singleton without ever paying for (or requiring) a session.

    Under "postgres" it needs a verified identity to scope the session to —
    same 401 behavior as ``get_current_user`` (via ``get_optional_current_user``,
    which only makes "no token" soft; a bad/expired one still raises). Routes
    that don't carry auth today (P-2b scope guard — adding it is P-4) simply
    can't use the Postgres path yet; that's expected, not a bug here.
    """
    settings = get_settings()
    if settings.persistence != "postgres":
        yield None
        return
    if auth is None:
        await _get_current_user(None)  # raises the same 401 get_current_user would
        return  # pragma: no cover - unreachable, _get_current_user always raises
    async for session in _tenant_scoped_session(auth):
        yield session


# --------------------------------------------------------------------------- #
# Worker-side sessions (Dramatiq actors — OUTSIDE any request/RLS scope)
# --------------------------------------------------------------------------- #

# Test seam: when set to a sessionmaker, ``worker_session`` yields from it
# instead of building its own engine. Consulted at CALL time on purpose —
# actor modules do ``from app.core.db import worker_session``, so patching that
# name in this module would not reach the reference they already bound.
# Production leaves this None. See tests/test_honeypot_dialer_pg.py.
_worker_sessionmaker_override = None


@asynccontextmanager
async def worker_session() -> AsyncGenerator[AsyncSession, None]:
    """One DB session for a single background-actor invocation.

    Role: a Dramatiq actor runs with no request and no tenant context, so it
    connects with the privileged (owning) role via ``ITTU_MIGRATION_DATABASE_URL``
    when set. That is deliberate: a trusted system worker is handed a row id and
    must read that row to learn which agency owns it — a chicken-and-egg RLS
    cannot resolve. Falls back to ``ITTU_DATABASE_URL`` for single-role setups.

    **Because RLS is NOT filtering these queries, actor code carries BOTH
    obligations the policies would otherwise discharge:**

    - scope by ``agency_id`` explicitly (see ``honeypot_ops.dialer.resolve_case_id``);
    - check ``data_mode`` explicitly. The owning role bypasses the mode predicate
      from migration 20260823_18 exactly as it bypasses the agency one, so a
      worker will happily act on a row from the other evidentiary universe — a
      POC row dispatched as if real, or worse. Both actors refuse a mismatched
      row rather than proceed (``dialer._dial_one``, ``uncover.notifications``).

    They are stated together because a reader who learns "RLS is off here" needs
    to learn both duties at once; the mode one was added second and is the
    easier of the two to forget.

    **Why a fresh NullPool engine per invocation, not a cached pooled one:** each
    actor message runs under its own ``asyncio.run(...)`` — a brand-new event
    loop — and Dramatiq runs messages across several threads/processes. An
    asyncpg connection is bound to the loop that created it, so a pooled
    connection handed to a later message on a different loop fails with
    ``got Future ... attached to a different loop`` and the message retries
    forever (the row is left mid-flight, e.g. a dial target stuck in
    ``dialing``). NullPool + dispose guarantees no connection outlives its loop.
    The cost is one connect per message, which is noise next to a webhook POST
    or a phone call.

    Shared by the C1 notification dispatcher and the outbound dialer.
    """
    from sqlalchemy.pool import NullPool

    if _worker_sessionmaker_override is not None:  # tests only
        async with _worker_sessionmaker_override() as session:
            yield session
        return

    s = get_settings()
    url = s.migration_database_url or s.database_url
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as session:
            yield session
    finally:
        await engine.dispose()
