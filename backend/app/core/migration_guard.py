"""Startup migration-drift guard.

In Postgres mode, verify at boot that the database is at the code's Alembic
head. A schema-drifted app WILL 500 on the first write that touches the missing
object — exactly what happened when ``core.cases`` was missing the ``stage``
column: "create case" failed with a mysterious 500 and nothing pointed at the
real cause (the DB being 3 migrations behind).

Failing loud at startup turns that into an obvious boot error that names the fix.
Memory mode has no schema, so the check is a no-op there.
"""

import logging
from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

_log = logging.getLogger("uvicorn.error")
_BACKEND_DIR = Path(__file__).resolve().parents[2]


def code_head_revision() -> str | None:
    """The migration head the current code expects (read from the files, no DB)."""
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    return ScriptDirectory.from_config(cfg).get_current_head()


async def assert_schema_at_head() -> None:
    """Fail loud (raise) if the Postgres schema is behind the code's Alembic head.

    Reads the DB's applied revision using the OWNER/migration URL — the app's
    ``ittu_app`` role can't read ``alembic_version`` (permission denied). If the
    revision can't be determined (no migration URL, unreachable), log a warning
    and continue rather than block boot on an unknown.
    """
    settings = get_settings()
    if settings.persistence != "postgres":
        return  # memory mode: no schema to drift

    head = code_head_revision()

    url = settings.migration_database_url or settings.database_url
    check_engine = create_async_engine(url)
    try:
        async with check_engine.connect() as conn:
            db_rev = await conn.run_sync(
                lambda sync_conn: MigrationContext.configure(sync_conn).get_current_revision()
            )
    except Exception as exc:  # noqa: BLE001 - never block boot on an unverifiable check
        _log.warning(
            "migration guard: could not read the DB revision (%s: %s) — skipping "
            "the drift check. Set ITTU_MIGRATION_DATABASE_URL (owner role) so this "
            "check can run.",
            type(exc).__name__,
            exc,
        )
        return
    finally:
        await check_engine.dispose()

    if db_rev != head:
        raise RuntimeError(
            f"DB SCHEMA DRIFT: database is at Alembic revision {db_rev!r} but this "
            f"code expects {head!r}. Writes will fail until the DB is migrated. Run "
            "`alembic upgrade head` as the owner role (ITTU_MIGRATION_DATABASE_URL), "
            "or ensure the deploy entrypoint applies migrations before startup."
        )

    _log.info("migration guard: DB schema at head (%s).", head)
