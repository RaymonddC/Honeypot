"""Migration-integrity guards — keep the DB schema from silently drifting behind
the code. This is the class of bug that made "create case" 500: the Neon DB was
3 migrations behind, so ``core.cases`` had no ``stage`` column and every insert
failed. These tests fail in CI instead.

- ``test_single_migration_head`` is DB-less and always runs.
- ``test_full_chain_applies_and_has_case_stage`` runs the WHOLE Alembic chain
  against an ephemeral in-process Postgres (pgserver — no Docker) and asserts it
  reaches head with the schema the app needs. Skips cleanly if pgserver isn't
  available (same as the other ``*_pg.py`` suites).

Note: a full ``alembic check`` (model-vs-migration autogenerate diff, which also
catches "changed a model but forgot the migration") is a stronger future guard,
but it currently reports pre-existing drift (constraint/index naming conventions,
a couple of ORM models out of sync with their raw-SQL migrations). It needs a
dedicated reconciliation pass before it can gate CI, so it's intentionally not
wired here yet.
"""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_DIR = Path(__file__).resolve().parents[1]


def _script() -> ScriptDirectory:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return ScriptDirectory.from_config(cfg)


def test_single_migration_head() -> None:
    """Exactly one head. Two heads mean ``upgrade head`` is ambiguous and a
    deploy can apply the wrong branch (or fail) — a merge migration is required."""
    heads = _script().get_heads()
    assert len(heads) == 1, (
        f"expected a single migration head, found {heads} — add a merge migration"
    )


@pytest.fixture(scope="module")
def migrated_pg():
    """Apply the full Alembic chain to a fresh ephemeral Postgres; yield
    ``(owner_async_uri, head_revision)``. Skips if pgserver can't run here."""
    pgserver = pytest.importorskip("pgserver", reason="pgserver (dev extra) not installed")
    import alembic.command

    from app.core.config import get_settings

    pgdata = tempfile.mkdtemp(prefix="ittu-pgdata-migcheck-")
    try:
        srv = pgserver.get_server(pgdata, cleanup_mode="delete")
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"pgserver could not start a Postgres instance here: {exc}")

    owner_uri = srv.get_uri().replace("postgresql://", "postgresql+asyncpg://", 1)
    prior_db = os.environ.get("ITTU_DATABASE_URL")
    prior_mig = os.environ.get("ITTU_MIGRATION_DATABASE_URL")
    # Pin both so env.py targets THIS cluster, not a developer .env's real Neon URL.
    os.environ["ITTU_DATABASE_URL"] = owner_uri
    os.environ["ITTU_MIGRATION_DATABASE_URL"] = owner_uri
    get_settings.cache_clear()
    try:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        alembic.command.upgrade(cfg, "head")  # proves the entire chain applies
        yield owner_uri, _script().get_current_head()
    finally:
        srv.cleanup()
        for key, prior in (
            ("ITTU_DATABASE_URL", prior_db),
            ("ITTU_MIGRATION_DATABASE_URL", prior_mig),
        ):
            if prior is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = prior
        get_settings.cache_clear()


def test_full_chain_applies_and_has_case_stage(migrated_pg) -> None:
    """The whole chain upgrades to head AND the schema has the columns the app
    writes — with ``core.cases.stage`` as the concrete canary (its absence is
    what broke case creation)."""
    owner_uri, head = migrated_pg
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    async def _check():
        eng = create_async_engine(owner_uri)
        try:
            async with eng.connect() as conn:
                rev = (await conn.execute(text("SELECT version_num FROM alembic_version"))).scalar()
                stage = (
                    await conn.execute(
                        text(
                            "SELECT 1 FROM information_schema.columns "
                            "WHERE table_schema='core' AND table_name='cases' "
                            "AND column_name='stage'"
                        )
                    )
                ).scalar()
            return rev, stage
        finally:
            await eng.dispose()

    rev, stage = asyncio.run(_check())
    assert rev == head, f"chain stopped at {rev!r}, expected head {head!r}"
    assert stage == 1, "core.cases.stage is missing — the exact drift that broke 'create case'"
