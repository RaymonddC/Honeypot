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
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

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
    prior_mig = os.environ.get("ITTU_MIGRATION_DATABASE_URL")
    os.environ["ITTU_DATABASE_URL"] = owner_async_uri
    # env.py prefers ITTU_MIGRATION_DATABASE_URL — a developer .env may point it at
    # a real Neon owner URL, which would send alembic THERE instead of this
    # ephemeral cluster. Pin it here so migrations run against the pgserver.
    os.environ["ITTU_MIGRATION_DATABASE_URL"] = owner_async_uri
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
        if prior_mig is None:
            os.environ.pop("ITTU_MIGRATION_DATABASE_URL", None)
        else:
            os.environ["ITTU_MIGRATION_DATABASE_URL"] = prior_mig
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
                        "INSERT INTO intel.scam_sessions (id, public_id, agency_id, channel_type) "
                        "VALUES (gen_random_uuid(), :public_id, :agency_id, 'text')"
                    ),
                    # public_id (migration 20260716_07): NOT NULL + UNIQUE now that
                    # P-2b's Postgres repo looks sessions up by the app-issued id,
                    # not the surrogate uuid PK. Any distinct value works here —
                    # this fixture only asserts on agency_id.
                    {"public_id": f"sess_rls_test_{agency_id}", "agency_id": agency_id},
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
            # Mode is an RLS predicate too since migration 20260823_18, and these
            # fixtures seed at the 'poc' column default. Without it the policy
            # fails CLOSED and this reads an empty table — which would look like
            # agency isolation working perfectly while proving nothing.
            await conn.execute(sa.text("SELECT set_config('app.data_mode', 'poc', true)"))
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


# --------------------------------------------------------------------------- #
# honeypot.dial_attempts — the call log, policed two joins out
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
async def seeded_attempts(app_role_uri):
    """A campaign → target → attempt chain for agency A and for agency B.

    Inserted as the OWNING role (setup, not the assertion). The attempt rows
    carry no agency_id of their own — reaching the right one is exactly what the
    policy's attempt → target → campaign join has to get right.
    """
    owner_async_uri, _app = app_role_uri
    engine = create_async_engine(owner_async_uri)
    try:
        async with engine.begin() as conn:
            for agency_id in (AGENCY_A, AGENCY_B):
                camp, target = uuid.uuid4(), uuid.uuid4()
                await conn.execute(
                    sa.text(
                        "INSERT INTO honeypot.dial_campaigns "
                        "(id, public_id, agency_id, name, status, pacing_per_minute) "
                        "VALUES (:id, :pid, :ag, 'rls test', 'running', 6)"
                    ),
                    {"id": camp, "pid": f"camp_rls_{agency_id[:8]}", "ag": agency_id},
                )
                await conn.execute(
                    sa.text(
                        "INSERT INTO honeypot.dial_targets "
                        "(id, campaign_id, phone_number, status, attempt_count) "
                        "VALUES (:id, :cid, :num, 'no_answer', 1)"
                    ),
                    {"id": target, "cid": camp, "num": f"+62811{agency_id[:7]}"},
                )
                await conn.execute(
                    sa.text(
                        "INSERT INTO honeypot.dial_attempts "
                        "(id, target_id, attempt_no, outcome) "
                        "VALUES (gen_random_uuid(), :tid, 1, 'no_answer')"
                    ),
                    {"tid": target},
                )
    finally:
        await engine.dispose()


async def test_rls_isolates_dial_attempts_by_agency(app_role_uri, seeded_attempts):
    """Agency A sees only its own call log.

    dial_attempts has no agency_id — ownership is two joins away (attempt →
    target → campaign). An un-policied table here would expose who every other
    agency has been calling and when, which is arguably more sensitive than the
    target list itself.
    """
    _owner, app_async_uri = app_role_uri
    engine = create_async_engine(app_async_uri)
    try:
        async with engine.connect() as conn, conn.begin():
            await conn.execute(
                sa.text("SELECT set_config('app.current_agency', :v, true)"),
                {"v": AGENCY_A},
            )
            await conn.execute(sa.text("SELECT set_config('app.data_mode', 'poc', true)"))
            seen = (
                await conn.execute(
                    sa.text(
                        "SELECT c.agency_id FROM honeypot.dial_attempts a "
                        "JOIN honeypot.dial_targets t ON t.id = a.target_id "
                        "JOIN honeypot.dial_campaigns c ON c.id = t.campaign_id"
                    )
                )
            ).fetchall()
            count = (
                await conn.execute(sa.text("SELECT count(*) FROM honeypot.dial_attempts"))
            ).scalar()
    finally:
        await engine.dispose()

    assert {str(r[0]) for r in seen} == {AGENCY_A}
    assert count == 1, "agency B's attempt row must be invisible, not merely unjoined"


async def test_dial_attempts_fail_closed_on_null_agency(app_role_uri, seeded_attempts):
    """No tenant context → no call history at all (fail closed, not open)."""
    _owner, app_async_uri = app_role_uri
    engine = create_async_engine(app_async_uri)
    try:
        async with engine.connect() as conn, conn.begin():
            count = (
                await conn.execute(sa.text("SELECT count(*) FROM honeypot.dial_attempts"))
            ).scalar()
    finally:
        await engine.dispose()

    assert count == 0


# --------------------------------------------------------------------------- #
# Triage (phase 6) — the queue is a view over intel.scam_sessions
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
async def seeded_triage(app_role_uri):
    """One unassigned VOICE call per agency — what triage lists."""
    owner_async_uri, _app = app_role_uri
    engine = create_async_engine(owner_async_uri)
    try:
        async with engine.begin() as conn:
            for agency_id in (AGENCY_A, AGENCY_B):
                await conn.execute(
                    sa.text(
                        "INSERT INTO intel.scam_sessions "
                        "(id, public_id, agency_id, case_id, channel_type, channel, "
                        " channel_ref, status, data_mode) "
                        "VALUES (gen_random_uuid(), :pid, :ag, NULL, 'voice', 'pstn', "
                        "        :num, 'closed', 'poc')"
                    ),
                    {
                        "pid": f"sess_triage_{agency_id}",
                        "ag": agency_id,
                        "num": f"+62811{agency_id[:7].replace('-', '')}",
                    },
                )
    finally:
        await engine.dispose()


async def test_triage_repository_isolates_by_agency(app_role_uri, seeded_triage):
    """The real ``PostgresTriageRepository``, run under agency A's tenant
    context, lists only agency A's unplaced calls.

    Asserted through the repository rather than raw SQL because triage is where
    an investigator *assigns evidence to a case file* — leaking another agency's
    call here would not just expose data, it would invite filing it into the
    wrong investigation.
    """
    from app.honeypot_ops.triage import PostgresTriageRepository

    _owner, app_async_uri = app_role_uri
    engine = create_async_engine(app_async_uri)
    try:
        sm = async_sessionmaker(engine, expire_on_commit=False)
        async with sm() as session, session.begin():
            await session.execute(
                sa.text("SELECT set_config('app.current_agency', :v, true)"),
                {"v": AGENCY_A},
            )
            await session.execute(
                sa.text("SELECT set_config('app.data_mode', 'poc', true)")
            )
            rows = await PostgresTriageRepository(
                session, agency_id=uuid.UUID(AGENCY_A)
            ).list_triage()
    finally:
        await engine.dispose()

    assert [r.id for r in rows] == [f"sess_triage_{AGENCY_A}"]


# --------------------------------------------------------------------------- #
# Join tables: no agency_id of their own, policed through their parent.
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
async def seeded_syndicate_members(app_role_uri):
    """A syndicate + entity + membership row for EACH agency, as the owner."""
    owner_async_uri, _ = app_role_uri
    engine = create_async_engine(owner_async_uri)
    ids = {}
    try:
        async with engine.begin() as conn:
            for tag, agency_id in (("a", AGENCY_A), ("b", AGENCY_B)):
                syn = await conn.execute(
                    sa.text(
                        "INSERT INTO intel.syndicates (id, public_id, agency_id, label, data_mode) "
                        "VALUES (gen_random_uuid(), :p, :a, 'rls-test', 'poc') RETURNING id"
                    ),
                    {"p": f"syn_rls_{tag}", "a": agency_id},
                )
                syn_id = syn.scalar_one()
                ent = await conn.execute(
                    sa.text(
                        "INSERT INTO intel.entities "
                        "(id, public_id, agency_id, type, value, method, data_mode) "
                        "VALUES (gen_random_uuid(), :p, :a, 'crypto_wallet', :v, 'regex', 'poc') "
                        "RETURNING id"
                    ),
                    {"p": f"ent_rls_{tag}", "a": agency_id, "v": f"WALLET-{tag}"},
                )
                await conn.execute(
                    sa.text(
                        "INSERT INTO intel.syndicate_members "
                        "(syndicate_id, entity_id, link_type, confidence) "
                        "VALUES (:s, :e, 'shared_wallet', 0.9)"
                    ),
                    {"s": syn_id, "e": ent.scalar_one()},
                )
                ids[tag] = syn_id
    finally:
        await engine.dispose()
    return ids


async def test_rls_isolates_syndicate_members_through_their_syndicate(
    app_role_uri, seeded_syndicate_members
):
    """A join table with no agency_id must still be isolated.

    Regression: an RLS review found agency A was correctly blocked from agency
    B's syndicate AND its entity, yet could read the membership row linking
    them — leaking the shape of another agency's investigation graph (which
    opaque ids cluster, the link type, the confidence, how many links exist).
    The ids are unreadable alone; the structure is still intelligence.
    """
    _owner, app_async_uri = app_role_uri
    engine = create_async_engine(app_async_uri)
    try:
        async with engine.connect() as conn:
            await conn.execute(
                sa.text("SELECT set_config('app.current_agency', :a, false)"),
                {"a": AGENCY_A},
            )
            await conn.execute(sa.text("SELECT set_config('app.data_mode', 'poc', false)"))
            own = (
                await conn.execute(
                    sa.text(
                        "SELECT count(*) FROM intel.syndicate_members WHERE syndicate_id = :s"
                    ),
                    {"s": seeded_syndicate_members["a"]},
                )
            ).scalar_one()
            other = (
                await conn.execute(
                    sa.text(
                        "SELECT count(*) FROM intel.syndicate_members WHERE syndicate_id = :s"
                    ),
                    {"s": seeded_syndicate_members["b"]},
                )
            ).scalar_one()
        assert own == 1, "an agency must still see its OWN membership rows"
        assert other == 0, "must not see another agency's membership rows"
    finally:
        await engine.dispose()


async def test_fiat_correlations_are_policed_through_their_case(app_role_uri):
    """fiat.correlations carries case_id (uuid into agency-scoped core.cases)
    and had no policy. Empty in practice today — which is exactly why it was
    worth fixing before it fills with real crypto↔fiat links."""
    owner_async_uri, app_async_uri = app_role_uri
    owner = create_async_engine(owner_async_uri)
    app = create_async_engine(app_async_uri)
    try:
        async with owner.begin() as conn:
            case_b = (
                await conn.execute(
                    sa.text(
                        "INSERT INTO core.cases (id, agency_id, title, status, stage, data_mode) "
                        "VALUES (gen_random_uuid(), :a, 'B case', 'open', 'intake', 'poc') "
                        "RETURNING id"
                    ),
                    {"a": AGENCY_B},
                )
            ).scalar_one()
            # correlations requires both parents (NOT NULL); those tables hold
            # public chain/fiat data and are deliberately un-policed.
            fiat_tx = (
                await conn.execute(
                    sa.text(
                        "INSERT INTO fiat.fiat_transactions (id, amount, ts, channel) "
                        "VALUES (gen_random_uuid(), 1000, now(), 'transfer') RETURNING id"
                    )
                )
            ).scalar_one()
            crypto_tx = (
                await conn.execute(
                    sa.text(
                        "INSERT INTO chain.transactions "
                        "(id, tx_hash, chain, from_addr, to_addr, value, ts) "
                        "VALUES (gen_random_uuid(), 'rls-test-hash', 'tron', 'A', 'B', 1, now()) "
                        "RETURNING id"
                    )
                )
            ).scalar_one()
            await conn.execute(
                sa.text(
                    "INSERT INTO fiat.correlations "
                    "(id, case_id, fiat_tx_id, crypto_tx_id, time_delta_seconds, amount_match, "
                    "confidence, method, data_mode) "
                    "VALUES (gen_random_uuid(), :c, :f, :x, 30, 1.0, 0.8, 'amount+time', 'poc')"
                ),
                {"c": case_b, "f": fiat_tx, "x": crypto_tx},
            )
        async with app.connect() as conn:
            await conn.execute(
                sa.text("SELECT set_config('app.current_agency', :a, false)"),
                {"a": AGENCY_A},
            )
            await conn.execute(sa.text("SELECT set_config('app.data_mode', 'poc', false)"))
            seen = (
                await conn.execute(
                    sa.text("SELECT count(*) FROM fiat.correlations WHERE case_id = :c"),
                    {"c": case_b},
                )
            ).scalar_one()
        assert seen == 0, "must not see correlations behind another agency's case"
    finally:
        await owner.dispose()
        await app.dispose()
