"""POC/LIVE evidentiary isolation, proven against a REAL Postgres.

``data_mode`` sat on 24 tables for the whole project doing nothing: written on
every insert, read by no query and no policy. Migration ``20260823_18`` makes it
an RLS predicate, so a query that forgets to filter cannot leak. These tests are
the proof that it actually bites — asserted through the non-owning ``ittu_app``
role, because a table owner bypasses RLS and would make every one of them pass
while proving nothing.

Same ephemeral in-process pgserver harness as ``test_rls_isolation.py`` (no
Docker): the full Alembic chain, then ``ittu_app`` from the real deploy script.
Skips cleanly if pgserver is unavailable — a skip here proves nothing, so it
says so rather than counting as a pass.

The most important test in this file is
``test_rows_written_before_the_migration_are_still_readable``: it seeds rows at
the PRE-mode migration head, runs the upgrade, and asserts nothing vanished. An
isolation change that silently hides existing evidence would be far worse than
the leak it fixes.
"""

import os
import tempfile
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Ephemeral, throwaway DB only — never a real credential.
APP_ROLE_PASSWORD = "ittu-test-role-pw-mode"  # noqa: S105

# Real seeded agency ids (migration 20260708_05), same as test_rls_isolation.
AGENCY_A = "a190a9ca-d827-5c3a-a625-b788d9ab03c9"  # Bareskrim Polri
AGENCY_B = "84cb96f6-6dfb-5e5f-9fbd-d06ce68e7772"  # PPATK

# The revision immediately BEFORE mode isolation — the "existing deployment"
# state that the upgrade must not destroy.
PRE_MODE_REVISION = "20260822_17"


def _alembic_cfg():
    from alembic.config import Config

    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    return cfg


@pytest.fixture(scope="session")
def pg_cluster():
    """Ephemeral in-process Postgres, held alive for the whole session.

    Session-scoped deliberately: the pgserver process is tied to this handle's
    lifetime, so a function-scoped fixture would tear the server down between
    tests (the gotcha recorded in test_rls_isolation.py).
    """
    pgserver = pytest.importorskip("pgserver", reason="pgserver (dev extra) not installed")

    pgdata = tempfile.mkdtemp(prefix="ittu-pgdata-mode-")
    try:
        srv = pgserver.get_server(pgdata, cleanup_mode="delete")
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"pgserver could not start a Postgres instance here: {exc}")

    yield srv
    srv.cleanup()


@pytest.fixture(scope="session")
def legacy_rows_then_upgraded(pg_cluster):
    """Migrate to the PRE-mode head, seed rows, THEN upgrade to head.

    This ordering is the whole point: seeding after the upgrade would prove only
    that new rows work. Real deployments have rows written before mode isolation
    existed, all carrying the ``data_mode='poc'`` column default, and those must
    survive. Returns ``(owner_async_uri, app_async_uri)``.
    """
    import alembic.command

    from app.core.config import get_settings

    owner_uri = pg_cluster.get_uri()
    owner_async_uri = owner_uri.replace("postgresql://", "postgresql+asyncpg://", 1)

    prior = {
        k: os.environ.get(k) for k in ("ITTU_DATABASE_URL", "ITTU_MIGRATION_DATABASE_URL")
    }
    os.environ["ITTU_DATABASE_URL"] = owner_async_uri
    # env.py prefers the migration URL — a developer .env may point it at a real
    # database, which would send alembic THERE. Pin it to this cluster.
    os.environ["ITTU_MIGRATION_DATABASE_URL"] = owner_async_uri
    get_settings.cache_clear()
    try:
        cfg = _alembic_cfg()
        # 1. the world as it was, before mode isolation
        alembic.command.upgrade(cfg, PRE_MODE_REVISION)
        _seed_legacy_rows_sync(pg_cluster)
        # 2. the change under test
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
    return owner_async_uri, f"postgresql+asyncpg://ittu_app:{APP_ROLE_PASSWORD}@{host_part}"


def _seed_legacy_rows_sync(pg_cluster) -> None:
    """Rows as a pre-mode deployment would have left them: no explicit data_mode,
    so every one takes the column's 'poc' server_default. Plus a hash-chained
    audit trail, which is what the audit exemption test needs."""
    pg_cluster.psql(
        f"""
        INSERT INTO core.cases (id, agency_id, title, status, stage)
        VALUES ('{uuid.uuid4()}', '{AGENCY_A}', 'legacy case (pre-mode)', 'open', 'intake');
        INSERT INTO intel.scam_sessions (id, public_id, agency_id, channel_type)
        VALUES ('{uuid.uuid4()}', 'sess_legacy_pre_mode', '{AGENCY_A}', 'text');
        """
    )


async def _rows(app_uri: str, sql: str, *, agency: str | None = AGENCY_A,
                mode: str | None = None) -> list:
    """Run ``sql`` as ``ittu_app`` with the given RLS context. ``mode=None``
    leaves ``app.data_mode`` unset — the fail-closed case."""
    engine = create_async_engine(app_uri)
    try:
        async with engine.connect() as conn, conn.begin():
            if agency is not None:
                await conn.execute(
                    sa.text("SELECT set_config('app.current_agency', :v, true)"),
                    {"v": agency},
                )
            if mode is not None:
                await conn.execute(
                    sa.text("SELECT set_config('app.data_mode', :v, true)"), {"v": mode}
                )
            return (await conn.execute(sa.text(sql))).fetchall()
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def seeded_both_modes(legacy_rows_then_upgraded, pg_cluster):
    """One POC and one LIVE case for agency A, inserted as the OWNING role
    (fixture setup bypasses RLS on purpose — it is not the thing under test)."""
    poc_id, live_id = uuid.uuid4(), uuid.uuid4()
    pg_cluster.psql(
        f"""
        INSERT INTO core.cases (id, agency_id, title, status, stage, data_mode)
        VALUES ('{poc_id}',  '{AGENCY_A}', 'poc case',  'open', 'intake', 'poc'),
               ('{live_id}', '{AGENCY_A}', 'live case', 'open', 'intake', 'live');
        """
    )
    return {"poc": str(poc_id), "live": str(live_id)}


# --------------------------------------------------------------------------- #
# 1. The isolation itself
# --------------------------------------------------------------------------- #


async def test_live_session_cannot_see_poc_rows(legacy_rows_then_upgraded, seeded_both_modes):
    """THE proof: as ittu_app with app.data_mode='live', a SELECT over core.cases
    returns the LIVE row and NOT the POC one sitting in the same table for the
    same agency. Postgres is enforcing this, not application filtering."""
    _owner, app_uri = legacy_rows_then_upgraded
    rows = await _rows(app_uri, "SELECT id, data_mode FROM core.cases", mode="live")

    modes = {r[1] for r in rows}
    assert modes == {"live"}, f"a LIVE session saw non-live rows: {modes}"
    assert seeded_both_modes["live"] in {str(r[0]) for r in rows}
    assert seeded_both_modes["poc"] not in {str(r[0]) for r in rows}


async def test_poc_session_cannot_see_live_rows(legacy_rows_then_upgraded, seeded_both_modes):
    """The mirror. Both directions matter: demo data must not enter a real case,
    and real evidence must not surface in a demo."""
    _owner, app_uri = legacy_rows_then_upgraded
    rows = await _rows(app_uri, "SELECT id, data_mode FROM core.cases", mode="poc")

    modes = {r[1] for r in rows}
    assert modes == {"poc"}, f"a POC session saw non-poc rows: {modes}"
    assert seeded_both_modes["poc"] in {str(r[0]) for r in rows}
    assert seeded_both_modes["live"] not in {str(r[0]) for r in rows}


async def test_mode_fails_closed_when_unset(legacy_rows_then_upgraded, seeded_both_modes):
    """A transaction that sets an agency but never sets app.data_mode sees
    NOTHING — fail closed, never fail open. The mode twin of
    test_rls_isolation.py::test_rls_fails_closed_on_null_agency.

    ``core.current_mode()`` returns NULL when unset and ``data_mode = NULL`` is
    never true, so the policy denies. Verified rather than assumed: this is the
    property the whole design rests on.
    """
    _owner, app_uri = legacy_rows_then_upgraded
    rows = await _rows(app_uri, "SELECT id FROM core.cases", mode=None)
    assert rows == [], f"unset app.data_mode admitted {len(rows)} rows — FAIL OPEN"


async def test_garbage_mode_also_fails_closed(legacy_rows_then_upgraded, seeded_both_modes):
    """A typo'd mode shows nothing rather than everything. Settings' Literal
    should make this unreachable from the app, but the policy must not depend on
    the application having validated its input."""
    _owner, app_uri = legacy_rows_then_upgraded
    rows = await _rows(app_uri, "SELECT id FROM core.cases", mode="Live")  # wrong case
    assert rows == [], "a bogus app.data_mode admitted rows — FAIL OPEN"


# --------------------------------------------------------------------------- #
# 2. The write side — a contract, because it is load-bearing and invisible
# --------------------------------------------------------------------------- #


async def test_mismatched_insert_is_refused_not_silently_hidden(legacy_rows_then_upgraded):
    """A LIVE session inserting a 'poc' row is REFUSED, not written-and-hidden.

    This works because Postgres applies a policy's USING expression as the
    implicit WITH CHECK for INSERT. That behaviour is load-bearing for us: it
    turns a mis-stamped write into a loud error instead of a row invisible to
    its own writer, which would look exactly like data loss.

    **If this test fails, look for a policy that was given an explicit
    permissive WITH CHECK** — that silently removes the protection while every
    read-side test here keeps passing.
    """
    _owner, app_uri = legacy_rows_then_upgraded
    engine = create_async_engine(app_uri)
    try:
        async with engine.connect() as conn, conn.begin():
            await conn.execute(
                sa.text("SELECT set_config('app.current_agency', :v, true)"), {"v": AGENCY_A}
            )
            await conn.execute(
                sa.text("SELECT set_config('app.data_mode', 'live', true)")
            )
            with pytest.raises(Exception, match="row-level security"):
                await conn.execute(
                    sa.text(
                        "INSERT INTO core.cases (id, agency_id, title, status, stage, data_mode) "
                        "VALUES (gen_random_uuid(), :a, 'smuggled', 'open', 'intake', 'poc')"
                    ),
                    {"a": AGENCY_A},
                )
    finally:
        await engine.dispose()


# --------------------------------------------------------------------------- #
# 3. Nothing that already existed may disappear  <- the one that matters most
# --------------------------------------------------------------------------- #


async def test_rows_written_before_the_migration_are_still_readable(
    legacy_rows_then_upgraded,
):
    """Rows seeded at revision 20260822_17 — BEFORE mode isolation — are still
    readable after the upgrade.

    Existing rows carry ``data_mode='poc'`` from the column's server_default, so
    a POC deployment (the only kind that exists today) still sees all of them.
    Seeded before the upgrade rather than after, because that is the only way to
    test the actual migration path a real deployment takes.

    If this fails, the migration is destroying visibility of existing evidence —
    stop and fix that before anything else in this file.
    """
    _owner, app_uri = legacy_rows_then_upgraded

    cases = await _rows(
        app_uri,
        "SELECT title FROM core.cases WHERE title = 'legacy case (pre-mode)'",
        mode="poc",
    )
    assert len(cases) == 1, "a case written before the migration vanished after it"

    sessions = await _rows(
        app_uri,
        "SELECT public_id FROM intel.scam_sessions WHERE public_id = 'sess_legacy_pre_mode'",
        mode="poc",
    )
    assert len(sessions) == 1, "a scam_session written before the migration vanished after it"


# --------------------------------------------------------------------------- #
# 4. core.audit_log is DELIBERATELY exempt — this test defends the exemption
# --------------------------------------------------------------------------- #

_AUDIT_WHY = (
    "core.audit_log must NOT have a mode RLS predicate.\n"
    "verify_chain() reads every row for the agency in seq order and walks "
    "prev_sha256, so hiding ANY entry breaks the linkage. Measured over a chain "
    "of poc,poc,live,live:\n"
    "    unfiltered        -> (True, None)\n"
    "    LIVE, poc hidden  -> (False, 3)   FALSE TAMPER ALARM\n"
    "    POC, live hidden  -> (True, None) SILENT TRUNCATION\n"
    "The second is the dangerous one: truncating the tail of a hash chain is "
    "undetectable — the trail verifies clean while records are missing.\n"
    "Mode provenance lives in the hashed detail blob instead "
    "(detail->>'_data_mode'). See app/core/audit.py's module docstring."
)


async def test_audit_log_is_visible_in_both_modes(legacy_rows_then_upgraded, pg_cluster):
    """Audit entries are readable regardless of the session's mode.

    Someone will eventually notice audit_log has no mode predicate and add the
    "missing" one. This is what stops them, and _AUDIT_WHY explains why from the
    failure itself rather than making them rediscover it.
    """
    _owner, app_uri = legacy_rows_then_upgraded
    pg_cluster.psql(
        f"""
        INSERT INTO core.audit_log (id, agency_id, action, seq, sha256, prev_sha256, detail)
        VALUES ('{uuid.uuid4()}', '{AGENCY_A}', 'case.created', 9001,
                '\\x00'::bytea, '\\x00'::bytea, '{{"_data_mode":"poc"}}'::jsonb),
               ('{uuid.uuid4()}', '{AGENCY_A}', 'case.created', 9002,
                '\\x00'::bytea, '\\x00'::bytea, '{{"_data_mode":"live"}}'::jsonb);
        """
    )

    for mode in ("poc", "live"):
        rows = await _rows(
            app_uri,
            "SELECT seq FROM core.audit_log WHERE seq IN (9001, 9002) ORDER BY seq",
            mode=mode,
        )
        seqs = [r[0] for r in rows]
        assert seqs == [9001, 9002], (
            f"a {mode.upper()} session saw only {seqs} of the audit trail.\n\n{_AUDIT_WHY}"
        )


async def test_audit_chain_still_verifies_after_the_migration(legacy_rows_then_upgraded):
    """A real hash-chained trail spanning both modes verifies clean end to end.

    Writes through the REAL PostgresAuditRepository (not hand-built rows) so the
    chain is linked exactly as production links it, then reads it back through
    the non-owning role and verifies. A mode predicate on audit_log would make
    this return (False, <seq>) — which is the whole reason the exemption exists.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.audit import PostgresAuditRepository

    _owner, app_uri = legacy_rows_then_upgraded
    engine = create_async_engine(app_uri)
    agency = AGENCY_B  # its own chain, untouched by the fixtures above
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        for mode in ("poc", "poc", "live", "live"):
            async with maker() as session, session.begin():
                for var, val in (
                    ("app.current_agency", agency),
                    ("app.data_mode", mode),
                ):
                    await session.execute(
                        sa.text("SELECT set_config(:v, :x, true)"), {"v": var, "x": val}
                    )
                # _stamp_mode() stamps get_settings().mode, which is not
                # necessarily `mode` here — pass it explicitly so the row really
                # does carry the mode this loop intends.
                await PostgresAuditRepository(session).record(
                    agency_id=agency, action="case.created", detail={"_data_mode": mode},
                )

        async with maker() as session, session.begin():
            for var, val in (("app.current_agency", agency), ("app.data_mode", "live")):
                await session.execute(
                    sa.text("SELECT set_config(:v, :x, true)"), {"v": var, "x": val}
                )
            repo = PostgresAuditRepository(session)
            entries = await repo.list_entries(agency_id=agency, limit=100)
            ok, broken_at = await repo.verify_chain(agency_id=agency)
    finally:
        await engine.dispose()

    # Guards the guard: verify_chain returns (True, None) for an EMPTY chain, so
    # without this the test would pass just as happily if the LIVE session could
    # see nothing at all — the exact failure it exists to catch.
    assert len(entries) == 4, (
        f"expected all 4 entries (2 poc + 2 live) visible to a LIVE session, got "
        f"{len(entries)} — the trail is being mode-filtered.\n\n{_AUDIT_WHY}"
    )
    assert {e.detail.get("_data_mode") for e in entries} == {"poc", "live"}

    assert (ok, broken_at) == (True, None), (
        f"the audit chain verified as BROKEN at seq {broken_at} when read in LIVE "
        f"mode — entries are being hidden from the walker.\n\n{_AUDIT_WHY}"
    )


# --------------------------------------------------------------------------- #
# 5. The join table inherits its parent's mode
# --------------------------------------------------------------------------- #


async def test_syndicate_members_inherit_the_parent_syndicates_mode(
    legacy_rows_then_upgraded, pg_cluster
):
    """intel.syndicate_members has no data_mode of its own — it is policed
    through its syndicate, so a member of a POC syndicate is invisible in LIVE.

    Deliberately parent-derived rather than given its own column: a join table
    has no independent mode, and a second source of truth could drift from the
    parent (and, with no write path in the app today, would sit at its 'poc'
    default forever — invisible in LIVE even when its syndicate is live).
    """
    poc_syn, live_syn = uuid.uuid4(), uuid.uuid4()
    poc_ent, live_ent = uuid.uuid4(), uuid.uuid4()
    # entity_id is a real FK to intel.entities, so the members need real parents
    # on both sides — a bare uuid would fail the constraint, not the policy.
    pg_cluster.psql(
        f"""
        INSERT INTO intel.syndicates (id, public_id, agency_id, label, data_mode)
        VALUES ('{poc_syn}',  'syn_mode_poc',  '{AGENCY_A}', 'poc syndicate',  'poc'),
               ('{live_syn}', 'syn_mode_live', '{AGENCY_A}', 'live syndicate', 'live');
        INSERT INTO intel.entities (id, public_id, agency_id, type, value, method, data_mode)
        VALUES ('{poc_ent}',  'ent_mode_poc',  '{AGENCY_A}', 'phone', '+62811000001',
                'regex', 'poc'),
               ('{live_ent}', 'ent_mode_live', '{AGENCY_A}', 'phone', '+62811000002',
                'regex', 'live');
        INSERT INTO intel.syndicate_members (syndicate_id, entity_id)
        VALUES ('{poc_syn}', '{poc_ent}'), ('{live_syn}', '{live_ent}');
        """
    )
    _owner, app_uri = legacy_rows_then_upgraded

    live_rows = await _rows(
        app_uri,
        f"SELECT syndicate_id FROM intel.syndicate_members "
        f"WHERE syndicate_id IN ('{poc_syn}', '{live_syn}')",
        mode="live",
    )
    assert [str(r[0]) for r in live_rows] == [str(live_syn)]

    poc_rows = await _rows(
        app_uri,
        f"SELECT syndicate_id FROM intel.syndicate_members "
        f"WHERE syndicate_id IN ('{poc_syn}', '{live_syn}')",
        mode="poc",
    )
    assert [str(r[0]) for r in poc_rows] == [str(poc_syn)]


# --------------------------------------------------------------------------- #
# 6. The worker bypasses RLS entirely — so it must check mode itself
# --------------------------------------------------------------------------- #


async def test_worker_refuses_a_notification_from_the_other_mode(
    legacy_rows_then_upgraded, pg_cluster, monkeypatch
):
    """The delivery actor runs as the OWNING role, which bypasses the mode
    predicate as surely as it bypasses the agency one. Nothing but an explicit
    check stops a POC notification being POSTed to a real agency's webhook.

    Asserted against a real database rather than a mock because the whole point
    is that RLS is NOT protecting this path — a mocked session would hide the
    very condition under test.
    """
    import app.core.db as core_db
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.core.config import get_settings
    from app.uncover.notifications import _deliver_one

    owner_uri, _app_uri = legacy_rows_then_upgraded
    public_id = f"ntf_mode_{uuid.uuid4().hex[:8]}"
    case_id = uuid.uuid4()
    bundle_id = uuid.uuid4()
    # notifications.bundle_id is NOT NULL, so the row needs a real parent bundle.
    pg_cluster.psql(
        f"""
        INSERT INTO core.cases (id, agency_id, title, status, stage, data_mode)
        VALUES ('{case_id}', '{AGENCY_A}', 'worker mode case', 'open', 'intake', 'poc');
        INSERT INTO action.action_bundles
            (id, public_id, case_id, agency_id, status, crime_type, data_mode)
        VALUES ('{bundle_id}', 'act_mode_{bundle_id.hex[:8]}', '{case_id}', '{AGENCY_A}',
                'draft', 'investment', 'poc');
        INSERT INTO action.notifications
            (id, public_id, bundle_id, agency_id, case_id, target_agency, agency_type,
             channel, status, data_mode, attempt_count)
        VALUES ('{uuid.uuid4()}', '{public_id}', '{bundle_id}', '{AGENCY_A}', '{case_id}',
                'Bank BCA', 'bank', 'webhook', 'queued', 'poc', 0);
        """
    )

    settings = get_settings()
    prior_mode = settings.mode
    settings.mode = "live"  # a LIVE deployment handed a POC row

    engine = create_async_engine(owner_uri)
    prior_override = core_db._worker_sessionmaker_override
    core_db._worker_sessionmaker_override = async_sessionmaker(engine, expire_on_commit=False)

    def _explode(*a, **kw):  # pragma: no cover - must never be reached
        raise AssertionError("the worker DISPATCHED a cross-mode notification")

    monkeypatch.setattr("app.uncover.notifications.deliver_webhook", _explode)
    try:
        await _deliver_one(public_id)

        async with engine.connect() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT status, last_error FROM action.notifications "
                        "WHERE public_id = :p"
                    ),
                    {"p": public_id},
                )
            ).one()
    finally:
        core_db._worker_sessionmaker_override = prior_override
        settings.mode = prior_mode
        await engine.dispose()

    # Settled `failed`, not left queued: a row that can never legitimately be
    # sent from this deployment must not be retried forever.
    assert row[0] == "failed", f"expected the row settled 'failed', got {row[0]!r}"
    assert "mode mismatch" in (row[1] or ""), row[1]
