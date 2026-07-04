"""Async SQLAlchemy engine, session factory, and declarative Base.

Engine creation is lazy (no connection until first use), so the API can boot
and serve /health without Postgres running.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """Declarative base — Alembic autogenerate targets Base.metadata."""


engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)

SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yield a request-scoped async session."""
    async with SessionLocal() as session:
        yield session
