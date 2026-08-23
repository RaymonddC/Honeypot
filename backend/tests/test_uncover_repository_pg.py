"""PostgresUncoverRepository — round-trip, stamping, isolation (P-3,
docs/Persistence-Plan.md P-3).

Same ephemeral, in-process Postgres harness as ``tests/test_infiltrate_repository_pg.py``
(pgserver — no Docker needed): runs the full Alembic chain (now through
migration ``20260717_08``, the ``action.action_bundles`` table + the
public_id/bundle_id bridges), creates the non-superuser ``ittu_app`` role via
the real deploy script, and proves the repository against it — connected AS
``ittu_app`` (never the owning/migration role), so RLS is actually enforcing,
not bypassed.

Repos are built directly (not through FastAPI's ``Depends`` graph — there's
no request/JWT here) over a session opened the same way
``app.core.db.get_tenant_session`` opens one: connect as ``ittu_app``,
``SELECT set_config('app.current_agency', ...)`` for the transaction, then
hand that session + the agency id to ``PostgresUncoverRepository`` exactly as
``get_uncover_repository`` would per-request.

Skips cleanly (not a failure) if ``pgserver`` isn't installed or can't start a
Postgres instance here — same as ``test_infiltrate_repository_pg.py``.
"""

import hashlib
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.uncover import documents as docs
from app.uncover import service as svc
from app.uncover.notifications import NotificationOut, RoutingTarget
from app.uncover.repository import PostgresUncoverRepository

BACKEND_DIR = Path(__file__).resolve().parents[1]

# Ephemeral, throwaway DB only — never a real credential. Distinct password
# from the other *_repository_pg.py files only so they read independently.
APP_ROLE_PASSWORD = "ittu-test-role-pw-3"  # noqa: S105

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

    pgdata = tempfile.mkdtemp(prefix="ittu-pgdata-uncover-repo-")
    try:
        srv = pgserver.get_server(pgdata, cleanup_mode="delete")
    except Exception as exc:  # pragma: no cover - environment-dependent
        pytest.skip(f"pgserver could not start a Postgres instance here: {exc}")

    yield srv
    srv.cleanup()


@pytest.fixture(scope="session")
def app_role_uri(pg_cluster):
    """Run migrations 01→08, create ``ittu_app`` via the real deploy script.

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

    def __init__(self, repo: PostgresUncoverRepository, session: AsyncSession, engine) -> None:
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
    # Mode is an RLS predicate too (migration 20260823_18). Set from the SAME
    # value the repo stamps with, mirroring _tenant_scoped_session — if the two
    # ever disagree the write is refused, which is the point.
    await session.execute(
        sa.text("SELECT set_config('app.data_mode', :v, true)"), {"v": data_mode}
    )
    repo = PostgresUncoverRepository(session, agency_id=uuid.UUID(agency_id), data_mode=data_mode)
    return _RepoHandle(repo, session, engine)


def _uid() -> str:
    return uuid.uuid4().hex[:10]


def _bundle_and_docs(seed: str, *, case_id: str = "CASE-2026-0142"):
    """One ActionBundle + its GeneratedDocuments — same shape
    ``service.generate_bundle`` assembles, hand-built here (real PDF-shaped
    bytes + a real sha256, so the round trip has something real to check)."""
    action_id = f"act_{seed}"
    base_ts = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)

    pdf_bytes = f"%PDF-1.4 test evidence for {seed}".encode()
    sha = hashlib.sha256(pdf_bytes).hexdigest()
    doc = docs.GeneratedDocument(
        id=f"doc_{seed}_1",
        type="account_blocking",
        format="iasc",
        title="Permohonan Pemblokiran — Account & Wallet Freeze Request",
        filename=f"freeze-{case_id}.pdf",
        pdf=pdf_bytes,
        sha256=sha,
        generated_at=base_ts,
        template_version="uncover-templates-0.1.0",
        status="draft",
        data_mode="poc",
        meta={"goaml_draft": {"report": {"report_code": "STR"}}},  # write-time-only, not round-tripped
    )
    doc_out = svc.DocumentOut(
        id=doc.id, type=doc.type, format=doc.format, title=doc.title, filename=doc.filename,
        sha256=doc.sha256, size_bytes=len(doc.pdf), status=doc.status,
        template_version=doc.template_version, generated_at=doc.generated_at,
        data_mode=doc.data_mode, download_url=f"/api/documents/{doc.id}",
    )

    entity = svc.ActionEntityIn(
        type="crypto_wallet", value=f"T{seed}wallet", chain="tron", holder_name=None
    )
    routing_plan = [
        RoutingTarget(
            agency="Exchange (Indodax)", agency_type="exchange", channel="webhook",
            document_type="account_blocking", reason=f"freeze/flag wallet T{seed}wallet",
        )
    ]
    totals = svc.BundleTotals(at_risk_usdt=1234.5, at_risk_idr=19_752_000.0)

    bundle = svc.ActionBundle(
        id=action_id, case_id=case_id, status="draft", data_mode="poc",
        crime_type="investment", outputs=["freeze"], entities=[entity],
        documents=[doc_out], goaml_draft=None, routing_plan=routing_plan,
        notifications=[], totals=totals, created_at=base_ts, dispatched_at=None, audit=[],
    )
    return bundle, [doc]


async def _save_bundle(repo: PostgresUncoverRepository, seed: str, **kw):
    """Same write order service.generate_bundle uses: the bundle envelope
    FIRST (its uuid is the FK target), then each document (references the
    bundle's public_id)."""
    bundle, generated = _bundle_and_docs(seed, **kw)
    await repo.save_bundle(bundle)
    for d in generated:
        await repo.save_document(bundle.id, d)
    return bundle, generated


# --------------------------------------------------------------------------- #
# The memory path never touches the database (the hard POC invariant).
# --------------------------------------------------------------------------- #


async def test_get_uncover_repository_returns_memory_singleton_under_memory_persistence():
    """persistence="memory" is the default — get_uncover_repository must
    return the in-memory singleton WITHOUT ever attempting a connection.
    Proven here by NOT needing pgserver at all: the default
    ITTU_DATABASE_URL points at localhost:5432 with nothing listening in
    this environment, so if this touched the engine even once, the call
    would hang/error instead of returning immediately."""
    from app.core.config import get_settings
    from app.uncover.repository import InMemoryUncoverRepository, get_uncover_repository

    settings = get_settings()
    assert settings.persistence == "memory"  # sanity: this IS the default

    repo = await get_uncover_repository()
    assert isinstance(repo, InMemoryUncoverRepository)


# --------------------------------------------------------------------------- #
# Round-trip
# --------------------------------------------------------------------------- #


async def test_bundle_round_trip_with_free_text_case_id(app_role_uri):
    """The bundle's case_id is a free-text business key ("CASE-2026-0142"),
    never a uuid — this is the exact gap that made action_bundles.case_id a
    ``text`` column instead of following action_documents/notifications'
    existing ``uuid`` column. If that had been dropped or mis-typed, this
    round trip would come back with case_id=None or raise."""
    _owner, app_uri = app_role_uri
    write = await _open_repo(app_uri, AGENCY_A)
    try:
        bundle, _docs = await _save_bundle(write.repo, _uid())
        await write.commit()
    finally:
        await write.close()

    read = await _open_repo(app_uri, AGENCY_A)
    try:
        got = await read.repo.get_bundle(bundle.id)
        assert got == bundle
        assert got.case_id == "CASE-2026-0142"

        listed = await read.repo.list_bundles()
        assert bundle in listed
    finally:
        await read.close()


async def test_document_round_trip_pdf_bytes_and_status_transition(app_role_uri):
    """PDF bytes, sha256, and the scalar fields (title/filename/template_version)
    that had no column before migration 08 all survive the round trip; a
    status transition (draft -> issued) persists via the targeted update, not
    a full document re-save."""
    _owner, app_uri = app_role_uri
    write = await _open_repo(app_uri, AGENCY_A)
    try:
        bundle, generated = await _save_bundle(write.repo, _uid())
        await write.commit()
    finally:
        await write.close()

    read = await _open_repo(app_uri, AGENCY_A)
    try:
        got_doc = await read.repo.get_document(generated[0].id)
        assert got_doc is not None
        assert got_doc.pdf == generated[0].pdf
        assert got_doc.sha256 == generated[0].sha256
        assert got_doc.title == generated[0].title
        assert got_doc.filename == generated[0].filename
        assert got_doc.template_version == generated[0].template_version
        assert got_doc.status == "draft"
        assert got_doc.meta == {}  # write-time-only — never round-tripped, see repository.py

        got_bundle = await read.repo.get_bundle(bundle.id)
        assert got_bundle.documents[0].size_bytes == len(generated[0].pdf)  # derived, not stored

        await read.repo.update_document_status(generated[0].id, "issued")
        await read.commit()
    finally:
        await read.close()

    verify = await _open_repo(app_uri, AGENCY_A)
    try:
        doc_after = await verify.repo.get_document(generated[0].id)
        assert doc_after.status == "issued"
        assert doc_after.pdf == generated[0].pdf  # untouched by the targeted status update

        bundle_after = await verify.repo.get_bundle(bundle.id)
        assert bundle_after.documents[0].status == "issued"
    finally:
        await verify.close()


async def test_dispatch_round_trip_notifications_and_bundle_status(app_role_uri):
    """Dispatch: bundle flips draft -> dispatched, notifications land in their
    own table (joined back via bundle_id — action_id/case_id are derived from
    the bundle, not duplicated columns)."""
    _owner, app_uri = app_role_uri
    seed = _uid()
    write = await _open_repo(app_uri, AGENCY_A)
    try:
        bundle, _generated = await _save_bundle(write.repo, seed)
        await write.commit()
    finally:
        await write.close()

    dispatch = await _open_repo(app_uri, AGENCY_A)
    try:
        got = await dispatch.repo.get_bundle(bundle.id)
        notification = NotificationOut(
            id=f"ntf_{seed}_1", action_id=got.id, case_id=got.case_id,
            target_agency="Exchange (Indodax)", agency_type="exchange", channel="webhook",
            status="mock", data_mode="poc",
            sent_at=datetime(2026, 7, 7, 12, 5, 0, tzinfo=timezone.utc),
            payload={"note": "POC mock sink — would dispatch to Exchange (Indodax) via webhook"},
        )
        got.notifications = [notification]
        got.status = "dispatched"
        got.dispatched_at = got.created_at + timedelta(minutes=5)
        await dispatch.repo.save_bundle(got)
        await dispatch.commit()
    finally:
        await dispatch.close()

    read = await _open_repo(app_uri, AGENCY_A)
    try:
        final = await read.repo.get_bundle(bundle.id)
        assert final.status == "dispatched"
        assert final.dispatched_at == bundle.created_at + timedelta(minutes=5)
        assert len(final.notifications) == 1
        n = final.notifications[0]
        assert n.id == f"ntf_{seed}_1"
        assert n.action_id == bundle.id      # derived via the bundle_id FK join
        assert n.case_id == bundle.case_id   # derived via the bundle_id FK join
        assert n.target_agency == "Exchange (Indodax)"
        assert n.agency_type == "exchange"
        assert n.status == "mock"
    finally:
        await read.close()


# --------------------------------------------------------------------------- #
# Stamping — every write carries the injected agency_id + settings.mode.
# --------------------------------------------------------------------------- #


async def test_writes_are_stamped_with_agency_and_data_mode(app_role_uri):
    owner_uri, app_uri = app_role_uri
    handle = await _open_repo(app_uri, AGENCY_A, data_mode="live")
    try:
        bundle, generated = await _save_bundle(handle.repo, _uid())
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
                        "SELECT agency_id, data_mode FROM action.action_bundles "
                        "WHERE public_id = :pid"
                    ),
                    {"pid": bundle.id},
                )
            ).one()
            assert str(row.agency_id) == AGENCY_A
            assert row.data_mode == "live"

            doc_row = (
                await conn.execute(
                    sa.text(
                        "SELECT agency_id, data_mode FROM action.action_documents "
                        "WHERE public_id = :pid"
                    ),
                    {"pid": generated[0].id},
                )
            ).one()
            assert str(doc_row.agency_id) == AGENCY_A
            assert doc_row.data_mode == "live"
    finally:
        await owner_engine.dispose()


# --------------------------------------------------------------------------- #
# Isolation — the real payoff of P-1's RLS, now proven through the repo.
# --------------------------------------------------------------------------- #


async def test_repo_isolates_bundles_by_agency(app_role_uri):
    _owner, app_uri = app_role_uri
    seed = _uid()

    a_handle = await _open_repo(app_uri, AGENCY_A)
    try:
        bundle_a, docs_a = await _save_bundle(a_handle.repo, seed, case_id="CASE-2026-AGENCY-A")
        await a_handle.commit()
    finally:
        await a_handle.close()

    b_handle = await _open_repo(app_uri, AGENCY_B)
    try:
        # Agency B's repo cannot see agency A's bundle or document at all.
        assert await b_handle.repo.get_bundle(bundle_a.id) is None
        assert bundle_a.id not in {b.id for b in await b_handle.repo.list_bundles()}
        assert await b_handle.repo.get_document(docs_a[0].id) is None

        # A status update from agency B's session must not touch agency A's row
        # (RLS's WITH CHECK blocks it via the plain UPDATE too).
        await b_handle.repo.update_document_status(docs_a[0].id, "issued")
    finally:
        await b_handle.close()

    # Agency A still sees its own bundle, and its document is untouched by
    # agency B's no-op update above (sanity — isolation isn't fail-closed for
    # everyone, and it's real row-level enforcement, not an app-level filter
    # that merely hides the row).
    a_handle2 = await _open_repo(app_uri, AGENCY_A)
    try:
        got = await a_handle2.repo.get_bundle(bundle_a.id)
        assert got == bundle_a
        doc = await a_handle2.repo.get_document(docs_a[0].id)
        assert doc.status == "draft"
    finally:
        await a_handle2.close()
