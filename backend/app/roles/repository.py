"""Reading and writing ``core.roles`` — the role↔capability policy.

Dual store, same as every other module here: an in-memory implementation so the
POC/demo path works without a database, and a Postgres one that is the real
thing. The in-memory store starts from ``DEFAULT_ROLE_CAPABILITIES`` so a demo
begins with the same policy a fresh install gets.

Every write goes through ``app.core.roles.invalidate()`` so the resolver picks
the change up on the next request rather than after its TTL.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from app.core import roles as role_resolver
from app.core.config import get_settings


@dataclass
class RoleRecord:
    name: str
    capabilities: frozenset[str]
    agency_type: str | None = None


@runtime_checkable
class RoleRepository(Protocol):
    async def list_roles(self) -> list[RoleRecord]: ...
    async def get(self, name: str) -> RoleRecord | None: ...
    async def create(self, record: RoleRecord) -> RoleRecord: ...
    async def set_capabilities(self, name: str, capabilities: frozenset[str]) -> RoleRecord: ...
    async def delete(self, name: str) -> None: ...


# --------------------------------------------------------------------------- #
# In-memory (POC / tests)
# --------------------------------------------------------------------------- #


class InMemoryRoleRepository:
    """A view over ``app.core.roles``'s memory policy — NOT a second store.

    It deliberately keeps no dict of its own. An earlier version did, and the
    resolver went on answering from the static defaults, so editing a role in
    memory mode changed the admin screen and nothing else: the guards never saw
    it. One store means an edit here is the same edit the guard reads.
    """

    @classmethod
    def reset(cls) -> None:
        role_resolver.reset_memory_policy()

    async def list_roles(self) -> list[RoleRecord]:
        policy = role_resolver.memory_policy()
        return sorted(
            (RoleRecord(name=n, capabilities=c) for n, c in policy.items()),
            key=lambda r: r.name,
        )

    async def get(self, name: str) -> RoleRecord | None:
        policy = role_resolver.memory_policy()
        if name not in policy:
            return None
        return RoleRecord(name=name, capabilities=policy[name])

    async def create(self, record: RoleRecord) -> RoleRecord:
        role_resolver.set_memory_role(record.name, record.capabilities)
        return record

    async def set_capabilities(self, name: str, capabilities: frozenset[str]) -> RoleRecord:
        role_resolver.set_memory_role(name, capabilities)
        return RoleRecord(name=name, capabilities=capabilities)

    async def delete(self, name: str) -> None:
        role_resolver.delete_memory_role(name)


# --------------------------------------------------------------------------- #
# Postgres
# --------------------------------------------------------------------------- #


class PostgresRoleRepository:
    """``core.roles`` is GLOBAL — no ``agency_id``, and RLS deliberately does not
    gate writes here (migration 20260903_20 explains why). The barrier is the
    ``roles.admin`` capability in the router, not the database."""

    def __init__(self, session) -> None:
        self._session = session

    @staticmethod
    def _to_record(row) -> RoleRecord:
        granted = (row.permissions or {}).get("capabilities") or []
        return RoleRecord(
            name=row.name,
            capabilities=frozenset(c for c in granted if isinstance(c, str)),
            agency_type=row.agency_type,
        )

    async def list_roles(self) -> list[RoleRecord]:
        from sqlalchemy import select

        from app.core.models import Role

        rows = (await self._session.execute(select(Role).order_by(Role.name))).scalars().all()
        return [self._to_record(r) for r in rows]

    async def _row(self, name: str):
        from sqlalchemy import select

        from app.core.models import Role

        return (
            await self._session.execute(select(Role).where(Role.name == name))
        ).scalar_one_or_none()

    async def get(self, name: str) -> RoleRecord | None:
        row = await self._row(name)
        return self._to_record(row) if row else None

    async def create(self, record: RoleRecord) -> RoleRecord:
        from app.core.models import Role

        row = Role(
            id=uuid.uuid4(),
            name=record.name,
            agency_type=record.agency_type,
            permissions={"capabilities": sorted(record.capabilities)},
        )
        self._session.add(row)
        await self._session.flush()
        role_resolver.invalidate()
        return record

    async def set_capabilities(self, name: str, capabilities: frozenset[str]) -> RoleRecord:
        row = await self._row(name)
        # Reassigned rather than mutated in place: JSONB columns are not tracked
        # for in-place changes, so `row.permissions["capabilities"] = ...` would
        # flush nothing and the save would silently do nothing.
        row.permissions = {**(row.permissions or {}), "capabilities": sorted(capabilities)}
        await self._session.flush()
        role_resolver.invalidate()
        return self._to_record(row)

    async def delete(self, name: str) -> None:
        row = await self._row(name)
        if row is not None:
            await self._session.delete(row)
            await self._session.flush()
            role_resolver.invalidate()


def get_role_repository(session=None) -> RoleRepository:
    if session is not None and get_settings().persistence == "postgres":
        return PostgresRoleRepository(session)
    return InMemoryRoleRepository()
