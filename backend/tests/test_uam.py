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


def test_a_refused_change_leaves_no_audit_entry():
    """Nothing happened, so nothing may be logged as having happened."""
    admin = _auth()
    _create(admin, email="escalate@bareskrim.polri.go.id", role="platform-admin")
    assert "user.created" not in _audit_actions(admin)
