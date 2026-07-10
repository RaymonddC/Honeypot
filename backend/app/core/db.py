"""Async SQLAlchemy engine, session factory, and declarative Base.

Engine creation is lazy (no connection until first use), so the API can boot
and serve /health without Postgres running.
"""

from collections.abc import AsyncGenerator

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
    async with SessionLocal() as session, session.begin():
        for var, value in (
            ("app.current_agency", str(auth.agency.id)),
            ("app.current_user", str(auth.user.id)),
            ("app.current_role", auth.role),
        ):
            await session.execute(
                text("SELECT set_config(:var, :value, true)"),
                {"var": var, "value": value},
            )
        yield session
