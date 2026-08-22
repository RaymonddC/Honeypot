"""User access management — GET/POST /api/users, PATCH /api/users/{id}.

The point of this module is revocation and privilege containment, so the tests
are written against the ways an access-control API actually fails in practice:
a deactivated account that can still get in, an admin who can reach into
another tenant, an admin who can promote themselves across the tenant boundary,
and an admin who can lock everyone (including themselves) out. Each of those is
unrecoverable from inside the product, so each gets a test.

Memory persistence (the suite default). ``_USERS`` is process-global module
state, so every test restores it — otherwise a deactivated user leaks into the
next test as a mystery 401.
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core import auth as auth_mod
from app.core.audit import reset_audit_store
from app.core.auth import find_agency, mint_token, upsert_demo_user
from app.main import app

client = TestClient(app)

BARESKRIM = find_agency("bareskrim")
PPATK = find_agency("ppatk")


@pytest.fixture(autouse=True)
def _isolate_user_store():
    """Snapshot/restore the in-process user store and the audit chain."""
    snapshot = dict(auth_mod._USERS)
    reset_audit_store()
    yield
    auth_mod._USERS.clear()
    auth_mod._USERS.update(snapshot)
    reset_audit_store()


def _auth(role: str = "agency-admin", agency: str = "bareskrim") -> dict[str, str]:
    user = upsert_demo_user(find_agency(agency), role)
    token, _ = mint_token(user)
    return {"Authorization": f"Bearer {token}"}


def _headers_for(user) -> dict[str, str]:
    token, _ = mint_token(user)
    return {"Authorization": f"Bearer {token}"}


def _create(headers, email="baru@bareskrim.polri.go.id", role="police-investigator", **extra):
    return client.post(
        "/api/users",
        json={"email": email, "name": "Pengguna Baru", "role": role, **extra},
        headers=headers,
    )


def _audit_actions(headers) -> list[str]:
    return [e["action"] for e in client.get("/api/audit", headers=headers).json()["entries"]]


# --- access to the API itself -------------------------------------------------


def test_the_admin_api_is_closed_to_anonymous_and_non_admin_callers():
    assert client.get("/api/users").status_code == 401
    assert client.get("/api/users", headers=_auth("police-investigator")).status_code == 403
    assert _create(_auth("police-investigator")).status_code == 403


def test_listing_shows_this_agency_only():
    listed = client.get("/api/users", headers=_auth()).json()
    agencies = {u["agency_id"] for u in listed}
    assert agencies == {str(BARESKRIM.id)}
    assert any(u["email"] == "budi@bareskrim.polri.go.id" for u in listed)


# --- provisioning -------------------------------------------------------------


def test_creating_a_user_returns_them_active_and_lists_them():
    r = _create(_auth())
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["is_active"] is True
    assert created["agency_id"] == str(BARESKRIM.id)
    assert created["email"] == "baru@bareskrim.polri.go.id"

    emails = [u["email"] for u in client.get("/api/users", headers=_auth()).json()]
    assert created["email"] in emails


def test_duplicate_email_is_refused_rather_than_silently_reassigned():
    _create(_auth())
    again = _create(_auth())
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "user_exists"


def test_email_shape_is_validated():
    assert _create(_auth(), email="not-an-email").status_code == 422


# --- privilege containment ----------------------------------------------------


def test_an_agency_admin_cannot_mint_a_platform_admin():
    """The whole tenant boundary rests on platform-admin being unreachable from
    inside an agency — if an agency-admin can grant it, the boundary is advisory."""
    r = _create(_auth(), email="escalate@bareskrim.polri.go.id", role="platform-admin")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "privilege_escalation"


def test_an_agency_admin_cannot_promote_an_existing_user_to_platform_admin():
    created = _create(_auth()).json()
    r = client.patch(
        f"/api/users/{created['id']}", json={"role": "platform-admin"}, headers=_auth()
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "privilege_escalation"


def test_a_platform_admin_may_grant_platform_admin():
    created = _create(_auth()).json()
    r = client.patch(
        f"/api/users/{created['id']}",
        json={"role": "platform-admin"},
        headers=_auth("platform-admin", "ppatk"),
    )
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "platform-admin"


# --- the agency boundary ------------------------------------------------------


def test_an_agency_admin_cannot_read_another_agencys_users():
    r = client.get(f"/api/users?agency_id={PPATK.id}", headers=_auth())
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "cross_agency_forbidden"


def test_an_agency_admin_cannot_modify_another_agencys_user():
    sari = auth_mod.find_user_by_email("sari@ppatk.go.id")
    r = client.patch(
        f"/api/users/{sari.id}", json={"is_active": False}, headers=_auth()
    )
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "cross_agency_forbidden"
    assert auth_mod.get_user(str(sari.id)).is_active is True, "must not have been applied"


def test_an_agency_admin_cannot_provision_into_another_agency():
    r = _create(_auth(), email="planted@ppatk.go.id", agency_id=str(PPATK.id))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "cross_agency_forbidden"


def test_a_platform_admin_may_administer_another_agency():
    admin = _auth("platform-admin", "ppatk")
    listed = client.get(f"/api/users?agency_id={BARESKRIM.id}", headers=admin).json()
    assert {u["agency_id"] for u in listed} == {str(BARESKRIM.id)}


def test_unknown_user_is_a_404_not_a_500():
    r = client.patch(
        f"/api/users/{uuid.uuid4()}", json={"is_active": False}, headers=_auth()
    )
    assert r.status_code == 404


def test_an_empty_patch_is_refused():
    created = _create(_auth()).json()
    assert client.patch(f"/api/users/{created['id']}", json={}, headers=_auth()).status_code == 422


# --- revocation actually revokes ---------------------------------------------


def test_a_deactivated_user_cannot_log_in():
    """Blocking token ISSUANCE is the half of revocation that always works —
    request auth is pure JWT and does not read the database."""
    budi = auth_mod.find_user_by_email("budi@bareskrim.polri.go.id")
    r = client.patch(f"/api/users/{budi.id}", json={"is_active": False}, headers=_auth())
    assert r.status_code == 200, r.text
    assert r.json()["is_active"] is False

    login = client.post(
        "/api/auth/login", json={"agency": "bareskrim", "role": "police-investigator"}
    )
    assert login.status_code == 403
    assert login.json()["error"]["code"] == "account_deactivated"


def test_a_deactivated_user_with_a_live_token_is_rejected():
    budi = auth_mod.find_user_by_email("budi@bareskrim.polri.go.id")
    headers = _headers_for(budi)
    assert client.get("/api/auth/me", headers=headers).status_code == 200

    client.patch(f"/api/users/{budi.id}", json={"is_active": False}, headers=_auth())

    after = client.get("/api/auth/me", headers=headers)
    assert after.status_code == 401
    assert after.json()["error"]["code"] == "account_deactivated"


def test_reactivating_restores_access():
    budi = auth_mod.find_user_by_email("budi@bareskrim.polri.go.id")
    client.patch(f"/api/users/{budi.id}", json={"is_active": False}, headers=_auth())
    client.patch(f"/api/users/{budi.id}", json={"is_active": True}, headers=_auth())
    assert client.get("/api/auth/me", headers=_headers_for(budi)).status_code == 200


# --- lockout guards -----------------------------------------------------------


def test_an_admin_cannot_deactivate_themselves():
    me = upsert_demo_user(BARESKRIM, "agency-admin")
    r = client.patch(f"/api/users/{me.id}", json={"is_active": False}, headers=_auth())
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "self_lockout"
    assert auth_mod.get_user(str(me.id)).is_active is True


def test_an_admin_cannot_demote_themselves():
    me = upsert_demo_user(BARESKRIM, "agency-admin")
    r = client.patch(
        f"/api/users/{me.id}", json={"role": "police-investigator"}, headers=_auth()
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "self_lockout"


def test_the_last_active_admin_of_an_agency_cannot_be_removed():
    """A platform-admin can reach in — but not to the point of leaving an agency
    with nobody who can restore access."""
    only_admin = upsert_demo_user(BARESKRIM, "agency-admin")
    platform = _auth("platform-admin", "ppatk")

    r = client.patch(
        f"/api/users/{only_admin.id}", json={"is_active": False}, headers=platform
    )
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "last_admin"

    # …and once a second admin exists, the first can go.
    second = _create(
        platform,
        email="wakil@bareskrim.polri.go.id",
        role="agency-admin",
        agency_id=str(BARESKRIM.id),
    )
    assert second.status_code == 201, second.text
    ok = client.patch(
        f"/api/users/{only_admin.id}", json={"is_active": False}, headers=platform
    )
    assert ok.status_code == 200, ok.text


# --- the trail ----------------------------------------------------------------


def test_every_mutation_lands_in_the_audit_trail():
    admin = _auth()
    created = _create(admin).json()
    client.patch(f"/api/users/{created['id']}", json={"role": "bank-compliance"}, headers=admin)
    client.patch(f"/api/users/{created['id']}", json={"is_active": False}, headers=admin)
    client.patch(f"/api/users/{created['id']}", json={"is_active": True}, headers=admin)

    entries = client.get("/api/audit", headers=admin).json()
    actions = [e["action"] for e in entries["entries"]]
    for expected in (
        "user.created", "user.role_changed", "user.deactivated", "user.reactivated"
    ):
        assert expected in actions, f"{expected} must be audited"
    assert entries["chain_ok"] is True

    change = next(e for e in entries["entries"] if e["action"] == "user.role_changed")
    # before→after: "who holds which power now" is unanswerable from a log that
    # only records what it changed TO.
    assert change["detail"]["from"] == "police-investigator"
    assert change["detail"]["to"] == "bank-compliance"
    assert change["target_id"] == created["id"]
    assert change["detail"]["_target"] == created["email"]


def test_a_cross_agency_change_is_chained_under_the_target_agency():
    """The agency whose access list changed must be able to see the change —
    and see that it came from outside."""
    platform = _auth("platform-admin", "ppatk")
    _create(platform, email="titipan@bareskrim.polri.go.id", agency_id=str(BARESKRIM.id))

    local = client.get("/api/audit", headers=_auth()).json()
    entry = next(e for e in local["entries"] if e["action"] == "user.created")
    assert entry["detail"]["acting_agency_id"] == str(PPATK.id)


def _entries(headers) -> list[dict]:
    return client.get("/api/audit", headers=headers).json()["entries"]


def test_a_refused_change_is_recorded_as_denied_never_as_done():
    """Nothing happened, so nothing may be logged as HAVING happened.

    This used to assert the refusal left no entry at all. It now leaves one —
    the whole point of auditing denials — so the invariant is the stronger one:
    the attempt is on the record, and it is unmistakably marked as refused. An
    entry that reads like a successful platform-admin grant would be far worse
    than no entry, which is why this asserts on the outcome, not just presence.
    """
    admin = _auth()
    r = _create(admin, email="escalate@bareskrim.polri.go.id", role="platform-admin")
    assert r.status_code == 403, r.text

    created = [e for e in _entries(admin) if e["action"] == "user.created"]
    assert len(created) == 1, f"expected exactly one entry, got {created}"
    entry = created[0]
    assert entry["detail"]["_outcome"] == "denied", (
        f"a refused grant must not read as done — detail was {entry['detail']}"
    )
    assert entry["detail"]["_denial_code"] == "privilege_escalation"
    assert entry["detail"]["attempted_role"] == "platform-admin"
    assert entry["detail"]["_actor_role"] == "agency-admin"
    # And the user really was not created.
    assert "escalate@bareskrim.polri.go.id" not in [
        u["email"] for u in client.get("/api/users", headers=admin).json()
    ]


def test_each_uam_guard_records_its_denial_under_the_domain_action():
    """All five guards, each keeping the action name of what was attempted.

    A parallel vocabulary (`user.role_changed.denied`) would split "everything
    this admin did" across two queries — see app/core/audit.py's record_denial.
    """
    admin = _auth()
    me = upsert_demo_user(BARESKRIM, "agency-admin")
    victim = _create(admin).json()

    # 1. privilege_escalation, on a PATCH this time (the POST is covered above)
    client.patch(
        f"/api/users/{victim['id']}", json={"role": "platform-admin"}, headers=admin
    )
    # 2. self_lockout
    client.patch(f"/api/users/{me.id}", json={"is_active": False}, headers=admin)
    # 3. last_admin — a second agency-admin, then remove the original
    other_admin = _create(
        admin, email="admin2@bareskrim.polri.go.id", role="agency-admin"
    ).json()
    client.patch(f"/api/users/{other_admin['id']}", json={"is_active": False}, headers=admin)
    # (that one succeeds — two admins exist; now the survivor is the last)
    client.patch(f"/api/users/{other_admin['id']}", json={"is_active": True}, headers=admin)
    # 4. cross_agency_forbidden
    client.get(f"/api/users?agency_id={PPATK.id}", headers=admin)
    # 5. user_not_found
    client.patch(
        f"/api/users/{uuid.uuid4()}", json={"role": "bank-compliance"}, headers=admin
    )

    denied = {
        (e["action"], e["detail"]["_denial_code"])
        for e in _entries(admin)
        if e["detail"].get("_outcome") == "denied"
    }
    for expected in (
        ("user.role_changed", "privilege_escalation"),
        ("user.deactivated", "self_lockout"),
        ("access.forbidden", "cross_agency_forbidden"),
        ("user.role_changed", "user_not_found"),
    ):
        assert expected in denied, f"{expected} not recorded — got {sorted(denied)}"
    assert client.get("/api/audit", headers=admin).json()["chain_ok"] is True


def test_the_last_admin_refusal_is_recorded_as_denied():
    """Split out from the guard sweep because reaching `last_admin` at all takes
    care: for a SELF-edit `self_lockout` fires first and masks it, so the only
    way in is an outsider — a platform-admin — removing another agency's final
    admin. A test that quietly hit self_lockout instead would still be green
    while proving nothing, which is why the code is asserted explicitly.
    """
    platform = _auth("platform-admin", "ppatk")
    last = upsert_demo_user(BARESKRIM, "agency-admin")

    # Leave Bareskrim with exactly one active admin, or the guard never fires.
    listing = client.get(f"/api/users?agency_id={BARESKRIM.id}", headers=platform).json()
    for u in listing:
        if u["role"] in ("agency-admin", "platform-admin") and u["id"] != str(last.id):
            client.patch(
                f"/api/users/{u['id']}",
                json={"role": "police-investigator"},
                headers=platform,
            )
    remaining = [
        u for u in client.get(f"/api/users?agency_id={BARESKRIM.id}", headers=platform).json()
        if u["role"] in ("agency-admin", "platform-admin") and u["is_active"]
    ]
    assert len(remaining) == 1, f"setup failed — {len(remaining)} active admins: {remaining}"

    r = client.patch(f"/api/users/{last.id}", json={"is_active": False}, headers=platform)
    assert r.status_code == 409, r.text
    assert r.json()["error"]["code"] == "last_admin", r.text

    # Chained under the ACTOR's agency (PPATK), not the target's.
    denied = [
        e for e in _entries(platform)
        if e["detail"].get("_denial_code") == "last_admin"
    ]
    assert len(denied) == 1, f"expected one last_admin entry, got {denied}"
    assert denied[0]["action"] == "user.deactivated"
    assert denied[0]["detail"]["_outcome"] == "denied"
    assert denied[0]["target_id"] == str(last.id)


def test_a_non_admin_probing_the_admin_api_leaves_a_trace():
    """The signal the whole item exists for: an authenticated user reaching for
    a door their role does not open. It used to vanish entirely."""
    investigator = _auth("police-investigator")
    assert client.get("/api/users", headers=investigator).status_code == 403

    entries = _entries(investigator)
    forbidden = [e for e in entries if e["action"] == "access.forbidden"]
    assert len(forbidden) == 1, (
        f"expected exactly one entry for one refused request, got {len(forbidden)}: "
        f"{[e['detail'] for e in forbidden]}"
    )
    d = forbidden[0]["detail"]
    assert d["_outcome"] == "denied" and d["_denial_code"] == "forbidden"
    assert d["path"] == "/api/users" and d["method"] == "GET"
    assert d["_actor_role"] == "police-investigator"
    assert "agency-admin" in d["requires"]


def test_denials_do_not_leak_across_agencies():
    """A refusal is chained under the ACTOR's agency, not the target's — an
    outsider's rejected attempt must not be appendable to another tenant's
    evidentiary chain."""
    platform = _auth("platform-admin", "ppatk")
    # A platform-admin CAN cross agencies, so use a plain agency-admin instead.
    agency_admin = _auth("agency-admin", "ppatk")
    assert client.get(
        f"/api/users?agency_id={BARESKRIM.id}", headers=agency_admin
    ).status_code == 403

    target_side = [
        e for e in _entries(_auth("agency-admin", "bareskrim"))
        if e["detail"].get("_outcome") == "denied"
    ]
    assert target_side == [], (
        "the refused agency's chain must not carry an outsider's attempt — "
        f"found {target_side}"
    )
    actor_side = [
        e for e in _entries(platform) if e["detail"].get("_outcome") == "denied"
    ]
    assert any(
        e["detail"]["_denial_code"] == "cross_agency_forbidden" for e in actor_side
    ), f"the actor's own agency must carry it — got {actor_side}"
