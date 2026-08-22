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

import asyncio
import importlib.util
import logging
import os
import tempfile
import time
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import db as db_module
from app.core.audit import (
    DENIAL_LOCK_TIMEOUT_MS,
    USER_DEACTIVATED,
    USER_ROLE_CHANGED,
    PostgresAuditRepository,
    record_action,
    record_denial,
    reset_audit_store,
)
from app.core.auth import SEED_USERS
from app.core.config import get_settings

BACKEND_DIR = Path(__file__).resolve().parents[1]
APP_ROLE_PASSWORD = "ittu-test-role-pw-4"  # noqa: S105 - ephemeral, throwaway DB only


def _load_migration_17():
    """Load migration 20260822_17 by path — its filename starts with a digit, so
    it cannot be imported normally (same trick as test_user_repository_pg.py).

    Imported rather than restated so the dirty-data test below runs the
    migration's ACTUAL detection query. A copied query here could drift from the
    real one and keep passing while the migration silently stopped detecting
    anything.
    """
    path = BACKEND_DIR / "migrations" / "versions" / "20260822_17_audit_log_seq_unique.py"
    spec = importlib.util.spec_from_file_location("_migration_17", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_MIGRATION_17 = _load_migration_17()
INDEX_NAME = _MIGRATION_17.INDEX_NAME
_DUPLICATES = _MIGRATION_17._DUPLICATES

_BUDI = next(u for u in SEED_USERS if u.email == "budi@bareskrim.polri.go.id")
AGENCY_A = str(_BUDI.agency_id)
BUDI_ID = str(_BUDI.id)


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

    host_part = owner_uri.split("@", 1)[1]  # "postgres?host=<socket_dir>"
    return f"postgresql+asyncpg://ittu_app:{APP_ROLE_PASSWORD}@{host_part}"


@pytest.fixture(scope="session")
def owner_uri(pg_cluster, app_role_uri):
    """The OWNING role's URI. Needed only by the dirty-data test, which drops and
    recreates the unique index — ``ittu_app`` is deliberately not the index owner
    (that separation is the same one RLS depends on), so it cannot."""
    return pg_cluster.get_uri().replace("postgresql://", "postgresql+asyncpg://", 1)


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
            # CONTROL: the ordinary success path, on the request's session. It
            # must NOT survive — if it does, the transaction never rolled back
            # and this test proves nothing about the denial.
            #
            # ORDER MATTERS, do not swap these back. Since migration 20260822_17
            # added UNIQUE (agency_id, seq), writing the control FIRST leaves an
            # uncommitted row squatting on the position the denial needs, and the
            # denial is then genuinely unserviceable — it is dropped rather than
            # written. That behaviour is real and is pinned by
            # test_a_denial_is_dropped_loudly_when_the_chain_head_is_uncommitted
            # below; this test is about the rollback property, so it does not
            # manufacture that collision.
            await record_action(
                session,
                agency_id=agency,
                action=USER_ROLE_CHANGED,
                actor_user_id=BUDI_ID,
                detail={"marker": "control-on-request-session"},
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


# --------------------------------------------------------------------------- #
# The seq allocation race (migration 20260822_17 + the retry in record()).
#
# `seq` and `prev_sha256` both come from the chain head read at the top of
# record(). Two transactions that read the same head therefore produce two
# entries claiming the same position AND the same predecessor — the chain
# FORKS, verify_chain reports it broken, and "broken" reads as tampering. These
# tests race real transactions against real Postgres; nothing here is simulated.
# --------------------------------------------------------------------------- #


def _fresh_agency() -> str:
    """A private agency per test — the cluster is session-scoped and audit_log is
    append-only, so sharing one would make counts depend on test order."""
    return str(uuid.uuid4())


async def _write_one(maker, agency: str, marker: int, ready: asyncio.Barrier) -> str:
    """One concurrent writer, shaped like a request: its own transaction, RLS
    set, one audit entry. The barrier is what makes this a race rather than a
    sequence — every writer reads the chain head before any of them commits."""
    async with maker() as session, session.begin():
        await _set_rls(session, agency, BUDI_ID, "agency-admin")
        await ready.wait()
        await record_action(
            session, agency_id=agency, action=USER_ROLE_CHANGED,
            actor_user_id=BUDI_ID, detail={"marker": marker},
        )
    return "ok"


async def test_concurrent_writers_for_one_agency_do_not_fork_the_chain(pg_audit):
    """THE race. Eight transactions append to one agency's chain at once."""
    engine, maker = pg_audit
    agency = _fresh_agency()
    writers = 8

    ready = asyncio.Barrier(writers)
    await asyncio.gather(*(_write_one(maker, agency, i, ready) for i in range(writers)))

    rows = await _rows(engine, agency)
    seqs = [r["seq"] for r in rows]
    markers = sorted(r["detail"]["marker"] for r in rows)

    assert seqs == sorted(set(seqs)), (
        f"duplicate seq — the chain forked: {seqs}"
    )
    assert seqs == list(range(1, writers + 1)), (
        f"expected a gapless 1..{writers}; got {seqs}"
    )
    assert markers == list(range(writers)), (
        f"a writer was lost to the race — markers present: {markers}"
    )

    async with maker() as session, session.begin():
        await _set_rls(session, agency, BUDI_ID, "agency-admin")
        ok, broken_at = await PostgresAuditRepository(session).verify_chain(agency_id=agency)
    assert ok is True, (
        f"chain broke at seq {broken_at} after {writers} concurrent writers — a "
        "routine concurrent write must never look like tampering. Chain: "
        f"{[(r['seq'], r['detail']) for r in rows]}"
    )


async def test_a_racing_writer_chains_onto_the_winner_not_beside_it(pg_audit):
    """Renumbering alone would not be enough: the loser must also re-read the
    winner's HASH. If it retried with a fresh seq but a stale ``prev_sha256``,
    every seq would be unique and the chain would still be forked."""
    engine, maker = pg_audit
    agency = _fresh_agency()

    ready = asyncio.Barrier(2)
    await asyncio.gather(*(_write_one(maker, agency, i, ready) for i in range(2)))

    rows = await _rows(engine, agency)
    async with engine.connect() as conn, conn.begin():
        await conn.execute(
            sa.text("SELECT set_config('app.current_agency', :v, true)"), {"v": agency}
        )
        hashes = (
            await conn.execute(
                sa.text(
                    "SELECT seq, encode(sha256,'hex'), encode(prev_sha256,'hex') "
                    "FROM core.audit_log ORDER BY seq"
                )
            )
        ).fetchall()

    assert len(hashes) == 2, f"expected 2 entries, got {rows}"
    first, second = hashes
    assert second[2] == first[1], (
        "entry 2's prev_sha256 does not point at entry 1's sha256 — the loser "
        f"retried the number but kept a stale predecessor. Got prev={second[2]}, "
        f"expected {first[1]}"
    )


async def test_a_denial_is_dropped_loudly_when_the_chain_head_is_uncommitted(pg_audit, caplog):
    """The one case that cannot be served, pinned so it stays a known quantity.

    If the enclosing request transaction has already written an UNCOMMITTED row
    at the chain position a denial needs, the denial cannot be appended: it can
    neither wait (the holder is waiting on this very ``await`` — Postgres sees
    no deadlock because the other side is blocked in Python, not in the
    database) nor pick another position (chaining onto a row that may roll back
    is precisely the fork we just fixed).

    So the requirement is not that it succeeds. It is that it fails FAST and
    LOUDLY instead of hanging a request forever, which is what it did before
    ``lock_timeout`` was set on this path.
    """
    _engine, maker = pg_audit
    agency = _fresh_agency()
    caplog.set_level(logging.ERROR, logger="uvicorn.error")

    async with maker() as session, session.begin():
        await _set_rls(session, agency, BUDI_ID, "agency-admin")
        await record_action(
            session, agency_id=agency, action=USER_ROLE_CHANGED,
            actor_user_id=BUDI_ID, detail={"marker": "uncommitted-head"},
        )

        started = time.monotonic()
        # wait_for is the anti-hang assertion: before lock_timeout this never
        # returned at all, and the suite had to be killed.
        entry = await asyncio.wait_for(
            record_denial(
                agency_id=agency, action=USER_DEACTIVATED, denial_code="last_admin",
                actor_user_id=BUDI_ID, actor_role="agency-admin",
            ),
            timeout=20,
        )
        elapsed = time.monotonic() - started

    assert entry is None, "the denial cannot be appended here and must say so by returning None"
    assert elapsed < 5, (
        f"took {elapsed:.1f}s — lock_timeout ({DENIAL_LOCK_TIMEOUT_MS}ms) is not "
        "bounding this wait, so it is still effectively a hang"
    )
    dropped = [r for r in caplog.records if "DROPPED denied" in r.getMessage()]
    assert dropped, (
        "a dropped evidentiary entry must be logged at ERROR — the log line is "
        f"the only record it happened. Saw: {[r.getMessage() for r in caplog.records]}"
    )


async def test_the_migration_refuses_to_install_the_guard_over_a_forked_chain(owner_uri):
    """The dirty-data path in migration 20260822_17 is not dead code.

    Drops the index, plants the duplicate the index exists to prevent, and runs
    the migration's OWN detection query against it — then restores. Without this
    the failure branch would only ever be exercised by an actual outage, which
    is the worst moment to discover it never worked.

    Runs as the owning role: dropping and recreating an index is a privilege
    ``ittu_app`` does not (and should not) have.
    """
    agency = _fresh_agency()
    engine = create_async_engine(owner_uri)
    try:
        async with engine.begin() as conn:
            await conn.execute(sa.text(f"DROP INDEX core.{INDEX_NAME}"))
        try:
            async with engine.begin() as conn:
                for _ in range(2):  # same (agency, seq) twice — a forked chain
                    await conn.execute(
                        sa.text(
                            "INSERT INTO core.audit_log (id, agency_id, action, seq) "
                            "VALUES (gen_random_uuid(), :a, 'case.created', 1)"
                        ),
                        {"a": agency},
                    )
            async with engine.connect() as conn:
                found = (await conn.execute(sa.text(_DUPLICATES))).fetchall()
            assert any(str(r[0]) == agency and r[1] == 1 and r[2] == 2 for r in found), (
                f"the migration's duplicate check missed a planted fork; it saw {found}"
            )

            # And the index genuinely refuses to be created over it.
            with pytest.raises(Exception) as caught:
                async with engine.begin() as conn:
                    await conn.execute(
                        sa.text(
                            f"CREATE UNIQUE INDEX {INDEX_NAME} "
                            "ON core.audit_log (agency_id, seq)"
                        )
                    )
            assert "unique" in str(caught.value).lower(), (
                f"expected a uniqueness failure, got {caught.value}"
            )
        finally:
            async with engine.begin() as conn:
                await conn.execute(
                    sa.text("DELETE FROM core.audit_log WHERE agency_id = :a"), {"a": agency}
                )
                await conn.execute(
                    sa.text(
                        f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} "
                        "ON core.audit_log (agency_id, seq)"
                    )
                )
    finally:
        await engine.dispose()


async def test_null_seq_rows_are_not_blocked_by_the_unique_index(pg_audit):
    """`seq` is nullable and the index must leave NULLs alone (Postgres treats
    them as distinct). Two unsequenced rows for one agency must both insert —
    otherwise the guard would reject data the column still permits."""
    engine, _maker = pg_audit
    agency = _fresh_agency()

    async with engine.begin() as conn:
        await conn.execute(
            sa.text("SELECT set_config('app.current_agency', :v, true)"), {"v": agency}
        )
        for _ in range(2):
            await conn.execute(
                sa.text(
                    "INSERT INTO core.audit_log (id, agency_id, action) "
                    "VALUES (gen_random_uuid(), :a, 'case.created')"
                ),
                {"a": agency},
            )
        n = (
            await conn.execute(
                sa.text("SELECT count(*) FROM core.audit_log WHERE agency_id = :a"),
                {"a": agency},
            )
        ).scalar()
    assert n == 2, f"NULL-seq rows were blocked by the unique index (saw {n})"
