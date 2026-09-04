"""Role administration — and the guards that stop it locking everyone out.

A configurable permission system has one catastrophic failure mode: an edit that
leaves nobody able to administer anything. There is no way back from inside the
product, so these guards are the feature, not decoration around it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.roles.repository import InMemoryRoleRepository

client = TestClient(app)


@pytest.fixture(autouse=True)
def _fresh_policy(monkeypatch):
    """Each test starts from the seeded policy — these tests MUTATE it.

    Reset both sides, and via monkeypatch rather than module-level env edits: an
    earlier version set ITTU_PERSISTENCE and cleared the settings cache at import
    time, which leaked into every module that ran afterwards and made an
    unrelated UAM test fail in the full suite while passing alone. Global state
    changed at import is the hardest kind of pollution to trace.
    """
    from app.core import auth as auth_mod
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "persistence", "memory", raising=False)
    InMemoryRoleRepository.reset()

    # Logging in CREATES demo users in the shared in-memory store, and that
    # leaked: `bearer("agency-admin")` here left a second Bareskrim admin
    # behind, so UAM's "last active admin" guard correctly saw two and allowed a
    # deactivation its test expected to be refused. It passed alone and failed
    # in the suite — the worst shape of test pollution. Snapshot and restore.
    users_before = dict(auth_mod._USERS)
    yield
    auth_mod._USERS.clear()
    auth_mod._USERS.update(users_before)
    InMemoryRoleRepository.reset()


def bearer(role: str, agency: str = "bareskrim") -> dict[str, str]:
    token = client.post("/api/auth/login", json={"agency_id": agency, "role": role}).json()["token"]
    return {"Authorization": f"Bearer {token}"}


# --------------------------------------------------------------------------- #
# Who may administer roles
# --------------------------------------------------------------------------- #


def test_an_agency_admin_cannot_administer_roles():
    """core.roles has no agency_id — a role is GLOBAL. An agency administrator
    editing one would change what OTHER agencies' users can do, which is a
    tenant-isolation break wearing the clothes of a settings page."""
    r = client.get("/api/roles", headers=bearer("agency-admin"))
    assert r.status_code == 403
    assert r.json()["error"]["capability"] == "roles.admin"


def test_a_platform_admin_can():
    r = client.get("/api/roles", headers=bearer("platform-admin"))
    assert r.status_code == 200
    names = {row["name"] for row in r.json()}
    assert "police-investigator" in names


def test_capabilities_are_readable_by_anyone_signed_in():
    """The capability list describes the PRODUCT, not anyone's access, and the
    UI needs it to render. Nothing sensitive is in it."""
    r = client.get("/api/capabilities", headers=bearer("bank-compliance", "bank-bca"))
    assert r.status_code == 200
    keys = {c["key"] for c in r.json()}
    assert "honeypot.read" in keys
    assert all(c["description"] for c in r.json())


# --------------------------------------------------------------------------- #
# The lockout guards
# --------------------------------------------------------------------------- #


def test_an_edit_may_not_leave_nobody_able_to_administer_users():
    """THE guard. Strip `users.admin` from every role and no one can ever grant
    it again — the system becomes unadministerable with no path back."""
    admin = bearer("platform-admin")
    # agency-admin may lose it while platform-admin still holds it...
    assert client.patch(
        "/api/roles/agency-admin", json={"capabilities": ["case.write"]}, headers=admin
    ).status_code == 200
    # ...but the last holder may not.
    r = client.patch(
        "/api/roles/platform-admin", json={"capabilities": ["case.write"]}, headers=admin
    )
    assert r.status_code == 409, "the last users.admin was removed — nobody can administer anything"
    assert r.json()["error"]["code"] == "last_holder"
    assert "users.admin" in r.json()["error"]["message"]


def test_roles_admin_is_protected_the_same_way():
    """Losing `roles.admin` everywhere means the permission system can never be
    edited again — the same shape of dead end."""
    admin = bearer("platform-admin")
    r = client.patch(
        "/api/roles/platform-admin",
        json={"capabilities": ["case.write", "users.admin"]},
        headers=admin,
    )
    assert r.status_code == 409
    assert "roles.admin" in r.json()["error"]["message"]


def test_a_capability_this_build_does_not_enforce_is_refused():
    """Storing it would make the UI advertise a protection that does not exist —
    worse than not offering it at all."""
    r = client.post(
        "/api/roles",
        json={"name": "ghost", "capabilities": ["honeypot.launch_missiles"]},
        headers=bearer("platform-admin"),
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "unknown_capability"


def test_a_builtin_role_cannot_be_deleted():
    """The seed migration, ITTU_OAUTH_PROVISION and the demo login all reference
    these by NAME. Deleting one breaks them silently."""
    r = client.delete("/api/roles/police-investigator", headers=bearer("platform-admin"))
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "builtin_role"


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #


def test_a_custom_role_can_be_created_edited_and_deleted():
    admin = bearer("platform-admin")

    created = client.post(
        "/api/roles", json={"name": "fraud-analyst", "capabilities": ["case.write"]}, headers=admin
    )
    assert created.status_code == 201
    assert created.json()["capabilities"] == ["case.write"]
    assert created.json()["builtin"] is False

    edited = client.patch(
        "/api/roles/fraud-analyst",
        json={"capabilities": ["case.write", "dispatch.send"]},
        headers=admin,
    )
    assert edited.status_code == 200
    assert edited.json()["capabilities"] == ["case.write", "dispatch.send"]

    assert client.delete("/api/roles/fraud-analyst", headers=admin).status_code == 204
    assert client.get("/api/roles/nope", headers=admin).status_code in (404, 405)


def test_a_new_role_actually_grants_what_it_says():
    """The end-to-end property: creating a role and giving it a capability must
    change what someone holding that role can DO. Without this the admin screen
    is a form that edits a row nobody consults."""
    admin = bearer("platform-admin")
    client.post(
        "/api/roles", json={"name": "field-officer", "capabilities": []}, headers=admin
    )

    holder = bearer("field-officer")
    assert client.get("/api/sessions", headers=holder).status_code == 403, (
        "a role with no capabilities could still read honeypot transcripts"
    )

    # honeypot.read alone: enough to review transcripts, deliberately NOT enough
    # to start a session — the split is only real if it draws that line.
    client.patch(
        "/api/roles/field-officer",
        json={"capabilities": ["honeypot.read"]},
        headers=admin,
    )
    assert client.get("/api/sessions", headers=holder).status_code == 200, (
        "granting honeypot.read did not take effect — the resolver cache was "
        "not invalidated, or the guard is not reading the roles table"
    )
    assert client.post("/api/sessions", json={}, headers=holder).status_code == 403, (
        "honeypot.read alone allowed STARTING a session — the split is cosmetic "
        "if reading the record also authorises contacting a suspect"
    )


def test_a_duplicate_name_is_refused():
    admin = bearer("platform-admin")
    client.post("/api/roles", json={"name": "dup", "capabilities": []}, headers=admin)
    r = client.post("/api/roles", json={"name": "dup", "capabilities": []}, headers=admin)
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "role_exists"
