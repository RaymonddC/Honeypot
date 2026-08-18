"""Alembic environment — async engine, wired to app settings + Base.metadata."""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.core.db import Base

# Import model modules here as they land so autogenerate sees them.
from app.action import models as action_models  # noqa: F401
from app.casedata import models as casedata_models  # noqa: F401
from app.core import models as core_models  # noqa: F401
from app.chain import models  # noqa: F401
from app.fiat import models as fiat_models  # noqa: F401
from app.honeypot_ops import models as honeypot_models  # noqa: F401
from app.intel import models as intel_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False is LOAD-BEARING. fileConfig defaults to
    # True, which disables every logger not named in alembic.ini — including
    # `ittu.request` and `uvicorn.error`, the ones the request log, the audit
    # writer and the migration guard use. Any in-process alembic call (a
    # management command, a test, a future migrate-on-boot) would therefore
    # silently switch application logging off, and the symptom — "the logs just
    # stopped" — points nowhere near migrations. Caught by a request-logging
    # test that failed only when a migration test ran first.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Migrations run as the OWNING role (ITTU_MIGRATION_DATABASE_URL) when set — the
# app's ITTU_DATABASE_URL is the non-owning ittu_app role that can't run DDL.
_settings = get_settings()
config.set_main_option(
    "sqlalchemy.url", _settings.migration_database_url or _settings.database_url
)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (emit SQL, no DBAPI)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def include_object(object_, name, type_, reflected, compare_to) -> bool:
    """Exclude CHECK constraints from autogenerate comparison.

    This project authors CHECK constraints in raw SQL inside the migrations
    (~48 of them: every ``ck_*_data_mode``, ``ck_*_status``, enum-ish value
    guards) and deliberately does NOT restate them on the ORM models — the
    models describe shape, the migrations own the invariants.

    Newer Alembic added a check-constraint autogenerate plugin, so it started
    reporting all of them as "removed" (model side has none) and `alembic check`
    failed with ~48 phantom diffs — while an older Alembic on the same code
    reported clean. Since ``alembic>=1.13`` is unpinned, that made the CI guard
    depend on whichever version the runner resolved.

    Excluding them here makes the guard deterministic across versions and honest
    about its scope: it compares tables/columns/indexes/FK/unique constraints.
    CHECK constraints, RLS policies and server-side functions remain outside
    autogenerate's reach and are reviewed by reading the migration.
    """
    if type_ == "check_constraint":
        return False
    return True


def do_run_migrations(connection: Connection) -> None:
    # include_schemas=True so autogenerate / `alembic check` inspect the named
    # schemas (core, fiat, intel, action, …), not just the default — otherwise
    # every core.*/fiat.* table looks "missing" and check is all false positives.
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
