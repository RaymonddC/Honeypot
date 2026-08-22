"""Readiness diagnostics — GET /ready (app/core/health.py).

The endpoint's whole value is in its FAILURE paths: it exists so that "why isn't
it working?" has one answer instead of a stack trace pointing somewhere
unhelpful. So most of this file drives the checks into their broken states and
asserts the detail actually names the fix.

Two properties matter as much as the checks themselves:

* ``/health`` must stay shallow and independent. It is Render's health check —
  if it started failing when Postgres blinked, a transient database problem
  would take the whole service down instead of degrading one page.
* ``/ready`` is unauthenticated (it backs a probe), so it must never leak a
  connection string, password, or hostname.

Everything here runs in memory mode with the dependency calls patched: these
tests must not need a database or a Redis.
"""

import pytest
from fastapi.testclient import TestClient

from app.core import health
from app.core.config import get_settings
from app.core.health import Check, readiness
from app.main import app

client = TestClient(app)


def _run(coro):
    """Run one coroutine — the checks are async but need no event-loop plugin."""
    import asyncio

    return asyncio.run(coro)


async def _grants_ok():
    """Stand-in for the grants probe when a test is exercising another check."""
    return Check("schema_grants", True, "all schemas usable")


@pytest.fixture
def restore_settings():
    """Save/restore the settings this file mutates.

    conftest's autouse fixture restores persistence/mode/keys, but not the URLs
    or the delivery flags — a leaked ITTU_REDIS_URL here would break unrelated
    tests in confusing ways.
    """
    s = get_settings()
    saved = (
        s.database_url,
        s.redis_url,
        s.migration_database_url,
        s.notification_delivery,
        s.dial_enqueue_on_start,
    )
    yield s
    (
        s.database_url,
        s.redis_url,
        s.migration_database_url,
        s.notification_delivery,
        s.dial_enqueue_on_start,
    ) = saved


# --------------------------------------------------------------------------- #
# Fakes — enough async-SQLAlchemy surface to exercise the real check logic.
# Patching the *engine factory* (rather than the whole check) keeps the real
# message construction under test, which is the part operators actually read.
# --------------------------------------------------------------------------- #


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value


class _FakeConn:
    def __init__(self, scalars, revision=None):
        self._scalars = list(scalars)
        self._revision = revision

    async def execute(self, *_args, **_kwargs):
        return _FakeResult(self._scalars.pop(0) if self._scalars else None)

    async def run_sync(self, _fn):
        return self._revision

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


class _FakeEngine:
    def __init__(self, conn):
        self._conn = conn

    def connect(self):
        return self._conn

    async def dispose(self):
        return None


def _engine_factory(monkeypatch, *engines):
    """Patch create_async_engine to hand back the given fakes, in order.

    Patched on ``sqlalchemy.ext.asyncio`` because health.py imports it inside
    each function, so the lookup happens at call time.
    """
    import sqlalchemy.ext.asyncio as sa_async

    queue = list(engines)

    def _make(*_args, **_kwargs):
        return queue.pop(0) if queue else _FakeEngine(_FakeConn([]))

    monkeypatch.setattr(sa_async, "create_async_engine", _make)


# --------------------------------------------------------------------------- #
# /health stays shallow
# --------------------------------------------------------------------------- #


def test_health_is_shallow_and_independent_of_dependencies(monkeypatch):
    """/health must NOT consult dependencies.

    It is the platform health check; wiring it to the database would turn a
    transient blip into a full outage. Proven by making readiness explode and
    checking /health is unaffected.
    """

    async def _boom():
        raise RuntimeError("dependencies are on fire")

    monkeypatch.setattr(health, "readiness", _boom)

    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


def test_ready_in_memory_mode_needs_no_database(monkeypatch):
    """Memory persistence is a supported posture, not a degraded one — the
    database check reports non-critical rather than failing."""
    monkeypatch.setattr(health, "_check_redis", lambda: Check("redis", True, "reachable"))

    r = client.get("/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is True
    assert body["persistence"] == "memory"

    db = next(c for c in body["checks"] if c["name"] == "database")
    assert db["ok"] is True and db["critical"] is False
    assert "memory persistence" in db["detail"]


def test_ready_needs_no_auth():
    """It backs a readiness probe — a probe cannot present a Bearer token."""
    assert client.get("/ready").status_code in (200, 503)


# --------------------------------------------------------------------------- #
# Failure paths — the reason the endpoint exists
# --------------------------------------------------------------------------- #


def test_unreachable_database_fails_ready_with_503(monkeypatch, restore_settings):
    """A critical failure must flip `ready` AND the status code, so a probe can
    act on it while a human reads the same body to find out why."""
    settings = restore_settings
    settings.persistence = "postgres"

    async def _unreachable():
        return [Check("database", False, "unreachable: ConnectionRefusedError")]

    monkeypatch.setattr(health, "_check_database", _unreachable)
    monkeypatch.setattr(health, "_check_schema_grants", _grants_ok)
    monkeypatch.setattr(health, "_check_redis", lambda: Check("redis", True, "reachable"))

    r = client.get("/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False
    db = next(c for c in body["checks"] if c["name"] == "database")
    assert db["ok"] is False and "unreachable" in db["detail"]



def test_schema_behind_head_tells_you_to_migrate(monkeypatch, restore_settings):
    """The drift that broke case creation. The detail must name the command —
    'schema_at_head: false' alone sends someone hunting."""
    settings = restore_settings
    settings.persistence = "postgres"
    settings.migration_database_url = "postgresql+asyncpg://owner@db/ittu"

    from app.core import migration_guard

    monkeypatch.setattr(migration_guard, "code_head_revision", lambda: "20260818_16")
    # app engine: SELECT current_user -> ittu_app;  owner engine: revision behind
    _engine_factory(
        monkeypatch,
        _FakeEngine(_FakeConn(["ittu_app"])),
        _FakeEngine(_FakeConn([], revision="20260723_11")),
    )

    checks = _run(health._check_database())
    at_head = next(c for c in checks if c.name == "schema_at_head")
    assert at_head.ok is False
    assert "20260723_11" in at_head.detail and "20260818_16" in at_head.detail
    assert "alembic upgrade head" in at_head.detail


def test_missing_grants_name_the_schema_and_the_script(monkeypatch):
    """How `casedata` stayed silently broken: InsufficientPrivilege at first use
    of one feature, with nothing pointing at grants."""
    # 7 schemas probed in order; deny the 6th (casedata).
    privileges = [True, True, True, True, True, False, True]
    _engine_factory(monkeypatch, _FakeEngine(_FakeConn(privileges)))

    check = _run(health._check_schema_grants())
    assert check.ok is False
    assert "casedata" in check.detail
    assert "create_app_role.sql" in check.detail


def test_rls_warns_loudly_when_connected_as_the_owning_role(monkeypatch):
    """Owner bypasses RLS entirely, so isolation silently does not apply.

    Non-critical on purpose — single-role local setups are legitimate — but the
    detail has to say plainly that isolation is off, because the symptom
    (everything works) looks like success.
    """
    _engine_factory(
        monkeypatch,
        _FakeEngine(_FakeConn(["ittu"])),          # the OWNING role
        _FakeEngine(_FakeConn([], revision=None)),
    )
    from app.core import migration_guard

    monkeypatch.setattr(migration_guard, "code_head_revision", lambda: None)

    checks = _run(health._check_database())
    rls = next(c for c in checks if c.name == "rls_enforcing")
    assert rls.ok is False
    assert rls.critical is False
    assert "RLS is bypassed" in rls.detail


# --------------------------------------------------------------------------- #
# Redis criticality depends on whether anything actually queues
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("delivery", "dial_enqueue", "expect_critical"),
    [
        ("sync", False, False),   # nothing queues — an idle Redis is not an outage
        ("worker", False, True),  # C1 dispatch goes through the broker
        ("sync", True, True),     # outbound dialing enqueues
    ],
)
def test_redis_is_critical_only_when_something_queues(
    monkeypatch, restore_settings, delivery, dial_enqueue, expect_critical
):
    """Redis being down only blocks readiness when work depends on it.

    Marking it always-critical would make every POC deployment permanently
    "not ready", which trains people to ignore the endpoint.
    """
    settings = restore_settings
    settings.notification_delivery = delivery
    settings.dial_enqueue_on_start = dial_enqueue

    import redis

    def _refuse(*_a, **_k):
        raise ConnectionError("nope")

    monkeypatch.setattr(redis, "from_url", _refuse)

    check = health._check_redis()
    assert check.ok is False
    assert check.critical is expect_critical
    if expect_critical:
        assert "queued work will never run" in check.detail
    else:
        assert "nothing queues today" in check.detail


# --------------------------------------------------------------------------- #
# No secrets — the endpoint is unauthenticated by design
# --------------------------------------------------------------------------- #


def test_ready_never_leaks_connection_strings(monkeypatch, restore_settings):
    """Built from the CONFIGURED urls rather than hardcoded, so this keeps
    holding if the defaults change."""
    settings = restore_settings
    settings.database_url = "postgresql+asyncpg://someuser:sup3rs3cret@db.internal:5432/ittu"
    settings.redis_url = "redis://:r3disp4ss@cache.internal:6379/0"
    settings.migration_database_url = "postgresql+asyncpg://owner:0wnerpw@db.internal:5432/ittu"

    import redis

    monkeypatch.setattr(
        redis, "from_url", lambda *_a, **_k: (_ for _ in ()).throw(ConnectionError("no"))
    )

    body = client.get("/ready").text
    for url in (settings.database_url, settings.redis_url, settings.migration_database_url):
        assert url not in body
    for secret in ("sup3rs3cret", "r3disp4ss", "0wnerpw", "db.internal", "cache.internal"):
        assert secret not in body, f"{secret!r} leaked into an unauthenticated response"


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #


def test_non_critical_failures_do_not_block_ready(monkeypatch):
    """`ready` is about "can this serve traffic", not "is everything perfect" —
    an RLS warning or an unused Redis must not take the service out."""
    monkeypatch.setattr(
        health, "_check_redis", lambda: Check("redis", False, "unreachable", critical=False)
    )

    result = _run(readiness())
    assert result.ready is True
    assert any(c.ok is False for c in result.checks)
