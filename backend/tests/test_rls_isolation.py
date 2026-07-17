"""RLS isolation proof against a REAL Postgres (docs/Persistence-Plan.md P-1).

Docker isn't available in this environment, so this spins up an ephemeral,
in-process Postgres via ``pgserver`` (no Docker needed), runs the FULL
Alembic chain (01→06) against it, creates the non-superuser ``ittu_app`` role
via the actual deploy script (``backend/scripts/create_app_role.sql`` — this
proves the deliverable itself, not a reimplementation of it), and then proves
the thing that actually matters: a session connected AS ``ittu_app`` (never as
the owning/migration role — table owners and superusers bypass RLS) with
``app.current_agency`` set to agency A sees ONLY agency A's
``intel.scam_sessions`` row, never agency B's, and a transaction that never
sets ``app.current_agency`` sees NOTHING (fail closed, not fail open).

Skips cleanly (not a failure) if ``pgserver`` isn't installed or can't start a
Postgres instance here, so the rest of the suite — entirely in-memory/POC —
stays green without a real database.

Gotcha (learned the hard way): the ``pgserver`` server process is tied to its
Python handle's lifetime, so the handle MUST be held by a session-scoped
fixture — a function-scoped one would tear the server down between tests.
"""

import os
import tempfile
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Ephemeral, throwaway DB only — never a real credential.
APP_ROLE_PASSWORD = "ittu-test-role-pw-1"  # noqa: S105

# Real seeded agency ids (migration 20260708_05 / app.core.auth.SEED_AGENCIES) —
# using these rather than arbitrary uuids proves isolation against the exact
# seed data a demo JWT would carry.
AGENCY_A = "a190a9ca-d827-5c3a-a625-b788d9ab03c9"  # Bareskrim Polri
AGENCY_B = "84cb96f6-6dfb-5e5f-9fbd-d06ce68e7772"  # PPATK


@pytest.fixture(scope="session")
def pg_cluster():
    """Ephemeral in-process Postgres, held alive for the whole test session.

    Skips the module cleanly if pgserver isn't installed (it's a `dev` extra,
    not a hard dependency) or can't start a server in this sandbox.
    """
    pgserver = pytest.importorskip("pgserver", reason="pgserver (dev extra) not installed")

    pgdata = tempfile.mkdtemp(prefix="ittu-pgdata-")
    try:
        srv = pgserver.get_server(pgdata, cleanup_mode="delete")
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"pgserver could not start a Postgres instance here: {exc}")

    yield srv
    srv.cleanup()


@pytest.fixture(scope="session")
def app_role_uri(pg_cluster):
    """Run migrations 01→06, create ``ittu_app`` via the real deploy script.

    Returns ``(owner_async_uri, app_async_uri)``. ``ITTU_DATABASE_URL`` /
    ``get_settings()`` are only touched for the duration of the migration run
    (``get_settings`` is ``lru_cache``d, so alembic's env.py — which reads
    ``get_settings().database_url`` — needs the cache cleared to pick up the
    ephemeral URL) and are restored afterwards so the rest of the suite is
    unaffected.
    """
    import alembic.command
    from alembic.config import Config

    from app.core.config import get_settings

    owner_uri = pg_cluster.get_uri()  # postgresql://postgres:@/postgres?host=<socket_dir>
    owner_async_uri = owner_uri.replace("postgresql://", "postgresql+asyncpg://", 1)

    prior_env = os.environ.get("ITTU_DATABASE_URL")
    os.environ["ITTU_DATABASE_URL"] = owner_async_uri
    get_settings.cache_clear()
    try:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        alembic.command.upgrade(cfg, "head")

        role_script = (BACKEND_DIR / "scripts" / "create_app_role.sql").read_text()
        pg_cluster.psql(f"\\set app_role_password {APP_ROLE_PASSWORD}\n{role_script}")
    finally:
        if prior_env is None:
            os.environ.pop("ITTU_DATABASE_URL", None)
        else:
            os.environ["ITTU_DATABASE_URL"] = prior_env
        get_settings.cache_clear()

    host_part = owner_uri.split("@", 1)[1]  # "postgres?host=<socket_dir>"
    app_async_uri = f"postgresql+asyncpg://ittu_app:{APP_ROLE_PASSWORD}@{host_part}"
    return owner_async_uri, app_async_uri


@pytest.fixture(scope="session")
async def seeded_sessions(app_role_uri):
    """One intel.scam_sessions row for agency A, one for agency B — inserted
    as the OWNING role (fixture setup, not the assertion under test)."""
    owner_async_uri, _app_async_uri = app_role_uri
    engine = create_async_engine(owner_async_uri)
    try:
        async with engine.begin() as conn:
            for agency_id in (AGENCY_A, AGENCY_B):
                await conn.execute(
                    sa.text(
                        "INSERT INTO intel.scam_sessions (id, agency_id, channel_type) "
                        "VALUES (gen_random_uuid(), :agency_id, 'text')"
                    ),
                    {"agency_id": agency_id},
                )
    finally:
        await engine.dispose()


async def test_rls_isolates_by_agency(app_role_uri, seeded_sessions):
    """THE proof: connected as ittu_app (non-owning) with app.current_agency=A,
    a SELECT over intel.scam_sessions returns ONLY agency A's row — agency B's
    row (present in the table) is invisible. This is Postgres RLS actually
    enforcing multi-tenant isolation, not application-level filtering."""
    _owner_async_uri, app_async_uri = app_role_uri
    engine = create_async_engine(app_async_uri)
    try:
        async with engine.connect() as conn, conn.begin():
            await conn.execute(
                sa.text("SELECT set_config('app.current_agency', :v, true)"),
                {"v": AGENCY_A},
            )
            result = await conn.execute(sa.text("SELECT agency_id FROM intel.scam_sessions"))
            seen = {str(row[0]) for row in result.fetchall()}
    finally:
        await engine.dispose()

    assert seen == {AGENCY_A}
    assert AGENCY_B not in seen


async def test_rls_fails_closed_on_null_agency(app_role_uri, seeded_sessions):
    """A transaction that never sets app.current_agency sees NOTHING at all —
    fail closed (no rows), never fail open (all rows)."""
    _owner_async_uri, app_async_uri = app_role_uri
    engine = create_async_engine(app_async_uri)
    try:
        async with engine.connect() as conn, conn.begin():
            result = await conn.execute(sa.text("SELECT agency_id FROM intel.scam_sessions"))
            rows = result.fetchall()
    finally:
        await engine.dispose()

    assert rows == []


async def test_owning_role_bypasses_rls_by_design(app_role_uri, seeded_sessions):
    """Sanity check on the deployment invariant itself (docs/Deploy.md §4): the
    owning/migration role sees BOTH agencies' rows with no app.current_agency
    set at all — exactly why the app must never connect as it, and exactly the
    Neon caveat documented in docs/Deploy.md."""
    owner_async_uri, _app_async_uri = app_role_uri
    engine = create_async_engine(owner_async_uri)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(sa.text("SELECT agency_id FROM intel.scam_sessions"))
            seen = {str(row[0]) for row in result.fetchall()}
    finally:
        await engine.dispose()

    assert seen == {AGENCY_A, AGENCY_B}
