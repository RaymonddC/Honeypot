"""The custody collapse — a bundle's audit view now DURABLE, proven on Postgres.

``ActionBundle.audit`` used to be filled from ``uncover.custody.audit_log``: a
per-process, in-memory hash chain. It was empty after every restart, and the
Action Panel derived the displayed **evidence hash** from that chain's head — so
the same bundle showed one evidence hash before a restart and a different one
after. In a product whose pitch is chain of custody, that is the worst kind of
defect: not a crash, a quietly wrong number.

An in-memory test cannot prove the fix, because in memory mode BOTH chains die
with the process. So the central test here restarts for real — new engine, new
session, process-local state cleared — and asserts the bundle's history is still
there. Same pgserver harness as the other `_pg` files (no Docker); skips cleanly
when pgserver is unavailable.
"""

import os
import tempfile
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import db as db_module
from app.core.audit import (
    BUNDLE_GENERATED,
    DISPATCH_SENT,
    PostgresAuditRepository,
    record_action,
    reset_audit_store,
)
from app.core.auth import SEED_USERS
from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_ROLE_PASSWORD = "ittu-test-role-pw-5"  # noqa: S105 - ephemeral, throwaway DB only

_BUDI = next(u for u in SEED_USERS if u.email == "budi@bareskrim.polri.go.id")
_SARI = next(u for u in SEED_USERS if u.email == "sari@ppatk.go.id")
AGENCY_A = str(_BUDI.agency_id)
AGENCY_B = str(_SARI.agency_id)
BUDI_ID = str(_BUDI.id)


@pytest.fixture(scope="session")
def pg_cluster():
    pgserver = pytest.importorskip("pgserver", reason="pgserver (dev extra) not installed")

    pgdata = tempfile.mkdtemp(prefix="ittu-pgdata-custody-")
    try:
        srv = pgserver.get_server(pgdata, cleanup_mode="delete")
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"pgserver could not start a Postgres instance here: {exc}")
    yield srv
    srv.cleanup()


@pytest.fixture(scope="session")
def app_role_uri(pg_cluster):
    import alembic.command
    from alembic.config import Config

    owner_uri = pg_cluster.get_uri()
    owner_async_uri = owner_uri.replace("postgresql://", "postgresql+asyncpg://", 1)
    prior = {k: os.environ.get(k) for k in ("ITTU_DATABASE_URL", "ITTU_MIGRATION_DATABASE_URL")}
    os.environ["ITTU_DATABASE_URL"] = owner_async_uri
    os.environ["ITTU_MIGRATION_DATABASE_URL"] = owner_async_uri
    get_settings.cache_clear()
    try:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        alembic.command.upgrade(cfg, "head")
        role_script = (BACKEND_DIR / "scripts" / "create_app_role.sql").read_text()
        pg_cluster.psql(f"\\set app_role_password {APP_ROLE_PASSWORD}\n{role_script}")
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        get_settings.cache_clear()

    host_part = owner_uri.split("@", 1)[1]
    return f"postgresql+asyncpg://ittu_app:{APP_ROLE_PASSWORD}@{host_part}"


@pytest.fixture
async def pg(app_role_uri, monkeypatch):
    engine = create_async_engine(app_role_uri)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", maker)
    get_settings().persistence = "postgres"  # restored by conftest's autouse fixture
    reset_audit_store()
    try:
        yield app_role_uri, maker, engine
    finally:
        reset_audit_store()
        await engine.dispose()


async def _scoped(maker, agency: str):
    session = maker()
    await session.begin()
    for var, value in (
        ("app.current_agency", agency),
        ("app.current_user", BUDI_ID),
        ("app.current_role", "police-investigator"),
    ):
        await session.execute(
            sa.text("SELECT set_config(:v, :x, true)"), {"v": var, "x": value}
        )
    return session


async def _write_bundle_history(maker, agency: str, bundle_id: str) -> None:
    """Exactly what app/uncover/router.py records for a generate + dispatch."""
    async with await _scoped(maker, agency) as session:
        await record_action(
            session, agency_id=agency, action=BUNDLE_GENERATED,
            actor_user_id=BUDI_ID, actor_name="Budi Santoso",
            target_type="action_bundle", target_id=bundle_id,
            detail={"documents": [{"id": "doc_1", "sha256": "a" * 64}]},
        )
        await record_action(
            session, agency_id=agency, action=DISPATCH_SENT,
            actor_user_id=BUDI_ID, actor_name="Budi Santoso",
            target_type="action_bundle", target_id=bundle_id,
            detail={"recipients": ["BCA"]},
        )
        await session.commit()


# --------------------------------------------------------------------------- #


async def test_a_bundles_audit_view_survives_a_restart(pg):
    """THE test the collapse exists for.

    The old in-memory custody chain was empty after every restart. This writes a
    bundle's history, then genuinely restarts — disposes the engine, clears all
    process-local audit state, builds a new engine and session — and asserts the
    history is still readable. Nothing in this process carries it across.
    """
    uri, maker, first_engine = pg
    bundle_id = f"act_{uuid.uuid4().hex[:12]}"
    await _write_bundle_history(maker, AGENCY_A, bundle_id)

    # --- restart ---------------------------------------------------------
    reset_audit_store()           # anything the process was holding is gone
    await first_engine.dispose()  # drop every pooled connection too

    engine2 = create_async_engine(uri)
    maker2 = async_sessionmaker(engine2, class_=AsyncSession, expire_on_commit=False)
    try:
        async with await _scoped(maker2, AGENCY_A) as session:
            entries = await PostgresAuditRepository(session).list_for_target(
                agency_id=AGENCY_A, target_id=bundle_id
            )
        actions = [e.action for e in entries]
        assert actions == [BUNDLE_GENERATED, DISPATCH_SENT], (
            "the bundle's history did not survive the restart — this is exactly "
            f"what the in-memory custody chain did wrong. Got: {actions}"
        )
        # Oldest first: this is read as a narrative of one artifact.
        assert entries[0].seq < entries[1].seq
        assert entries[0].detail["_target_id"] == bundle_id, (
            "the entry no longer names its bundle — the business key was dropped "
            "again (core.audit_log.target_id is a uuid column; act_… is not one)"
        )
    finally:
        await engine2.dispose()


async def test_a_bundles_audit_view_is_agency_scoped(pg):
    """A bundle's custody view must never show another tenant's entries — and
    must not leak this agency's to another, even given the exact bundle id."""
    _uri, maker, _engine = pg
    bundle_id = f"act_{uuid.uuid4().hex[:12]}"
    await _write_bundle_history(maker, AGENCY_A, bundle_id)

    async with await _scoped(maker, AGENCY_B) as session:
        leaked = await PostgresAuditRepository(session).list_for_target(
            agency_id=AGENCY_B, target_id=bundle_id
        )
    assert leaked == [], f"agency B can read agency A's bundle history: {leaked}"

    # Asking for A's agency_id while scoped to B must also fail — RLS, not the
    # WHERE clause, is what has to make this empty.
    async with await _scoped(maker, AGENCY_B) as session:
        cross = await PostgresAuditRepository(session).list_for_target(
            agency_id=AGENCY_A, target_id=bundle_id
        )
    assert cross == [], f"RLS did not block a cross-agency read: {cross}"


async def test_only_this_bundles_entries_are_returned(pg):
    """The filter has to be a filter. A second bundle in the same agency must
    not appear in the first one's custody view."""
    _uri, maker, _engine = pg
    mine = f"act_{uuid.uuid4().hex[:12]}"
    theirs = f"act_{uuid.uuid4().hex[:12]}"
    await _write_bundle_history(maker, AGENCY_A, mine)
    await _write_bundle_history(maker, AGENCY_A, theirs)

    async with await _scoped(maker, AGENCY_A) as session:
        entries = await PostgresAuditRepository(session).list_for_target(
            agency_id=AGENCY_A, target_id=mine
        )
    targets = {e.detail.get("_target_id") for e in entries}
    assert targets == {mine}, f"another bundle's entries bled in: {targets}"
    assert len(entries) == 2
