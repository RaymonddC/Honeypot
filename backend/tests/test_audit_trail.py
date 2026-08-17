"""Agency audit trail (app/core/audit.py + GET /api/audit).

``core.audit_log`` shipped with the core schema — migrated, and documented as
"append-only; hash-chained per agency" — but nothing ever wrote to it. These
tests cover the writer, and specifically the properties that make the chain
worth having: tampering is DETECTED, tenants are isolated, and recording never
breaks the action it describes.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.audit import (
    CASE_CREATED,
    GENESIS,
    InMemoryAuditRepository,
    record_action,
    reset_audit_store,
)
from app.main import app

client = TestClient(app)


def _login(agency: str = "bareskrim") -> str:
    r = client.post("/api/auth/login", json={"agency_id": agency, "role": "police-investigator"})
    return r.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- the chain itself ---------------------------------------------------------


def test_chain_links_each_entry_to_its_predecessor():
    repo = InMemoryAuditRepository()

    async def run():
        a = await repo.record(agency_id="ag-1", action="case.created", target_id="c1")
        b = await repo.record(agency_id="ag-1", action="case.updated", target_id="c1")
        return a, b

    first, second = asyncio.run(run())
    assert first.seq == 1 and second.seq == 2
    assert first.prev_sha256 == GENESIS       # chain starts from a known root
    assert second.prev_sha256 == first.sha256  # …and every link points back
    ok, broken = asyncio.run(repo.verify_chain(agency_id="ag-1"))
    assert ok is True and broken is None


def test_tampering_is_detected_and_located():
    """The whole point: editing a recorded action must be visible afterwards.

    An audit log you can quietly rewrite is worse than none — it lends false
    confidence to whatever it says. The report also names WHERE the chain
    breaks, because "invalid" alone isn't actionable.
    """
    repo = InMemoryAuditRepository()

    async def run():
        for i in range(4):
            await repo.record(agency_id="ag-1", action="case.updated", detail={"i": i})
        # Someone edits entry 2 in place, leaving its hash untouched.
        repo._by_agency["ag-1"][1].detail = {"i": "edited"}
        return await repo.verify_chain(agency_id="ag-1")

    ok, broken_at = asyncio.run(run())
    assert ok is False
    assert broken_at == 2, "should point at the first entry that fails"


def test_deleting_an_entry_is_detected():
    """Removing a row must not produce a chain that still verifies — otherwise
    the easiest tampering of all (drop the inconvenient line) goes unnoticed."""
    repo = InMemoryAuditRepository()

    async def run():
        for i in range(4):
            await repo.record(agency_id="ag-1", action="case.updated", detail={"i": i})
        del repo._by_agency["ag-1"][1]  # entry 2 disappears
        return await repo.verify_chain(agency_id="ag-1")

    ok, _ = asyncio.run(run())
    assert ok is False


def test_chains_are_per_agency_and_independent():
    """Agencies are RLS-isolated, so a global chain would make one tenant's
    verification depend on rows it may not read."""
    repo = InMemoryAuditRepository()

    async def run():
        await repo.record(agency_id="ag-1", action="case.created")
        await repo.record(agency_id="ag-2", action="case.created")
        return (
            await repo.list_entries(agency_id="ag-1"),
            await repo.list_entries(agency_id="ag-2"),
        )

    one, two = asyncio.run(run())
    assert len(one) == 1 and len(two) == 1
    assert one[0].seq == 1 and two[0].seq == 1        # each starts its own chain
    assert one[0].prev_sha256 == two[0].prev_sha256 == GENESIS


def test_recording_never_raises():
    """Audit is bookkeeping ABOUT work that already happened. If it fails, the
    action must still stand — a failed insert rolling back a completed case
    update trades a missing log line for corrupted state."""

    from app.core.config import get_settings

    class Exploding:
        def add(self, *a, **k):
            raise RuntimeError("db is down")

        async def execute(self, *a, **k):
            raise RuntimeError("db is down")

    # The session is only consulted under postgres persistence, so force it —
    # otherwise this passes for the wrong reason (memory repo, session ignored).
    settings = get_settings()
    prior = settings.persistence
    settings.persistence = "postgres"
    try:
        # Never raises, and says so by returning None.
        assert asyncio.run(
            record_action(Exploding(), agency_id="ag-1", action=CASE_CREATED)
        ) is None
    finally:
        settings.persistence = prior
    # A missing tenant is also survivable (and logged, not silently accepted).
    assert asyncio.run(record_action(None, agency_id=None, action=CASE_CREATED)) is None


# --- through the API ----------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_audit():
    reset_audit_store()
    yield
    reset_audit_store()


def test_creating_and_updating_a_case_is_recorded():
    token = _login()
    created = client.post(
        "/api/cases", json={"title": "Audit me"}, headers=_auth(token)
    ).json()
    client.patch(
        f"/api/cases/{created['id']}", json={"stage": "trace"}, headers=_auth(token)
    )

    feed = client.get("/api/audit", headers=_auth(token)).json()
    actions = [e["action"] for e in feed["entries"]]
    assert "case.created" in actions and "case.updated" in actions
    assert feed["chain_ok"] is True

    update = next(e for e in feed["entries"] if e["action"] == "case.updated")
    # Only the changed field — not the whole object, which would bury it.
    assert update["detail"]["changed"] == {"stage": "trace"}
    assert update["target_type"] == "case"


def test_audit_feed_requires_auth_and_is_agency_scoped():
    assert client.get("/api/audit").status_code == 401

    bareskrim, ppatk = _login("bareskrim"), _login("ppatk")
    client.post("/api/cases", json={"title": "Bareskrim only"}, headers=_auth(bareskrim))

    other = client.get("/api/audit", headers=_auth(ppatk)).json()
    titles = [e.get("detail", {}).get("title") for e in other["entries"]]
    assert "Bareskrim only" not in titles, "one agency must not see another's actions"
