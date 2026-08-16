"""The outbound dial worker against a real Postgres (phase 4).

The dialer is the one piece that cannot be exercised in memory mode: the actor
runs in another process and loads its target by id, so it needs real rows. Same
ephemeral in-process Postgres harness as the other ``*_pg.py`` suites (pgserver —
no Docker), skipping cleanly when pgserver isn't available.

What matters here, in order of importance:

1. **The call log is one-to-many** — a requeued target dialed twice leaves TWO
   ``intel.scam_sessions`` rows pointing at it. This is the behaviour the
   ``dial_targets.session_id`` column was dropped for (migration 20260816_14);
   a single FK could not express it.
2. **POC never dials and LIVE never pretends** — a ``live`` row raises rather
   than silently simulating, matching every other LIVE boundary in the codebase.
3. The durable status machine: attempt counting, retry budget, and the
   deliberate difference between ``no_answer`` (settles — Requeue is the way to
   try again) and ``failed`` (retries within budget).
"""

import asyncio
import contextlib
import os
import tempfile
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.honeypot_ops.dialer import DialAttemptError, _dial_one, simulate_outcome

BACKEND_DIR = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- #
# Harness
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def owner_uri():
    """Ephemeral Postgres migrated to head; yields the owner async URI.

    The dialer connects as the owning role by design (see
    ``get_worker_sessionmaker``): a system actor is handed a row id and must read
    it to learn the owning agency, which it cannot do under RLS.
    """
    pgserver = pytest.importorskip("pgserver", reason="pgserver (dev extra) not installed")
    import alembic.command
    from alembic.config import Config

    from app.core.config import get_settings

    pgdata = tempfile.mkdtemp(prefix="ittu-pgdata-dialer-")
    try:
        srv = pgserver.get_server(pgdata, cleanup_mode="delete")
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"pgserver could not start a Postgres instance here: {exc}")

    uri = srv.get_uri().replace("postgresql://", "postgresql+asyncpg://", 1)
    prior_db = os.environ.get("ITTU_DATABASE_URL")
    prior_mig = os.environ.get("ITTU_MIGRATION_DATABASE_URL")
    # Pin both: a developer .env points at a real database, and migrations must
    # land on THIS cluster.
    os.environ["ITTU_DATABASE_URL"] = uri
    os.environ["ITTU_MIGRATION_DATABASE_URL"] = uri
    get_settings.cache_clear()
    try:
        cfg = Config(str(BACKEND_DIR / "alembic.ini"))
        cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
        alembic.command.upgrade(cfg, "head")
        yield uri
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


@contextlib.asynccontextmanager
async def _worker(uri: str):
    """Point the actor's cached sessionmaker at the test cluster, for one loop.

    The engine MUST be created inside the same event loop that later awaits it —
    asyncpg binds connections to their creating loop, so a module-scoped engine
    plus per-test ``asyncio.run()`` (a fresh loop each time) blows up with
    "attached to a different loop". Hence: one ``asyncio.run`` per test, engine
    built within it.

    Patching the cache directly (rather than juggling env vars) keeps the actor
    on exactly the code path production uses — only the URL differs.
    """
    import app.core.db as core_db

    engine = create_async_engine(uri)
    prior = core_db._worker_sessionmaker
    core_db._worker_sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield engine
    finally:
        core_db._worker_sessionmaker = prior
        await engine.dispose()


def run_scenario(coro_fn):
    """Run one async test body in a single fresh event loop."""
    return asyncio.run(coro_fn())


def _find_number(outcomes: list[str], nth: int = 0) -> str:
    """A phone number whose first N simulated attempts match ``outcomes``.

    The simulation is a pure function of (number, attempt), so tests assert exact
    behaviour without mocking randomness — but the mapping is an implementation
    detail. Searching for a number with the shape a test needs keeps these tests
    honest if the distribution is ever retuned.

    ``nth`` skips to a later match. The Postgres fixture is module-scoped, so
    every test in this file shares one database: two tests asking for "an
    engaged number" would otherwise get the SAME number, and case-linking (§5)
    deliberately matches on exactly that — one test's leftover session would
    silently satisfy the next test's link.
    """
    found = 0
    for i in range(100_000):
        candidate = f"+628{i:010d}"
        if all(
            simulate_outcome(candidate, n + 1)[0] == want
            for n, want in enumerate(outcomes)
        ):
            if found == nth:
                return candidate
            found += 1
    raise AssertionError(f"no number produces {outcomes} (nth={nth})")  # pragma: no cover


async def _seed(engine, *, number: str, data_mode: str = "poc",
                campaign_status: str = "running", case_id=None) -> uuid.UUID:
    """Insert a running campaign + one queued target; return the target id."""
    from app.core.auth import find_agency

    agency_id = find_agency("bareskrim").id
    camp_id, target_id = uuid.uuid4(), uuid.uuid4()
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO honeypot.dial_campaigns "
                "(id, public_id, agency_id, name, case_id, status, pacing_per_minute, data_mode) "
                "VALUES (:id, :pid, :ag, 'dialer test', :case, :st, 6, :dm)"
            ),
            {"id": camp_id, "pid": f"camp_{uuid.uuid4().hex[:12]}", "ag": agency_id,
             "case": case_id, "st": campaign_status, "dm": data_mode},
        )
        await conn.execute(
            sa.text(
                "INSERT INTO honeypot.dial_targets "
                "(id, campaign_id, phone_number, status, attempt_count, data_mode) "
                "VALUES (:id, :cid, :num, 'queued', 0, :dm)"
            ),
            {"id": target_id, "cid": camp_id, "num": number, "dm": data_mode},
        )
    return target_id


async def _target(engine, target_id) -> sa.Row:
    async with engine.connect() as conn:
        return (
            await conn.execute(
                sa.text(
                    "SELECT status, attempt_count, last_error "
                    "FROM honeypot.dial_targets WHERE id = :id"
                ),
                {"id": target_id},
            )
        ).one()


async def _sessions(engine, target_id) -> list[sa.Row]:
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT public_id, disposition, duration_seconds, channel_type, "
                        "channel, channel_ref, status, recording_url, case_id "
                        "FROM intel.scam_sessions WHERE dial_target_id = :id "
                        "ORDER BY started_at"
                    ),
                    {"id": target_id},
                )
            ).all()
        )


async def _attempts(engine, target_id) -> list[sa.Row]:
    """The call log (CDR) for a target, oldest attempt first."""
    async with engine.connect() as conn:
        return list(
            (
                await conn.execute(
                    sa.text(
                        "SELECT attempt_no, outcome, error, duration_seconds, "
                        "session_id, data_mode, started_at "
                        "FROM honeypot.dial_attempts WHERE target_id = :id "
                        "ORDER BY attempt_no"
                    ),
                    {"id": target_id},
                )
            ).all()
        )


async def _requeue(engine, target_id) -> None:
    """What POST /requeue does: status back to queued, attempt_count untouched."""
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "UPDATE honeypot.dial_targets SET status='queued', last_error=NULL "
                "WHERE id = :id"
            ),
            {"id": target_id},
        )


# --------------------------------------------------------------------------- #
# 1. The call log is one-to-many
# --------------------------------------------------------------------------- #


def test_requeued_target_accumulates_one_session_per_attempt(owner_uri):
    """THE phase-4 invariant: dial → requeue → dial leaves two call records.

    A single ``dial_targets.session_id`` could only have named one of them, which
    is why migration 20260816_14 dropped it in favour of this reverse link.
    """
    async def scenario():
        async with _worker(owner_uri) as engine:
            number = _find_number(["engaged", "engaged"])
            target_id = await _seed(engine, number=number)

            await _dial_one(str(target_id))
            assert len(await _sessions(engine, target_id)) == 1
            assert (await _target(engine, target_id)).attempt_count == 1

            await _requeue(engine, target_id)
            await _dial_one(str(target_id))

            both = await _sessions(engine, target_id)
            assert len(both) == 2, "each attempt must leave its own call record"
            assert both[0].public_id != both[1].public_id
            # attempt_count is history and survives the requeue.
            assert (await _target(engine, target_id)).attempt_count == 2

    run_scenario(scenario)


def test_engaged_call_is_logged_as_a_voice_session(owner_uri):
    async def scenario():
        async with _worker(owner_uri) as engine:
            number = _find_number(["engaged"])
            target_id = await _seed(engine, number=number)
            await _dial_one(str(target_id))

            (row,) = await _sessions(engine, target_id)
            assert row.channel_type == "voice"
            assert row.channel == "pstn"
            assert row.channel_ref == number   # the dialed number is itself intel
            assert row.disposition == "engaged"
            assert row.duration_seconds > 0
            assert row.status == "closed"      # the call is over
            assert row.recording_url is None   # recording is deferred (spec §3.7)
            assert row.case_id is None         # no campaign case → triage (phase 6)
            assert (await _target(engine, target_id)).status == "engaged"

    run_scenario(scenario)


def test_campaign_case_id_pre_attaches_the_call(owner_uri):
    """Spec §5 step 1: a campaign pinned to a case skips triage entirely."""
    async def scenario():
        async with _worker(owner_uri) as engine:
            case_id = uuid.uuid4()
            target_id = await _seed(
                engine, number=_find_number(["engaged"]), case_id=case_id
            )
            await _dial_one(str(target_id))

            (row,) = await _sessions(engine, target_id)
            assert row.case_id == case_id

    run_scenario(scenario)


# --------------------------------------------------------------------------- #
# 2. POC never dials, LIVE never pretends
# --------------------------------------------------------------------------- #


def test_live_data_mode_fails_loud_instead_of_simulating(owner_uri):
    """A LIVE row must not be quietly simulated — that would look like a placed
    call. It raises, pointing at phase 5, exactly like every other LIVE stub."""
    async def scenario():
        async with _worker(owner_uri) as engine:
            target_id = await _seed(
                engine, number="+6281234500001", data_mode="live"
            )

            with pytest.raises(NotImplementedError, match="LIVE outbound dialing"):
                await _dial_one(str(target_id))

            # Attempt counted, row left mid-flight — no fabricated outcome.
            row = await _target(engine, target_id)
            assert row.status == "dialing"
            assert row.attempt_count == 1
            assert await _sessions(engine, target_id) == []

    run_scenario(scenario)


def test_poc_dial_touches_no_network(owner_uri, monkeypatch):
    """The POC path must be pure computation. Any outbound HTTP here would mean
    a 'simulated' campaign was really reaching a provider."""
    import httpx

    def _boom(*a, **kw):  # pragma: no cover - only runs if the guard fails
        raise AssertionError("POC dialing attempted a network call")

    monkeypatch.setattr(httpx.AsyncClient, "request", _boom)
    monkeypatch.setattr(httpx.Client, "request", _boom)

    async def scenario():
        async with _worker(owner_uri) as engine:
            target_id = await _seed(engine, number=_find_number(["engaged"]))
            await _dial_one(str(target_id))
            assert (await _target(engine, target_id)).status == "engaged"

    run_scenario(scenario)


# --------------------------------------------------------------------------- #
# 3. The durable status machine
# --------------------------------------------------------------------------- #


def test_no_answer_settles_and_logs_no_session(owner_uri):
    """Nobody picking up is an answer: it settles rather than auto-retrying, and
    creates no session — a no-answer is not a conversation, and the triage queue
    reads sessions."""
    async def scenario():
        async with _worker(owner_uri) as engine:
            target_id = await _seed(engine, number=_find_number(["no_answer"]))
            await _dial_one(str(target_id))

            row = await _target(engine, target_id)
            assert row.status == "no_answer"
            assert row.attempt_count == 1
            assert await _sessions(engine, target_id) == []

    run_scenario(scenario)


def test_failed_dial_requeues_until_the_budget_is_spent(owner_uri):
    """A carrier failure is transient, so it re-queues and raises (→ Dramatiq
    backoff) until ``dial_max_retries``, then settles as failed."""
    from app.core.config import get_settings

    budget = get_settings().dial_max_retries

    async def scenario():
        async with _worker(owner_uri) as engine:
            target_id = await _seed(engine, number=_find_number(["failed"] * budget))

            for attempt in range(1, budget):
                with pytest.raises(DialAttemptError):
                    await _dial_one(str(target_id))
                row = await _target(engine, target_id)
                assert row.status == "queued", "a retryable failure goes back in the queue"
                assert row.attempt_count == attempt
                assert row.last_error

            # Final attempt: budget spent → settle, don't raise.
            await _dial_one(str(target_id))
            row = await _target(engine, target_id)
            assert row.status == "failed"
            assert row.attempt_count == budget
            assert await _sessions(engine, target_id) == []

    run_scenario(scenario)


def test_dial_is_idempotent_on_an_already_settled_target(owner_uri):
    """At-least-once redelivery must not double-dial or double-log."""
    async def scenario():
        async with _worker(owner_uri) as engine:
            target_id = await _seed(engine, number=_find_number(["engaged"]))
            await _dial_one(str(target_id))
            await _dial_one(str(target_id))  # redelivery

            assert len(await _sessions(engine, target_id)) == 1
            assert (await _target(engine, target_id)).attempt_count == 1

    run_scenario(scenario)


def test_paused_campaign_is_not_dialed(owner_uri):
    """Pause must actually stop calls that were already enqueued."""
    async def scenario():
        async with _worker(owner_uri) as engine:
            target_id = await _seed(
                engine, number=_find_number(["engaged"]), campaign_status="paused"
            )
            await _dial_one(str(target_id))

            row = await _target(engine, target_id)
            assert row.status == "queued"   # untouched, still pending
            assert row.attempt_count == 0
            assert await _sessions(engine, target_id) == []

    run_scenario(scenario)


def test_unknown_target_id_is_a_noop(owner_uri):
    async def scenario():
        async with _worker(owner_uri) as engine:  # noqa: F841 - needed for the patch
            await _dial_one(str(uuid.uuid4()))
            await _dial_one("not-a-uuid")

    run_scenario(scenario)


# --------------------------------------------------------------------------- #
# The call log (honeypot.dial_attempts) — EVERY attempt, not just connected ones
# --------------------------------------------------------------------------- #


def test_unanswered_attempt_is_still_logged(owner_uri):
    """The gap this table closes: a no-answer leaves a record.

    Before it existed, an unanswered call vanished into ``attempt_count`` — the
    target said "tried once" and nothing said when, or that nobody picked up.
    """
    async def scenario():
        async with _worker(owner_uri) as engine:
            number = _find_number(["no_answer"])
            target_id = await _seed(engine, number=number)
            await _dial_one(str(target_id))

            (att,) = await _attempts(engine, target_id)
            assert att.attempt_no == 1
            assert att.outcome == "no_answer"
            assert att.session_id is None, "a silent call is not a conversation"
            assert att.started_at is not None

            # ...and it still creates no session, so triage stays a work queue.
            assert await _sessions(engine, target_id) == []

    run_scenario(scenario)


def test_requeue_then_dial_appends_a_second_attempt(owner_uri):
    """THE user-facing invariant: requeue → dial gives 2+ log entries.

    Deliberately uses a no-answer THEN an engaged call, the case the old
    session-only log could not represent at all: the first attempt produced no
    session, so the history would have shown a single entry for two real calls.
    """
    async def scenario():
        async with _worker(owner_uri) as engine:
            number = _find_number(["no_answer", "engaged"])
            target_id = await _seed(engine, number=number)

            await _dial_one(str(target_id))
            await _requeue(engine, target_id)
            await _dial_one(str(target_id))

            log = await _attempts(engine, target_id)
            assert [a.attempt_no for a in log] == [1, 2]
            assert [a.outcome for a in log] == ["no_answer", "engaged"]
            # Only the connected attempt links to a conversation.
            assert log[0].session_id is None
            assert log[1].session_id is not None
            assert log[1].duration_seconds > 0

            # One session for the one call that connected — the split holds.
            assert len(await _sessions(engine, target_id)) == 1

    run_scenario(scenario)


def test_attempt_links_to_the_session_it_produced(owner_uri):
    async def scenario():
        async with _worker(owner_uri) as engine:
            number = _find_number(["engaged"])
            target_id = await _seed(engine, number=number)
            await _dial_one(str(target_id))

            (att,) = await _attempts(engine, target_id)
            async with engine.connect() as conn:
                sid = (
                    await conn.execute(
                        sa.text(
                            "SELECT id FROM intel.scam_sessions WHERE dial_target_id = :t"
                        ),
                        {"t": target_id},
                    )
                ).scalar_one()
            assert att.session_id == sid
            assert att.duration_seconds > 0

    run_scenario(scenario)


def test_failed_attempts_are_each_logged_across_the_retry_budget(owner_uri):
    """A retried failure is still a placed call, so each try earns a row."""
    async def scenario():
        async with _worker(owner_uri) as engine:
            number = _find_number(["failed", "failed", "failed"])
            target_id = await _seed(engine, number=number)

            for _ in range(3):
                with contextlib.suppress(DialAttemptError):
                    await _dial_one(str(target_id))

            log = await _attempts(engine, target_id)
            assert [a.attempt_no for a in log] == [1, 2, 3]
            assert {a.outcome for a in log} == {"failed"}
            assert all(a.error for a in log), "the carrier reason is kept per attempt"
            assert (await _target(engine, target_id)).status == "failed"

    run_scenario(scenario)


def test_attempt_log_carries_the_rows_data_mode(owner_uri):
    """POC attempts must stay flagged as non-evidence (the codebase invariant)."""
    async def scenario():
        async with _worker(owner_uri) as engine:
            number = _find_number(["engaged"])
            target_id = await _seed(engine, number=number, data_mode="poc")
            await _dial_one(str(target_id))
            (att,) = await _attempts(engine, target_id)
            assert att.data_mode == "poc"

    run_scenario(scenario)


# --------------------------------------------------------------------------- #
# 5. Case linking (§5) — exact match only, everything else to triage
# --------------------------------------------------------------------------- #


async def _seed_case_session(engine, *, number: str, case_id, agency_id=None) -> None:
    """An earlier call on ``number`` already filed under ``case_id``."""
    from app.core.auth import find_agency

    if agency_id is None:
        agency_id = find_agency("bareskrim").id
    async with engine.begin() as conn:
        await conn.execute(
            sa.text(
                "INSERT INTO intel.scam_sessions "
                "(id, public_id, agency_id, case_id, channel_type, channel, "
                " channel_ref, status, data_mode) "
                "VALUES (gen_random_uuid(), :pid, :ag, :case, 'voice', 'pstn', "
                "        :num, 'closed', 'poc')"
            ),
            {"pid": f"sess_{uuid.uuid4().hex[:12]}", "ag": agency_id,
             "case": case_id, "num": number},
        )


def test_known_number_links_to_the_case_it_already_belongs_to(owner_uri):
    """§5 step 2: the same number engaged before on a case → same case again.

    This is the everyday link — a requeued target that engages a second time, or
    a scammer who calls back — and it is the reason auto-linking exists at all.
    """
    async def scenario():
        async with _worker(owner_uri) as engine:
            number = _find_number(["engaged"], nth=10)
            case_id = uuid.uuid4()
            await _seed_case_session(engine, number=number, case_id=case_id)

            target_id = await _seed(engine, number=number)  # campaign NOT pinned
            await _dial_one(str(target_id))

            (row,) = await _sessions(engine, target_id)
            assert row.case_id == case_id

    run_scenario(scenario)


def test_unknown_number_goes_to_triage(owner_uri):
    """No pinned case and nothing exact to match on → NULL, i.e. a human decides.

    The counterpart to the test above: matching must not reach for a link it
    cannot prove, because a wrong auto-link silently merges two investigations.
    """
    async def scenario():
        async with _worker(owner_uri) as engine:
            # A case exists, but on a DIFFERENT number.
            await _seed_case_session(
                engine, number=_find_number(["no_answer"], nth=11), case_id=uuid.uuid4()
            )
            target_id = await _seed(engine, number=_find_number(["engaged"], nth=11))
            await _dial_one(str(target_id))

            (row,) = await _sessions(engine, target_id)
            assert row.case_id is None

    run_scenario(scenario)


def test_match_never_crosses_agencies(owner_uri):
    """Another agency's case is not a match, even on an identical number.

    The dialer runs as the owning role (no RLS), so this filter is the only thing
    standing between two agencies' investigations — worth asserting directly.
    """
    async def scenario():
        async with _worker(owner_uri) as engine:
            from app.core.auth import find_agency

            number = _find_number(["engaged"], nth=12)
            await _seed_case_session(
                engine,
                number=number,
                case_id=uuid.uuid4(),
                agency_id=find_agency("ppatk").id,   # a DIFFERENT agency
            )
            target_id = await _seed(engine, number=number)  # campaign is bareskrim
            await _dial_one(str(target_id))

            (row,) = await _sessions(engine, target_id)
            assert row.case_id is None, "a foreign agency's case must not be matched"

    run_scenario(scenario)


def test_shared_wallet_links_to_the_case(owner_uri):
    """§5 step 2, the entity arm: a wallet already on a case links a new call.

    Exercised through ``resolve_case_id`` directly because a *simulated* call
    produces no transcript and therefore no entities — the phase-5 media bridge
    is what will supply them for a real call.
    """
    async def scenario():
        async with _worker(owner_uri) as engine:
            from app.core.auth import find_agency
            from app.honeypot_ops.dialer import resolve_case_id

            agency_id = find_agency("bareskrim").id
            case_id = uuid.uuid4()
            wallet = "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6"
            session_pid = f"sess_{uuid.uuid4().hex[:12]}"

            async with engine.begin() as conn:
                await conn.execute(
                    sa.text(
                        "INSERT INTO intel.scam_sessions "
                        "(id, public_id, agency_id, case_id, channel_type, status, data_mode) "
                        "VALUES (gen_random_uuid(), :pid, :ag, :case, 'voice', 'closed', 'poc')"
                    ),
                    {"pid": session_pid, "ag": agency_id, "case": case_id},
                )
                await conn.execute(
                    sa.text(
                        "INSERT INTO intel.entities "
                        "(id, public_id, session_id, agency_id, type, value, "
                        " normalized_value, method, data_mode) "
                        "SELECT gen_random_uuid(), :epid, s.id, :ag, 'crypto_wallet', "
                        "       :val, :val, 'regex', 'poc' "
                        "FROM intel.scam_sessions s WHERE s.public_id = :pid"
                    ),
                    {"epid": f"ent_{uuid.uuid4().hex[:12]}", "ag": agency_id,
                     "val": wallet, "pid": session_pid},
                )

            sm = async_sessionmaker(engine, expire_on_commit=False)
            async with sm() as session:
                hit = await resolve_case_id(
                    session,
                    campaign_case_id=None,
                    phone="+628000000000",      # a number nobody has seen
                    agency_id=agency_id,
                    entity_values=(wallet,),
                )
                miss = await resolve_case_id(
                    session,
                    campaign_case_id=None,
                    phone="+628000000000",
                    agency_id=agency_id,
                    entity_values=("TSomeOtherWalletEntirely",),
                )

            assert hit == case_id
            assert miss is None

    run_scenario(scenario)
