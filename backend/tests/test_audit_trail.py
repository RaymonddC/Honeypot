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
    DENIAL_CAP,
    GENESIS,
    USER_DEACTIVATED,
    USER_ROLE_CHANGED,
    InMemoryAuditRepository,
    _memory_repository,
    is_denied,
    record_action,
    record_denial,
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


def test_the_wired_actions_all_record():
    """Every call site that claims to be audited actually is.

    Wiring an audit trail is the kind of change that rots quietly: a new
    endpoint ships, nobody adds the record_action call, and the log looks fine
    because it still has rows. This pins the set.
    """
    token = _login()  # auth.login
    case = client.post("/api/cases", json={"title": "Wired"}, headers=_auth(token)).json()
    client.patch(f"/api/cases/{case['id']}", json={"stage": "trace"}, headers=_auth(token))

    entities = client.get("/api/entities", headers=_auth(token)).json()
    if entities:  # the POC replay seeds extracted entities
        client.post(
            f"/api/entities/{entities[0]['id']}/review",
            json={"status": "confirmed"},
            headers=_auth(token),
        )

    feed = client.get("/api/audit", headers=_auth(token)).json()
    actions = {e["action"] for e in feed["entries"]}
    assert {"auth.login", "case.created", "case.updated"} <= actions
    if entities:
        assert "entity.reviewed" in actions
    assert feed["chain_ok"] is True, "wiring more writers must not break the chain"


def test_login_is_recorded_with_method_and_role():
    """'Who authenticated, how, and as what' is a first-order audit question.

    The recorded role must match the identity actually issued — an audit entry
    that disagrees with the token is worse than none.
    """
    r = client.post(
        "/api/auth/login",
        json={"agency_id": "ppatk", "role": "regulator-analyst"},
    ).json()
    feed = client.get("/api/audit", headers=_auth(r["token"])).json()
    login = next(e for e in feed["entries"] if e["action"] == "auth.login")
    assert login["detail"]["method"] == "demo"
    assert login["detail"]["role"] == r["role"] == "regulator-analyst"
    assert login["actor_user_id"] == r["user"]["id"]


def test_dispatch_is_recorded_with_recipients():
    """Dispatch is the product's most consequential action — irreversible and
    outward. 'Who authorised it, and which agencies were told' is precisely what
    gets asked afterwards, so recipients are recorded by name."""
    token = _login()
    r = client.post(
        "/api/actions/generate",
        json={
            "case_id": "CASE-AUDIT-1",
            "crime_type": "investment",
            "entities": [
                {
                    "type": "crypto_wallet",
                    "value": "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6",
                    "chain": "tron",
                }
            ],
            "outputs": ["freeze"],
        },
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    bundle = r.json()
    d = client.post(f"/api/actions/{bundle['id']}/dispatch", headers=_auth(token))
    assert d.status_code == 200, d.text

    feed = client.get("/api/audit", headers=_auth(token)).json()
    sent = next((e for e in feed["entries"] if e["action"] == "dispatch.sent"), None)
    assert sent is not None, "dispatch must be audited"
    assert sent["target_type"] == "action_bundle"
    assert sent["detail"]["recipients"], "recipient agencies must be named"
    # The packet itself and any signing secret must never reach the audit row.
    assert "payload" not in sent["detail"] and "secret" not in str(sent["detail"]).lower()
    assert feed["chain_ok"] is True


def test_generated_evidence_is_recorded_durably_with_hashes():
    """Bundle generation lands in the DURABLE trail, with document hashes.

    uncover.custody also records this, but that chain is an in-memory POC
    accumulator refilled per request — it does not survive a restart. Recording
    here is what makes "what evidence was produced, by whom, and what did it
    hash to" answerable later from one place, without having to trust a second
    table to still agree.
    """
    token = _login()
    bundle = client.post(
        "/api/actions/generate",
        json={
            "case_id": "CASE-AUDIT-2",
            "crime_type": "investment",
            "entities": [
                {
                    "type": "crypto_wallet",
                    "value": "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6",
                    "chain": "tron",
                }
            ],
            "outputs": ["freeze"],
        },
        headers=_auth(token),
    ).json()

    feed = client.get("/api/audit", headers=_auth(token)).json()
    gen = next(e for e in feed["entries"] if e["action"] == "action.bundle.generated")
    assert gen["target_id"] == bundle["id"]
    docs = gen["detail"]["documents"]
    assert docs, "generated documents must be recorded"
    # The hash is the evidentiary part — it must match what the API returned.
    assert {d["sha256"] for d in docs} == {d["sha256"] for d in bundle["documents"]}
    assert feed["chain_ok"] is True


def test_entries_name_the_person_and_the_thing_not_uuids():
    """An audit row must be readable by the people it exists for.

    Before this, "who did what" answered with actor=9f79eb96-3e3a-57b1-… and
    target=case/43b65ec1 — unusable to an investigator, let alone a court. Name
    and label are SNAPSHOTTED at write time, not joined on read: if a user is
    later renamed or a case retitled, the entry must still say who acted on what
    AT THE TIME (same reasoning as intel.scam_sessions.persona_snapshot).
    """
    token = _login()
    case = client.post(
        "/api/cases", json={"title": "Judol sweep Aug"}, headers=_auth(token)
    ).json()
    client.patch(
        f"/api/cases/{case['id']}", json={"stage": "trace"}, headers=_auth(token)
    )
    feed = client.get("/api/audit", headers=_auth(token)).json()
    by_action = {e["action"]: e for e in feed["entries"]}

    for action in ("auth.login", "case.created", "case.updated"):
        assert by_action[action]["detail"]["_actor"] == "Budi Santoso", action

    # The thing acted on is named, so "changed a case" says WHICH case.
    assert by_action["case.created"]["detail"]["_target"] == "Judol sweep Aug"
    assert by_action["case.updated"]["detail"]["_target"] == "Judol sweep Aug"
    # For a login the target IS the actor; repeating it reads as
    # "Budi Santoso signed in Budi Santoso".
    assert "_target" not in by_action["auth.login"]["detail"]


def test_entries_record_where_the_action_came_from():
    """Audit practice (CloudTrail/SOC 2) records who acted AND from what device
    and location. We recorded only who and when — material for a
    law-enforcement tool, where "Budi confirmed this wallet" reads very
    differently from an unrecognised address at 03:00.

    The first X-Forwarded-For entry is the real client: Render terminates TLS
    upstream, so request.client is the proxy. Later hops are appended by
    intermediaries, so only the first is taken.
    """
    token = _login()
    headers = {
        **_auth(token),
        "X-Forwarded-For": "203.0.113.9, 10.0.0.1",
        "User-Agent": "Mozilla/5.0 ITTU-Console",
    }
    client.post("/api/cases", json={"title": "Origin test"}, headers=headers)

    feed = client.get("/api/audit", headers=_auth(token)).json()
    created = next(e for e in feed["entries"] if e["action"] == "case.created")
    assert created["detail"]["_ip"] == "203.0.113.9", "must be the client, not the proxy"
    assert created["detail"]["_user_agent"] == "Mozilla/5.0 ITTU-Console"
    # Ties the audit row to its request log line.
    assert created["detail"]["_request_id"]


def test_downloading_evidence_is_audited_with_its_hash():
    """Evidence LEAVING the system — the only read we audit, deliberately.

    "Who downloaded the evidence pack" is a top insider-risk question in
    forensics (arguably more than who edited a case title), and it was
    previously possible with no trace at all. The document's custody hash is
    recorded so the trail says exactly WHICH bytes were taken, making an
    exported copy comparable later.
    """
    token = _login()
    bundle = client.post(
        "/api/actions/generate",
        json={
            "case_id": "CASE-EXPORT-1",
            "crime_type": "investment",
            "entities": [
                {"type": "crypto_wallet", "value": "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6", "chain": "tron"}
            ],
            "outputs": ["freeze"],
        },
        headers=_auth(token),
    ).json()
    doc = bundle["documents"][0]

    r = client.get(f"/api/documents/{doc['id']}", headers=_auth(token))
    assert r.status_code == 200

    feed = client.get("/api/audit", headers=_auth(token)).json()
    export = next(e for e in feed["entries"] if e["action"] == "evidence.exported")
    assert export["target_id"] == doc["id"]
    assert export["detail"]["sha256"] == doc["sha256"], "must record WHICH bytes left"
    assert export["detail"]["_actor"] == "Budi Santoso"
    assert feed["chain_ok"] is True


# --- denied actions -----------------------------------------------------------


def test_recording_a_denial_never_raises():
    """Same guarantee as record_action, plus one that matters more: this runs on
    a path already returning a clean 4xx, so a failure here must never turn a
    403 into a 500 — the caller would learn something about our infrastructure
    instead of being told no."""
    from app.core import db as db_module
    from app.core.config import get_settings

    def exploding_sessionmaker():
        raise RuntimeError("db is down")

    settings = get_settings()
    prior_persistence, prior_maker = settings.persistence, db_module.SessionLocal
    settings.persistence = "postgres"  # or the memory repo answers, proving nothing
    db_module.SessionLocal = exploding_sessionmaker
    try:
        # Never raises, and says so by returning None.
        assert asyncio.run(
            record_denial(
                agency_id="ag-1", action=USER_ROLE_CHANGED,
                denial_code="privilege_escalation", actor_user_id="u-1",
            )
        ) is None
    finally:
        settings.persistence = prior_persistence
        db_module.SessionLocal = prior_maker

    # A missing tenant is survivable too (and logged, not silently accepted).
    assert asyncio.run(
        record_denial(agency_id=None, action=USER_ROLE_CHANGED, denial_code="forbidden")
    ) is None


def test_a_denial_is_marked_as_denied_and_keeps_the_domain_action():
    async def run():
        entry = await record_denial(
            agency_id="ag-1",
            action=USER_ROLE_CHANGED,
            denial_code="privilege_escalation",
            actor_user_id="u-1",
            actor_role="agency-admin",
        )
        return entry

    entry = asyncio.run(run())
    assert entry.action == USER_ROLE_CHANGED, (
        "a `.denied` action name would split 'everything this actor did' across "
        f"two queries — got {entry.action!r}"
    )
    assert entry.detail["_outcome"] == "denied"
    assert entry.detail["_denial_code"] == "privilege_escalation"
    assert entry.detail["_actor_role"] == "agency-admin"


def test_a_success_has_no_outcome_key_so_old_entries_read_as_success():
    """Why `_outcome` lives in `detail` and absent means success: not one row
    written before denials existed had to be backfilled to stay correct."""

    async def run():
        return await record_action(
            None, agency_id="ag-1", action=CASE_CREATED, detail={"title": "x"}
        )

    entry = asyncio.run(run())
    assert "_outcome" not in entry.detail
    assert is_denied(entry.detail) is False


def test_denials_are_capped_per_actor_action_and_window():
    """A misconfigured client must not be able to bury a year of real activity
    under its own 403s — the chain is evidence a human has to read."""

    async def run():
        recorded = []
        for _ in range(DENIAL_CAP + 4):
            entry = await record_denial(
                agency_id="ag-cap",
                action=USER_ROLE_CHANGED,
                denial_code="privilege_escalation",
                actor_user_id="noisy-client",
            )
            recorded.append(entry)
        # A DIFFERENT action by the same actor has its own budget — one runaway
        # loop must not blind the trail to everything else that actor does.
        other = await record_denial(
            agency_id="ag-cap",
            action=USER_DEACTIVATED,
            denial_code="last_admin",
            actor_user_id="noisy-client",
        )
        return recorded, other

    recorded, other = asyncio.run(run())
    kept = [e for e in recorded if e is not None]
    assert len(kept) == DENIAL_CAP, (
        f"expected {DENIAL_CAP} recorded then silence, got {len(kept)} of "
        f"{len(recorded)} attempts"
    )
    assert all(e is None for e in recorded[DENIAL_CAP:]), "the cap must stop writing"
    assert other is not None, "a different action must not inherit the exhausted budget"

    # Suppression has to be VISIBLE, or a capped chain reads like a quiet one.
    assert kept[-1].detail["_denial_cap_reached"] is True
    assert "_denial_cap_reached" not in kept[0].detail
    assert "per worker" in kept[-1].detail["_denial_cap"], (
        "the marker must say the cap is per worker — with N workers the "
        "effective cap is DENIAL_CAP × N"
    )


def test_capped_denials_do_not_break_the_chain():
    """Suppression skips WRITES, not sequence numbers — nothing is left with a
    hole in it."""

    async def run():
        for _ in range(DENIAL_CAP + 3):
            await record_denial(
                agency_id="ag-cap2", action=USER_ROLE_CHANGED,
                denial_code="privilege_escalation", actor_user_id="noisy",
            )
        await record_action(None, agency_id="ag-cap2", action=CASE_CREATED)
        return await _memory_repository().verify_chain(agency_id="ag-cap2")

    ok, broken_at = asyncio.run(run())
    assert ok is True, f"chain broke at {broken_at} after capped denials"
