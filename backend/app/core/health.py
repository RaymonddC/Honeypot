"""Readiness diagnostics — one place that answers "why isn't it working?".

``/health`` stays deliberately shallow: it is Render's health check, and a
transient database blip must not take the whole service down. This module backs
``/ready``, which actually probes dependencies.

Every check here exists because that exact failure cost real debugging time, and
in each case the symptom pointed somewhere unhelpful:

* **schema behind the code** — "create case" 500'd with nothing naming the
  cause; the database was 3 migrations behind.
* **grants** — the app connects as the non-owning ``ittu_app`` role, and a
  schema missing from ``create_app_role.sql`` (``casedata`` was) fails with
  ``InsufficientPrivilege`` and no hint about grants.
* **RLS actually enforcing** — connecting as an owner silently bypasses every
  policy, so isolation "works" in testing and leaks in production. A boolean
  that says which role you are is worth more than a page of documentation.
* **Redis** — the queue path fails silently: jobs enqueue and nothing consumes,
  with no error anywhere.

Contains **no secrets and no connection strings** — booleans, role names, and
short reasons only — because a readiness probe is typically unauthenticated.
"""

import logging
from dataclasses import dataclass, field

from app.core.config import get_settings

_log = logging.getLogger("uvicorn.error")


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    critical: bool = True  # a non-critical check can fail without blocking ready


@dataclass
class Readiness:
    ready: bool
    mode: str
    persistence: str
    checks: list[Check] = field(default_factory=list)


async def _check_database() -> list[Check]:
    """Reachable, at migration head, and connected as the RLS-subject role."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.migration_guard import code_head_revision

    settings = get_settings()
    checks: list[Check] = []
    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            role = (await conn.execute(text("SELECT current_user"))).scalar()
        checks.append(Check("database", True, f"connected as {role}"))
        # Owner bypasses RLS entirely, so isolation would silently not apply.
        # Reported as a warning rather than a failure: single-role local setups
        # are legitimate, production is not.
        is_owner = bool(role) and role == "ittu"
        checks.append(
            Check(
                "rls_enforcing",
                not is_owner,
                "connected as the OWNING role — RLS is bypassed, agency isolation "
                "is NOT in effect" if is_owner else f"non-owning role ({role})",
                critical=False,
            )
        )
    except Exception as exc:  # noqa: BLE001 - a probe must report, not raise
        await engine.dispose()
        return [Check("database", False, f"unreachable: {type(exc).__name__}")]
    finally:
        await engine.dispose()

    # Schema version — the drift that broke case creation.
    head = code_head_revision()
    owner_url = settings.migration_database_url or settings.database_url
    owner_engine = create_async_engine(owner_url)
    try:
        from alembic.runtime.migration import MigrationContext

        async with owner_engine.connect() as conn:
            db_rev = await conn.run_sync(
                lambda c: MigrationContext.configure(c).get_current_revision()
            )
        at_head = db_rev == head
        checks.append(
            Check(
                "schema_at_head",
                at_head,
                f"at {head}" if at_head
                else f"DB at {db_rev}, code expects {head} — run `alembic upgrade head`",
            )
        )
    except Exception as exc:  # noqa: BLE001
        # ittu_app cannot read alembic_version; that is expected, not a failure.
        checks.append(
            Check(
                "schema_at_head", True,
                f"not verifiable from this role ({type(exc).__name__}) — set "
                "ITTU_MIGRATION_DATABASE_URL to enable",
                critical=False,
            )
        )
    finally:
        await owner_engine.dispose()
    return checks


async def _check_schema_grants() -> Check:
    """Every schema the app writes must be readable by the connecting role.

    A missing GRANT surfaces as InsufficientPrivilege at the first use of one
    feature, with nothing pointing at grants — that is how `casedata` stayed
    broken.
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    schemas = ("core", "intel", "chain", "fiat", "action", "casedata", "honeypot")
    engine = create_async_engine(get_settings().database_url)
    denied: list[str] = []
    try:
        async with engine.connect() as conn:
            for schema in schemas:
                usable = (
                    await conn.execute(
                        text("SELECT has_schema_privilege(current_user, :s, 'USAGE')"),
                        {"s": schema},
                    )
                ).scalar()
                if not usable:
                    denied.append(schema)
    except Exception as exc:  # noqa: BLE001
        return Check("schema_grants", False, f"could not check: {type(exc).__name__}")
    finally:
        await engine.dispose()
    return Check(
        "schema_grants",
        not denied,
        "all schemas usable" if not denied
        else f"no USAGE on {', '.join(denied)} — re-run scripts/create_app_role.sql",
    )


def _check_redis() -> Check:
    """Reachable broker. Without it, queued work vanishes with no error."""
    settings = get_settings()
    needed = settings.notification_delivery == "worker" or settings.dial_enqueue_on_start
    try:
        import redis

        redis.from_url(settings.redis_url).ping()
        return Check("redis", True, "reachable", critical=needed)
    except Exception as exc:  # noqa: BLE001
        return Check(
            "redis",
            False,
            f"unreachable ({type(exc).__name__}) — queued work will never run"
            if needed else f"unreachable ({type(exc).__name__}); nothing queues today",
            critical=needed,
        )


async def readiness() -> Readiness:
    """Probe every dependency. Never raises — a probe that 500s tells you less."""
    settings = get_settings()
    checks: list[Check] = []

    if settings.persistence == "postgres":
        try:
            checks.extend(await _check_database())
            checks.append(await _check_schema_grants())
        except Exception as exc:  # noqa: BLE001
            _log.warning("readiness: database checks failed: %s", exc)
            checks.append(Check("database", False, f"check errored: {type(exc).__name__}"))
    else:
        checks.append(
            Check("database", True, "memory persistence — no database in use", critical=False)
        )

    checks.append(_check_redis())
    return Readiness(
        ready=all(c.ok for c in checks if c.critical),
        mode=settings.mode,
        persistence=settings.persistence,
        checks=checks,
    )
