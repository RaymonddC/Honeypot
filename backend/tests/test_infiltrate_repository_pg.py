"""PostgresInfiltrateRepository — round-trip, stamping, isolation (P-2b,
docs/Persistence-Plan.md P-2).

Same ephemeral, in-process Postgres harness as ``tests/test_rls_isolation.py``
(pgserver — no Docker needed): runs the full Alembic chain (now through
migration ``20260716_07``, the ``public_id`` bridge), creates the non-
superuser ``ittu_app`` role via the real deploy script, and proves the
repository against it — connected AS ``ittu_app`` (never the owning/migration
role), so RLS is actually enforcing, not bypassed.

Repos are built directly (not through FastAPI's ``Depends`` graph — there's
no request/JWT here) over a session opened the same way
``app.core.db.get_tenant_session`` opens one: connect as ``ittu_app``,
``SELECT set_config('app.current_agency', ...)`` for the transaction, then
hand that session + the agency id to ``PostgresInfiltrateRepository`` exactly
as ``get_infiltrate_repository`` would per-request.

Skips cleanly (not a failure) if ``pgserver`` isn't installed or can't start a
Postgres instance here — same as ``test_rls_isolation.py``.
"""

import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.infiltrate import service as svc
from app.infiltrate.custody import MessageChain
from app.infiltrate.repository import PostgresInfiltrateRepository

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Ephemeral, throwaway DB only — never a real credential. Distinct from
# test_rls_isolation.py's password only so the two files read independently.
APP_ROLE_PASSWORD = "ittu-test-role-pw-2"  # noqa: S105

# Real seeded agency ids (migration 20260708_05 / app.core.auth.SEED_AGENCIES) —
# same ones a demo JWT would carry.
AGENCY_A = "a190a9ca-d827-5c3a-a625-b788d9ab03c9"  # Bareskrim Polri
AGENCY_B = "84cb96f6-6dfb-5e5f-9fbd-d06ce68e7772"  # PPATK


@pytest.fixture(scope="session")
def pg_cluster():
    """Ephemeral in-process Postgres, held alive for the whole test session.

    Skips the module cleanly if pgserver isn't installed (it's a `dev` extra,
    not a hard dependency) or can't start a server in this sandbox.
    """
    pgserver = pytest.importorskip("pgserver", reason="pgserver (dev extra) not installed")

    pgdata = tempfile.mkdtemp(prefix="ittu-pgdata-repo-")
    try:
        srv = pgserver.get_server(pgdata, cleanup_mode="delete")
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"pgserver could not start a Postgres instance here: {exc}")

    yield srv
    srv.cleanup()


@pytest.fixture(scope="session")
def app_role_uri(pg_cluster):
    """Run migrations 01→07, create ``ittu_app`` via the real deploy script.

    Returns ``(owner_async_uri, app_async_uri)``. See test_rls_isolation.py
    for why ``get_settings.cache_clear()`` is needed around the migration run.
    """
    import alembic.command
    from alembic.config import Config

    from app.core.config import get_settings

    owner_uri = pg_cluster.get_uri()
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


class _RepoHandle:
    """A repo + its own engine/session, so a test can commit and dispose
    cleanly (mirrors one request's lifetime)."""

    def __init__(self, repo: PostgresInfiltrateRepository, session: AsyncSession, engine) -> None:
        self.repo = repo
        self.session = session
        self._engine = engine

    async def commit(self) -> None:
        await self.session.commit()

    async def close(self) -> None:
        await self.session.close()
        await self._engine.dispose()


async def _open_repo(app_async_uri: str, agency_id: str, *, data_mode: str = "poc") -> _RepoHandle:
    """Build a repo over a fresh RLS-scoped session connected AS ittu_app —
    same shape as app.core.db.get_tenant_session, without FastAPI DI."""
    engine = create_async_engine(app_async_uri)
    session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)()
    await session.execute(
        sa.text("SELECT set_config('app.current_agency', :v, true)"), {"v": agency_id}
    )
    repo = PostgresInfiltrateRepository(session, agency_id=uuid.UUID(agency_id), data_mode=data_mode)
    return _RepoHandle(repo, session, engine)


def _bundle(seed: str, *, channel_ref: str = "+62-test"):
    """One SessionOut + its messages/entity/syndicate — same shape service.py
    assembles in _build_session, hand-built here (real hash chain via the
    actual MessageChain, so custody re-verification has something real to
    check)."""
    session_id = f"sess_{seed}"
    in_id, out_id = f"msg_{seed}_in", f"msg_{seed}_out"
    base_ts = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)

    chain = MessageChain(session_id)
    cm_in = chain.append(
        "inbound", "kirim ke rekening 1234567890 BCA ya pak", base_ts, {"turn": 0}
    )
    cm_out = chain.append(
        "outbound", "baik, saya catat dulu ya", base_ts + timedelta(seconds=1), {"turn": 0}
    )

    entity = svc.EntityOut(
        id=f"ent_{seed}", session_id=session_id, message_id=in_id,
        type="bank_account", value="1234567890", normalized_value="1234567890",
        chain=None, bank_name="BCA", context="rekening 1234567890 BCA",
        method="regex", confidence=0.9, review_status="unverified",
        provenance={"turn": 0, "methods": ["regex"], "validators_passed": ["luhn"]},
        data_mode="poc", created_at=base_ts,
    )
    messages = [
        svc.MessageOut(
            id=in_id, session_id=session_id, seq=cm_in.seq, direction="inbound",
            content=cm_in.content, ts=cm_in.ts, sha256=cm_in.sha256,
            prev_sha256=cm_in.prev_sha256, meta=cm_in.meta, entities=[entity],
        ),
        svc.MessageOut(
            id=out_id, session_id=session_id, seq=cm_out.seq, direction="outbound",
            content=cm_out.content, ts=cm_out.ts, sha256=cm_out.sha256,
            prev_sha256=cm_out.prev_sha256, meta=cm_out.meta, entities=[],
        ),
    ]
    session = svc.SessionOut(
        id=session_id, case_id=None,
        persona=svc.PersonaOut(
            id="per_test", name="Bu Test", age=50, occupation="tester", region="Testland"
        ),
        channel_type="text", channel="telegram", channel_ref=channel_ref,
        status="escalated", crime_type="investment_scam",
        classification=svc.ClassificationOut(
            crime_type="investment_scam", confidence=0.87, model_version="poc-rules-1",
            signals=["deposit_request"],
        ),
        data_mode="poc", started_at=base_ts, ended_at=base_ts + timedelta(seconds=2),
        message_count=2, entity_count=1,
        escalations=[
            svc.EscalationOut(
                reason="deposit_request", detail="asked for bank transfer",
                message_id=in_id, ts=base_ts,
            )
        ],
        scam_signals=[svc.SignalOut(signal="deposit_request", detail="", message_id=in_id)],
        custody=svc.CustodyOut(messages_logged=2, chain_intact=True, head_sha256=cm_out.sha256),
        syndicate_id=None,
    )
    syndicate = svc.SyndicateOut(
        id=f"syn_{seed}", label=f"{channel_ref} ring", notes=f"clustered from {session_id}",
        linguistic_fingerprint={"channel": "telegram"},
        session_ids=[session_id], entity_count=1,
        members=[
            svc.SyndicateMemberOut(
                entity_id=entity.id, type=entity.type, value=entity.normalized_value,
                link_type="mule_account", confidence=entity.confidence,
            )
        ],
        data_mode="poc", created_at=base_ts,
    )
    session.syndicate_id = syndicate.id
    return session, messages, entity, syndicate


async def _save_bundle(repo: PostgresInfiltrateRepository, seed: str, **kw):
    """Same write order _build_session uses: entities, then syndicate, then
    the session (which may buffer escalation/signal meta patches for messages
    that don't exist yet — see PostgresInfiltrateRepository._pending_message_meta),
    then finally the messages (draining that buffer)."""
    session, messages, entity, syndicate = _bundle(seed, **kw)
    await repo.save_entity(entity)
    await repo.save_syndicate(syndicate)
    await repo.save_session(session)
    await repo.save_messages(session.id, messages)
    return session, messages, entity, syndicate


def _uid() -> str:
    return uuid.uuid4().hex[:10]


# --------------------------------------------------------------------------- #
# The memory path never touches the database (the hard POC invariant).
# --------------------------------------------------------------------------- #


async def test_optional_tenant_session_yields_none_under_memory_persistence():
    """persistence="memory" is the default — get_optional_tenant_session must
    yield None WITHOUT ever attempting a connection. Proven here by NOT
    needing pgserver at all: the default ITTU_DATABASE_URL points at
    localhost:5432 with nothing listening in this environment, so if this
    touched the engine even once, the test would error/hang instead of
    cleanly returning None."""
    from app.core.config import get_settings
    from app.core.db import get_optional_tenant_session

    settings = get_settings()
    assert settings.persistence == "memory"  # sanity: this IS the default

    gen = get_optional_tenant_session()
    got = await gen.__anext__()
    assert got is None
    with pytest.raises(StopAsyncIteration):
        await gen.__anext__()


# --------------------------------------------------------------------------- #
# Round-trip
# --------------------------------------------------------------------------- #


async def test_session_round_trip(app_role_uri):
    """Two separate handles (two separate connections/transactions) — like
    two separate requests — because ``SET LOCAL app.current_agency`` (the RLS
    var) only lives for the transaction that set it: reading on the SAME
    handle right after ``commit()`` would see nothing (the var reset with the
    transaction), which is correct fail-closed RLS behavior, not a bug. A
    fresh handle sets the var fresh for its own transaction."""
    _owner, app_uri = app_role_uri
    write = await _open_repo(app_uri, AGENCY_A)
    try:
        session, _messages, _entity, _syn = await _save_bundle(write.repo, _uid())
        await write.commit()
    finally:
        await write.close()

    read = await _open_repo(app_uri, AGENCY_A)
    try:
        got = await read.repo.get_session(session.id)
        assert got == session

        listed = await read.repo.list_sessions()
        assert session in listed
    finally:
        await read.close()


async def test_messages_round_trip_order_seq_and_custody_chain(app_role_uri):
    """Order, seq, and the sha256/prev_sha256 hash chain all survive the
    round trip — custody.chain_intact is recomputed at read time (never
    stored) and must come back True for an untampered chain."""
    _owner, app_uri = app_role_uri
    write = await _open_repo(app_uri, AGENCY_A)
    try:
        session, messages, _entity, _syn = await _save_bundle(write.repo, _uid())
        await write.commit()
    finally:
        await write.close()

    read = await _open_repo(app_uri, AGENCY_A)
    try:
        got_messages = await read.repo.get_messages(session.id)
        assert got_messages == messages
        assert [m.seq for m in got_messages] == [1, 2]

        got_session = await read.repo.get_session(session.id)
        assert got_session.custody.chain_intact is True
        assert got_session.custody.head_sha256 == messages[-1].sha256
        assert got_session.custody.messages_logged == 2
    finally:
        await read.close()


async def test_entities_round_trip_filters_and_review_resave(app_role_uri):
    _owner, app_uri = app_role_uri
    write = await _open_repo(app_uri, AGENCY_A)
    try:
        session, _messages, entity, _syn = await _save_bundle(write.repo, _uid())
        await write.commit()
    finally:
        await write.close()

    read = await _open_repo(app_uri, AGENCY_A)
    try:
        got_entity = await read.repo.get_entity(entity.id)
        assert got_entity == entity

        by_session = await read.repo.list_entities(session_id=session.id)
        assert by_session == [entity]

        # Scope status filters by session_id too — the pgserver cluster is
        # shared session-scope across this whole test file (other tests'
        # agency-A entities are real neighbors here), so an unscoped status
        # filter would see more than just this test's one entity.
        by_status = await read.repo.list_entities(session_id=session.id, status="unverified")
        assert by_status == [entity]
        assert await read.repo.list_entities(session_id=session.id, status="confirmed") == []

        # Review-status re-save (mirrors service.review_entity): mutate the
        # returned object, re-save, re-fetch — same handle is fine here since
        # everything happens within this one still-open transaction.
        got_entity.review_status = "confirmed"
        got_entity.method = "human"
        await read.repo.save_entity(got_entity)

        refetched = await read.repo.get_entity(entity.id)
        assert refetched.review_status == "confirmed"
        assert refetched.method == "human"
        assert await read.repo.list_entities(session_id=session.id, status="confirmed") == [refetched]
        assert await read.repo.list_entities(session_id=session.id, status="unverified") == []
    finally:
        await read.close()


async def test_syndicates_round_trip(app_role_uri):
    _owner, app_uri = app_role_uri
    write = await _open_repo(app_uri, AGENCY_A)
    try:
        session, _messages, _entity, syndicate = await _save_bundle(write.repo, _uid())
        await write.commit()
    finally:
        await write.close()

    read = await _open_repo(app_uri, AGENCY_A)
    try:
        listed = await read.repo.list_syndicates()
        assert syndicate in listed

        got_session = await read.repo.get_session(session.id)
        assert got_session.syndicate_id == syndicate.id
    finally:
        await read.close()


# --------------------------------------------------------------------------- #
# Stamping — every write carries the injected agency_id + settings.mode.
# --------------------------------------------------------------------------- #


async def test_writes_are_stamped_with_agency_and_data_mode(app_role_uri):
    owner_uri, app_uri = app_role_uri
    handle = await _open_repo(app_uri, AGENCY_A, data_mode="live")
    try:
        session, messages, entity, syndicate = await _save_bundle(handle.repo, _uid())
        await handle.commit()
    finally:
        await handle.close()

    # Read back via the OWNING role (bypasses RLS) so this checks the raw
    # column values, independent of the SELECT policy under test elsewhere.
    owner_engine = create_async_engine(owner_uri)
    try:
        async with owner_engine.connect() as conn:
            row = (
                await conn.execute(
                    sa.text(
                        "SELECT agency_id, data_mode FROM intel.scam_sessions "
                        "WHERE public_id = :pid"
                    ),
                    {"pid": session.id},
                )
            ).one()
            assert str(row.agency_id) == AGENCY_A
            assert row.data_mode == "live"

            msg_row = (
                await conn.execute(
                    sa.text(
                        "SELECT agency_id, data_mode FROM intel.messages WHERE public_id = :pid"
                    ),
                    {"pid": messages[0].id},
                )
            ).one()
            assert str(msg_row.agency_id) == AGENCY_A
            assert msg_row.data_mode == "live"

            ent_row = (
                await conn.execute(
                    sa.text(
                        "SELECT agency_id, data_mode FROM intel.entities WHERE public_id = :pid"
                    ),
                    {"pid": entity.id},
                )
            ).one()
            assert str(ent_row.agency_id) == AGENCY_A
            assert ent_row.data_mode == "live"

            syn_row = (
                await conn.execute(
                    sa.text(
                        "SELECT agency_id, data_mode FROM intel.syndicates WHERE public_id = :pid"
                    ),
                    {"pid": syndicate.id},
                )
            ).one()
            assert str(syn_row.agency_id) == AGENCY_A
            assert syn_row.data_mode == "live"
    finally:
        await owner_engine.dispose()


# --------------------------------------------------------------------------- #
# Isolation — the real payoff of P-1's RLS, now proven through the repo.
# --------------------------------------------------------------------------- #


async def test_repo_isolates_sessions_by_agency(app_role_uri):
    _owner, app_uri = app_role_uri
    seed = _uid()

    a_handle = await _open_repo(app_uri, AGENCY_A)
    try:
        session_a, *_ = await _save_bundle(a_handle.repo, seed, channel_ref="+62-agency-a")
        await a_handle.commit()
    finally:
        await a_handle.close()

    b_handle = await _open_repo(app_uri, AGENCY_B)
    try:
        # Agency B's repo cannot see agency A's session at all.
        assert await b_handle.repo.get_session(session_a.id) is None
        assert session_a.id not in {s.id for s in await b_handle.repo.list_sessions()}
        assert await b_handle.repo.get_messages(session_a.id) is None
        assert await b_handle.repo.list_entities(session_id=session_a.id) == []

        # Agency A still sees its own session (sanity — isolation isn't fail-
        # closed-for-everyone).
    finally:
        await b_handle.close()

    a_handle2 = await _open_repo(app_uri, AGENCY_A)
    try:
        assert await a_handle2.repo.get_session(session_a.id) == session_a
    finally:
        await a_handle2.close()
