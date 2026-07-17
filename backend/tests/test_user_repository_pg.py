"""UserRepository (P-4b, docs/Persistence-Plan.md P-4) — login-boundary
SECURITY DEFINER functions validated against a real Postgres.

Same ephemeral, in-process Postgres harness as test_rls_isolation.py /
test_infiltrate_repository_pg.py (pgserver — no Docker needed): runs the full
Alembic chain (now through migration 20260717_09), creates the non-superuser
``ittu_app`` role via the real deploy script, and proves the login helpers
against it — connected AS ``ittu_app``, never the owning/migration role.

The point of this file: prove the crux the whole design hinges on —
1. A normal RLS-scoped (or unscoped) query as ``ittu_app`` CANNOT see another
   agency's ``core.users`` rows (or any rows at all with no session vars set)
   — RLS is still enforcing on this table.
2. The SECURITY DEFINER login functions CAN look a user up pre-auth (no
   session vars set at all) — proving they actually solve the login-vs-RLS
   deadlock, not just working "by accident" because RLS was left off.

Skips cleanly (not a failure) if ``pgserver`` isn't installed or can't start a
Postgres instance here — same as the other pgserver-backed test files.
"""

import importlib.util
import os
import tempfile
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.user_repository import PostgresUserRepository
from app.core.auth import SeedUser

BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATION_09_PATH = (
    BACKEND_DIR / "migrations" / "versions" / "20260717_09_user_login_helpers.py"
)

APP_ROLE_PASSWORD = "ittu-test-role-pw-3"  # noqa: S105 - ephemeral, throwaway DB only

# Real seeded agency/user ids (migration 20260708_05 / 20260717_09, app.core.auth).
AGENCY_A = "a190a9ca-d827-5c3a-a625-b788d9ab03c9"  # Bareskrim Polri
AGENCY_B = "84cb96f6-6dfb-5e5f-9fbd-d06ce68e7772"  # PPATK
BUDI_ID = "9f79eb96-3e3a-57b1-a617-311a785553a1"
BUDI_EMAIL = "budi@bareskrim.polri.go.id"
SARI_EMAIL = "sari@ppatk.go.id"


# --------------------------------------------------------------------------- #
# Memory path — no pgserver needed, proves the persistence-first-check
# invariant and the toggle selection, mirroring
# test_infiltrate_repository_pg.py's analogous memory-path test.
# --------------------------------------------------------------------------- #


async def test_get_optional_session_yields_none_under_memory_persistence():
    """persistence="memory" is the default — get_optional_session must yield
    None WITHOUT ever attempting a connection (same proof as
    test_infiltrate_repository_pg.py's get_optional_tenant_session test: the
    default ITTU_DATABASE_URL points at localhost:5432 with nothing
    listening, so touching the engine would error/hang, not cleanly return
    None)."""
    from app.core.config import get_settings
    from app.core.db import get_optional_session

    settings = get_settings()
    assert settings.persistence == "memory"  # sanity: this IS the default

    gen = get_optional_session()
    got = await gen.__anext__()
    assert got is None
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()


async def test_get_user_repository_selects_memory_impl_by_default():
    from app.core.user_repository import InMemoryUserRepository, get_user_repository

    repo = await get_user_repository(session=None)
    assert isinstance(repo, InMemoryUserRepository)


async def test_resolve_demo_user_finds_canonical_seeded_user_not_a_placeholder():
    """The exact subtlety migration 09's seed data exists for: an (agency,
    role) that already has a canonical seeded person (Budi) must resolve to
    THAT person via the repository path too — never synthesize a
    "<role>@<agency>.demo.ittu.id" placeholder duplicate."""
    from app.core.auth import find_agency
    from app.core.user_repository import get_user_repository, resolve_demo_user

    repo = await get_user_repository(session=None)
    agency = find_agency("bareskrim")
    user = await resolve_demo_user(repo, agency, "police-investigator")
    assert user.email == BUDI_EMAIL
    assert str(user.id) == BUDI_ID


def test_migration_09_seed_ids_match_the_actual_auth_source_of_truth():
    """The 6 seed rows in migration 09 were hand-computed offline (uuid5 of a
    fixed namespace + email) and hardcoded as migration literals — the same
    style migration 05 uses for AGENCIES/ROLES, and for the same reason
    (``alembic upgrade head --sql`` must render with no Postgres running, so
    the migration can't import app code at all).

    That means nothing stops the two from drifting: if ``app/core/auth.py``'s
    id scheme ever changes, or a digit was mistyped when these were computed,
    a green test suite would never catch it — demo login would silently
    start minting a phantom (non-canonical) user for a seeded (agency, role)
    pair instead of the real person, exactly the bug this migration exists to
    prevent. This test is the tripwire: it loads migration 09's ``SEED_USERS``
    constant by path (its filename starts with a digit, so it can't be a
    normal import) and asserts every row against ``app.core.auth.SEED_USERS``
    — the ACTUAL ``_user_id(email)``/``_agency_id(slug)`` computation, not a
    restated constant."""
    from app.core.auth import SEED_USERS as AUTH_SEED_USERS

    spec = importlib.util.spec_from_file_location("_migration_09", MIGRATION_09_PATH)
    migration_09 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration_09)

    auth_by_email = {u.email: u for u in AUTH_SEED_USERS}
    migration_rows = migration_09.SEED_USERS
    assert len(migration_rows) == len(AUTH_SEED_USERS)

    for user_id, agency_id, email, name, role in migration_rows:
        truth = auth_by_email.get(email)
        assert truth is not None, f"migration 09 seeds {email!r} — not in app.core.auth.SEED_USERS"
        assert user_id == str(truth.id), f"{email}: migration id {user_id} != _user_id() {truth.id}"
        assert agency_id == str(truth.agency_id), (
            f"{email}: migration agency_id {agency_id} != {truth.agency_id}"
        )
        assert name == truth.name
        assert role == truth.role


@pytest.fixture(scope="session")
def pg_cluster():
    pgserver = pytest.importorskip("pgserver", reason="pgserver (dev extra) not installed")

    pgdata = tempfile.mkdtemp(prefix="ittu-pgdata-users-")
    try:
        srv = pgserver.get_server(pgdata, cleanup_mode="delete")
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"pgserver could not start a Postgres instance here: {exc}")

    yield srv
    srv.cleanup()


@pytest.fixture(scope="session")
def app_role_uri(pg_cluster):
    """Run migrations 01→09, create ``ittu_app`` via the real deploy script."""
    import alembic.command
    from alembic.config import Config

    from app.core.config import get_settings

    owner_uri = pg_cluster.get_uri()
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


async def test_login_lookup_finds_seeded_user_without_any_rls_context(app_role_uri):
    """THE proof this migration exists for: connected as ittu_app, with NO
    app.current_agency/app.current_user set at all (exactly the pre-auth
    state at login), the SECURITY DEFINER helper still finds the seeded user —
    RLS did NOT block the login lookup."""
    _owner, app_uri = app_role_uri
    engine = create_async_engine(app_uri)
    try:
        session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)()
        try:
            repo = PostgresUserRepository(session)
            user = await repo.find_by_email(BUDI_EMAIL)
            assert user is not None
            assert str(user.id) == BUDI_ID
            assert str(user.agency_id) == AGENCY_A
            assert user.role == "police-investigator"

            by_role = await repo.find_by_agency_role(uuid.UUID(AGENCY_A), "police-investigator")
            assert by_role is not None
            assert str(by_role.id) == BUDI_ID

            assert await repo.find_by_email("nobody@nowhere.example") is None
        finally:
            await session.close()
    finally:
        await engine.dispose()


async def test_login_upsert_creates_and_updates_via_security_definer(app_role_uri):
    _owner, app_uri = app_role_uri
    engine = create_async_engine(app_uri)
    try:
        session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)()
        try:
            repo = PostgresUserRepository(session)
            new_id = uuid.uuid4()
            minted = SeedUser(
                id=new_id, agency_id=uuid.UUID(AGENCY_B),
                email=f"new-{new_id.hex[:8]}@ppatk.go.id", name="New Analyst",
                role="regulator-analyst",
            )
            created = await repo.upsert(minted)
            await session.commit()
            assert created.email == minted.email
            assert created.name == "New Analyst"

            # Re-upsert same id with a changed name — proves UPDATE branch.
            renamed = SeedUser(
                id=new_id, agency_id=uuid.UUID(AGENCY_B),
                email=minted.email, name="Renamed Analyst", role="regulator-analyst",
            )
            updated = await repo.upsert(renamed)
            await session.commit()
            assert updated.name == "Renamed Analyst"
            assert str(updated.id) == str(new_id)
        finally:
            await session.close()
    finally:
        await engine.dispose()


async def test_normal_tenant_query_still_cannot_see_other_agencies_users(app_role_uri):
    """Defense-in-depth check: the SECURITY DEFINER bypass is confined to the
    three login functions — a plain SELECT against core.users as ittu_app is
    still fully RLS-governed. Scoped to agency A sees ONLY agency A's users
    (never Sari, seeded under agency B); with no session var set at all it
    sees NOTHING (fail closed, not fail open) — same invariant
    test_rls_isolation.py proves for intel.scam_sessions."""
    _owner, app_uri = app_role_uri
    engine = create_async_engine(app_uri)
    try:
        async with engine.connect() as conn, conn.begin():
            await conn.execute(
                sa.text("SELECT set_config('app.current_agency', :v, true)"), {"v": AGENCY_A}
            )
            result = await conn.execute(sa.text("SELECT email FROM core.users"))
            seen = {row[0] for row in result.fetchall()}
        assert BUDI_EMAIL in seen
        assert SARI_EMAIL not in seen

        async with engine.connect() as conn, conn.begin():
            result = await conn.execute(sa.text("SELECT email FROM core.users"))
            rows = result.fetchall()
        assert rows == []
    finally:
        await engine.dispose()
