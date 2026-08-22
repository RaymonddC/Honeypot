"""Denied actions land DURABLY — proven against a real Postgres.

This file exists for one reason, and it is a trap that an in-memory test cannot
see. ``app/core/db.py``'s ``_tenant_scoped_session`` opens **one transaction per
request** (``async with SessionLocal() as session, session.begin():``). A guard
that raises ``HTTPException`` leaves that context with an exception, so the
transaction ROLLS BACK — and an audit row written on the request's session rolls
back with it. In memory mode there is no transaction to lose, so the naive
implementation passes every test and records nothing in production.

So the assertion here is not "a row appears". It is: after the request
transaction unwinds, the DENIAL is still in the table and a control row written
the ordinary way on the request's session is GONE. If the denial ever moves back
onto the request session, the control and the denial will vanish together and
this test goes red.

Same ephemeral, in-process Postgres harness as ``test_user_repository_pg.py``
(pgserver — no Docker): the full Alembic chain, then the non-superuser
``ittu_app`` role from the real deploy script, so ``core.audit_log``'s RLS
policies are actually enforcing. Skips cleanly if pgserver is unavailable.
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
    USER_DEACTIVATED,
    USER_ROLE_CHANGED,
    PostgresAuditRepository,
    record_action,
    record_denial,
    reset_audit_store,
)
from app.core.auth import SEED_USERS
from app.core.config import get_mode_resolver, get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_ROLE_PASSWORD = "ittu-test-role-pw-4"  # noqa: S105 - ephemeral, throwaway DB only

_BUDI = next(u for u in SEED_USERS if u.email == "budi@bareskrim.polri.go.id")
AGENCY_A = str(_BUDI.agency_id)
BUDI_ID = str(_BUDI.id)


def _reset_settings_caches() -> None:
    """Rebuild the settings singleton — AND everything holding a reference to it.

    ``get_mode_resolver`` is separately ``@lru_cache``d and captures the Settings
    instance it was built with, so clearing only ``get_settings`` leaves the
    resolver pointing at an orphaned object: later tests then mutate the new
    singleton while ``/api/config`` and ``_auth_mode()`` keep reading the old
    one. The other pgserver files clear only ``get_settings`` and get away with
    it purely because they sort AFTER the auth tests alphabetically — this file
    does not, which is how the trap surfaced. Flagged for a proper fix (the
    resolver should not cache the instance); clearing both is the local one.
    """
    get_settings.cache_clear()
    get_mode_resolver.cache_clear()


@pytest.fixture(scope="session")
def pg_cluster():
    pgserver = pytest.importorskip("pgserver", reason="pgserver (dev extra) not installed")

    pgdata = tempfile.mkdtemp(prefix="ittu-pgdata-denials-")
    try:
        srv = pgserver.get_server(pgdata, cleanup_mode="delete")
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"pgserver could not start a Postgres instance here: {exc}")

    yield srv
    srv.cleanup()


@pytest.fixture(scope="session")
def app_role_uri(pg_cluster):
    """Migrations to head, then ``ittu_app`` via the real deploy script."""
    import alembic.command
    from alembic.config import Config

    owner_uri = pg_cluster.get_uri()
    owner_async_uri = owner_uri.replace("postgresql://", "postgresql+asyncpg://", 1)

    prior = {
        k: os.environ.get(k)
        for k in ("ITTU_DATABASE_URL", "ITTU_MIGRATION_DATABASE_URL")
    }
    os.environ["ITTU_DATABASE_URL"] = owner_async_uri
    # env.py prefers ITTU_MIGRATION_DATABASE_URL — a developer .env may point it
    # at a real owner URL, which would send alembic THERE. Pin it here.
    os.environ["ITTU_MIGRATION_DATABASE_URL"] = owner_async_uri
    _reset_settings_caches()
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
        _reset_settings_caches()

    host_part = owner_uri.split("@", 1)[1]  # "postgres?host=<socket_dir>"
    return f"postgresql+asyncpg://ittu_app:{APP_ROLE_PASSWORD}@{host_part}"


@pytest.fixture
async def pg_audit(app_role_uri, monkeypatch):
    """Wire the app's Postgres path at the two seams denials use.

    ``record_denial`` reads ``SessionLocal`` off ``app.core.db`` at CALL time
    precisely so this patch reaches it — binding the name at import time would
    freeze whichever sessionmaker existed then.
    """
    engine = create_async_engine(app_role_uri)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_module, "SessionLocal", maker)
    get_settings().persistence = "postgres"  # restored by conftest's autouse fixture
    reset_audit_store()  # clear the denial rate counters between tests
    try:
        yield engine, maker
    finally:
        reset_audit_store()
        await engine.dispose()


async def _set_rls(session, agency_id: str, user_id: str, role: str) -> None:
    """Set the vars the core.* policies read — what a real request session does."""
    for var, value in (
        ("app.current_agency", agency_id),
        ("app.current_user", user_id),
        ("app.current_role", role),
    ):
        await session.execute(
            sa.text("SELECT set_config(:var, :value, true)"), {"var": var, "value": value}
        )


async def _rows(engine, agency_id: str) -> list[dict]:
    """Every committed audit row for an agency, oldest first."""
    async with engine.connect() as conn, conn.begin():
        await conn.execute(
            sa.text("SELECT set_config('app.current_agency', :v, true)"), {"v": agency_id}
        )
        result = await conn.execute(
            sa.text("SELECT seq, action, detail FROM core.audit_log ORDER BY seq")
        )
        return [{"seq": r[0], "action": r[1], "detail": r[2] or {}} for r in result.fetchall()]


# --------------------------------------------------------------------------- #


async def test_a_denial_survives_the_request_transaction_rolling_back(pg_audit):
    """THE test. A guard's denial must outlive the transaction the guard kills."""
    engine, maker = pg_audit
    agency = AGENCY_A

    before = await _rows(engine, agency)

    class _GuardRaised(Exception):
        """Stands in for the HTTPException a guard raises."""

    with pytest.raises(_GuardRaised):
        # Byte-for-byte the shape of app/core/db.py's request session.
        async with maker() as session, session.begin():
            await _set_rls(session, agency, BUDI_ID, "agency-admin")

            # CONTROL: the ordinary success path, on the request's session. It
            # must NOT survive — if it does, the transaction never rolled back
            # and this test proves nothing about the denial.
            await record_action(
                session,
                agency_id=agency,
                action=USER_ROLE_CHANGED,
                actor_user_id=BUDI_ID,
                detail={"marker": "control-on-request-session"},
            )
            # The denial — takes no session, opens and commits its own.
            await record_denial(
                agency_id=agency,
                action=USER_ROLE_CHANGED,
                denial_code="privilege_escalation",
                actor_user_id=BUDI_ID,
                actor_name="Budi",
                actor_role="agency-admin",
                target_type="user",
                target_id=str(uuid.uuid4()),
                detail={"marker": "denied"},
            )
            raise _GuardRaised

    after = await _rows(engine, agency)
    added = after[len(before):]
    markers = [r["detail"].get("marker") for r in added]

    assert "control-on-request-session" not in markers, (
        "the request transaction did NOT roll back, so this test cannot prove "
        f"anything about the denial. Rows added: {added}"
    )
    assert "denied" in markers, (
        "the denial did not survive the rollback — it was almost certainly "
        f"written on the request's session. Rows added: {added}"
    )

    denial = next(r for r in added if r["detail"].get("marker") == "denied")
    assert denial["action"] == USER_ROLE_CHANGED, (
        "a denial keeps the DOMAIN action name so 'everything this actor did' "
        f"stays one query — got {denial['action']!r}"
    )
    assert denial["detail"]["_outcome"] == "denied"
    assert denial["detail"]["_denial_code"] == "privilege_escalation"


async def test_the_chain_still_verifies_with_denials_interleaved(pg_audit):
    """Denials are chained like anything else — a mixed chain must verify.

    Successes and denials are written by DIFFERENT transactions, so if the
    denial path got the sequence or the previous hash wrong the chain would
    break exactly here and nowhere else.
    """
    engine, maker = pg_audit
    agency = AGENCY_A
    # The cluster is session-scoped and rows are append-only, so earlier tests
    # in this file leave entries behind. Baseline them out — and note that
    # verify_chain below still covers ALL of them, which is the stronger check.
    baseline = len(await _rows(engine, agency))

    for i in range(3):
        async with maker() as session, session.begin():
            await _set_rls(session, agency, BUDI_ID, "agency-admin")
            await record_action(
                session,
                agency_id=agency,
                action=USER_ROLE_CHANGED,
                actor_user_id=BUDI_ID,
                detail={"i": i},
            )
        # …and a denial between each pair, on its own transaction.
        await record_denial(
            agency_id=agency,
            action=USER_DEACTIVATED,
            denial_code="last_admin",
            actor_user_id=BUDI_ID,
            actor_role="agency-admin",
            detail={"i": i},
        )

    async with maker() as session, session.begin():
        await _set_rls(session, agency, BUDI_ID, "agency-admin")
        ok, broken_at = await PostgresAuditRepository(session).verify_chain(agency_id=agency)

    rows = await _rows(engine, agency)
    assert ok is True, (
        f"chain broke at seq {broken_at} with denials interleaved. Chain was: "
        f"{[(r['seq'], r['action'], r['detail'].get('_outcome', 'success')) for r in rows]}"
    )
    outcomes = [r["detail"].get("_outcome", "success") for r in rows[baseline:]]
    assert outcomes == ["success", "denied"] * 3, (
        f"the interleaving is not what was written — got {outcomes}"
    )


async def test_a_denial_is_written_under_rls_as_the_unprivileged_app_role(pg_audit):
    """The denial session carries no request context, so it must set the RLS
    vars itself — ``core.audit_log``'s insert policy is ``agency_id =
    core.current_agency()`` and fails CLOSED against an unset one. Connected as
    ittu_app (non-superuser), a row appearing at all is the proof it did.

    And the entry must be invisible to a different tenant: a denial is still
    agency-private evidence.
    """
    engine, _maker = pg_audit
    other_agency = str(next(u for u in SEED_USERS if u.email == "sari@ppatk.go.id").agency_id)

    entry = await record_denial(
        agency_id=AGENCY_A,
        action=USER_ROLE_CHANGED,
        denial_code="cross_agency_forbidden",
        actor_user_id=BUDI_ID,
        actor_role="agency-admin",
    )
    assert entry is not None, "the insert was refused or errored — see the audit warning log"

    assert any(r["detail"].get("_denial_code") == "cross_agency_forbidden"
               for r in await _rows(engine, AGENCY_A))
    leaked = [
        r for r in await _rows(engine, other_agency)
        if r["detail"].get("_denial_code") == "cross_agency_forbidden"
    ]
    assert leaked == [], f"another agency can read this denial: {leaked}"
