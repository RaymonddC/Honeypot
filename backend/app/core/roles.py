"""Roles as DATA — resolving a role name to the capabilities it holds.

``app/core/capabilities.py`` defines WHAT can be permitted (closed, code-defined).
This module answers WHO holds each one, by reading ``core.roles.permissions`` —
so an agency can add a role, or change what an existing one may do, without a
deploy.

**Why a cache, and why this one.** The guard runs on every protected request, and
a database round-trip per request to answer "may this role do X" is a poor trade
when roles change perhaps monthly. The whole table is a handful of rows, so one
query loads all of it. Two things then keep it honest:

* an explicit ``invalidate()`` on every role edit, so a permission change takes
  effect on the next request in the process that made it, and
* a short TTL as the backstop for OTHER processes — with more than one instance,
  an edit here is not visible there until the TTL lapses. That bound is stated
  rather than hidden: revocation is fast, not instant.

**Fail closed.** If the table cannot be read, this returns NO capabilities rather
than falling back to the seeded defaults. A database that is down must not
quietly hand out permissions from a copy in the code — that is how a revoked
capability comes back to life during an outage.
"""

from __future__ import annotations

import logging
import time

from app.core.capabilities import DEFAULT_ROLE_CAPABILITIES, is_capability
from app.core.config import get_settings

_log = logging.getLogger("uvicorn.error")

#: How long another process may keep serving a stale role→capability map.
#: Short, because it bounds how long a REVOKED capability keeps working.
CACHE_TTL_SECONDS = 30.0

_cache: dict[str, frozenset[str]] | None = None
_cache_expires_at: float = 0.0


def invalidate() -> None:
    """Drop the cached map — call after ANY write to ``core.roles``.

    In-process only. Other instances pick the change up when their TTL lapses;
    see the module docstring.
    """
    global _cache, _cache_expires_at
    _cache = None
    _cache_expires_at = 0.0


#: The memory-mode policy. Lives HERE, not in ``app/roles/repository.py``, so the
#: resolver and the admin API share one source of truth — an earlier version had
#: the repository keep its own dict while this module returned the static
#: defaults, so editing a role in memory mode changed nothing about what anyone
#: could actually do. The admin screen would have looked like it worked.
_memory_policy: dict[str, frozenset[str]] = {}


def memory_policy() -> dict[str, frozenset[str]]:
    """The in-memory role→capability map, seeded on first use."""
    if not _memory_policy:
        reset_memory_policy()
    return _memory_policy


def reset_memory_policy() -> None:
    """Back to the seeded defaults (fresh process, or a test)."""
    _memory_policy.clear()
    _memory_policy.update({k: frozenset(v) for k, v in DEFAULT_ROLE_CAPABILITIES.items()})
    invalidate()


def set_memory_role(name: str, capabilities: frozenset[str]) -> None:
    _memory_policy[name] = frozenset(capabilities)
    invalidate()


def delete_memory_role(name: str) -> None:
    _memory_policy.pop(name, None)
    invalidate()


async def _load_from_db() -> dict[str, frozenset[str]] | None:
    """Read every role's permissions. ``None`` means "could not read" — which the
    caller must treat as no capabilities, NOT as the defaults."""
    from sqlalchemy import select

    from app.core.db import SessionLocal
    from app.core.models import Role

    try:
        async with SessionLocal() as session:
            rows = (await session.execute(select(Role))).scalars().all()
    except Exception as exc:  # noqa: BLE001 - a guard must not 500 on a db blip
        _log.error(
            "roles: could not read core.roles (%s: %s) — treating every role as "
            "having NO capabilities. Protected endpoints will 403 until this "
            "recovers, which is the safe direction.",
            type(exc).__name__,
            exc,
        )
        return None

    resolved: dict[str, frozenset[str]] = {}
    for row in rows:
        # `permissions` is JSONB and hand-editable, so treat it as untrusted:
        # a stray key that no longer maps to a real capability is dropped rather
        # than honoured, because the UI would otherwise show a protection that
        # nothing enforces.
        granted = (row.permissions or {}).get("capabilities") or []
        if not isinstance(granted, list):
            _log.warning(
                "roles: %r has a non-list `capabilities` (%s) — ignoring it",
                row.name, type(granted).__name__,
            )
            granted = []
        kept = {c for c in granted if isinstance(c, str) and is_capability(c)}
        dropped = {c for c in granted if isinstance(c, str)} - kept
        if dropped:
            _log.warning(
                "roles: %r lists capabilities this build does not enforce: %s — "
                "ignored. They were valid in another version, or are a typo.",
                row.name, sorted(dropped),
            )
        resolved[row.name] = frozenset(kept)
    return resolved


async def all_role_capabilities() -> dict[str, frozenset[str]]:
    """Every role and what it may do, cached. Empty dict on a read failure."""
    global _cache, _cache_expires_at

    now = time.monotonic()
    if _cache is not None and now < _cache_expires_at:
        return _cache

    if get_settings().persistence != "postgres":
        loaded: dict[str, frozenset[str]] | None = dict(memory_policy())
    else:
        loaded = await _load_from_db()

    if loaded is None:
        # Do NOT cache a failure: retry on the next request rather than serving
        # "no capabilities" for the whole TTL after a transient blip.
        return {}

    _cache = loaded
    _cache_expires_at = now + CACHE_TTL_SECONDS
    return _cache


async def capabilities_for(role: str) -> frozenset[str]:
    """What ``role`` may do. An unknown role holds NOTHING.

    An unknown role is not an error here: a role can be deleted while someone
    still holds a token naming it. They lose their capabilities, which is the
    intended consequence — and the role admin API refuses the delete in the first
    place while anyone is assigned to it.
    """
    return (await all_role_capabilities()).get(role, frozenset())


async def has_capability(role: str, capability: str) -> bool:
    return capability in await capabilities_for(role)
