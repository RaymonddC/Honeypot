"""AUTH API — demo login → JWT → /me, token lifecycle, MODE gating (P5).

TestClient, no DB, no network. POC demo login is the default path; the Google
LIVE path fails closed in POC and is stubbed (501) when google-auth is absent.
"""

import importlib.util
import time
from unittest.mock import patch

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app.core.auth import find_agency, mint_token, upsert_demo_user
from app.core.config import get_settings
from app.main import app

client = TestClient(app)

BARESKRIM_ID = "a190a9ca-d827-5c3a-a625-b788d9ab03c9"


@pytest.fixture
def auth_live():
    """Flip the auth module to LIVE for one test (per-module MODE override)."""
    settings = get_settings()
    settings.module_modes["auth"] = "live"
    yield
    settings.module_modes.pop("auth", None)


# --- demo login ---------------------------------------------------------------


def test_login_default_agency_returns_jwt_and_identity():
    r = client.post("/api/auth/login", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == get_settings().jwt_ttl_seconds
    assert body["agency"]["slug"] == "bareskrim"
    assert body["agency"]["id"] == BARESKRIM_ID
    assert body["agency"]["type"] == "police"
    assert body["role"] == "police-investigator"  # default role for police
    assert body["user"]["agency_id"] == BARESKRIM_ID
    # the JWT carries exactly the contract claims
    claims = pyjwt.decode(body["token"], options={"verify_signature": False})
    assert {"sub", "agency_id", "role", "exp"} <= set(claims)
    assert claims["agency_id"] == BARESKRIM_ID
    assert claims["role"] == "police-investigator"


@pytest.mark.parametrize(
    "ref,slug,default_role",
    [
        ("ppatk", "ppatk", "regulator-analyst"),
        ("84cb96f6-6dfb-5e5f-9fbd-d06ce68e7772", "ppatk", "regulator-analyst"),  # by uuid
        ("bank-bca", "bank-bca", "bank-compliance"),
        ("indodax", "indodax", "exchange-compliance"),
    ],
)
def test_login_by_agency_id_or_slug(ref, slug, default_role):
    body = client.post("/api/auth/login", json={"agency_id": ref}).json()
    assert body["agency"]["slug"] == slug
    assert body["role"] == default_role


def test_login_by_agency_type_and_explicit_role():
    body = client.post(
        "/api/auth/login", json={"agency_type": "regulator", "role": "agency-admin"}
    ).json()
    assert body["agency"]["type"] == "regulator"
    assert body["role"] == "agency-admin"
    assert body["user"]["role"] == "agency-admin"


def test_login_unknown_agency_404():
    r = client.post("/api/auth/login", json={"agency_id": "interpol"})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "agency_not_found"


def test_login_unknown_role_422():
    assert client.post("/api/auth/login", json={"role": "supreme-leader"}).status_code == 422


# --- /auth/me + token lifecycle -------------------------------------------------


def test_login_token_drives_me():
    login = client.post("/api/auth/login", json={"agency_id": "ppatk"}).json()
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {login['token']}"})
    assert r.status_code == 200
    me = r.json()
    assert me["user"] == login["user"]
    assert me["agency"] == login["agency"]
    assert me["role"] == "regulator-analyst"


def test_me_without_token_401():
    r = client.get("/api/auth/me")
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "missing_token"
    assert r.headers["www-authenticate"] == "Bearer"


def test_me_with_garbage_token_401():
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_token"


def test_me_with_expired_token_401():
    user = upsert_demo_user(find_agency("bareskrim"), "police-investigator")
    token, _ = mint_token(user, ttl_seconds=-10)
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "token_expired"


def test_me_with_wrong_signature_401():
    user = upsert_demo_user(find_agency("bareskrim"), "police-investigator")
    now = int(time.time())
    forged = pyjwt.encode(
        {"sub": str(user.id), "agency_id": str(user.agency_id),
         "role": "platform-admin", "exp": now + 600},
        "attacker-secret-thats-long-enough-for-hs256",
        algorithm="HS256",
    )
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {forged}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_token"


def test_token_missing_required_claim_401():
    now = int(time.time())
    incomplete = pyjwt.encode(  # no agency_id claim
        {"sub": "abc", "role": "platform-admin", "exp": now + 600},
        get_settings().jwt_secret,
        algorithm="HS256",
    )
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {incomplete}"})
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_token"


# --- MODE gating: POC ⇄ LIVE login paths ----------------------------------------


def test_google_login_disabled_in_poc():
    r = client.post("/api/auth/google", json={"id_token": "whatever"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "google_login_disabled"


def test_demo_login_disabled_in_live(auth_live):
    r = client.post("/api/auth/login", json={})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "demo_login_disabled"


def _has_google_auth() -> bool:
    try:
        return importlib.util.find_spec("google.oauth2") is not None
    except ModuleNotFoundError:  # no `google` namespace package at all
        return False


def test_google_login_live_stub_or_verify(auth_live):
    r = client.post("/api/auth/google", json={"id_token": "not-a-google-token"})
    if not _has_google_auth():
        assert r.status_code == 501  # stub: google-auth not installed
        assert r.json()["error"]["code"] == "google_auth_unavailable"
    else:  # lib present: bogus token must fail verification, never mint a JWT
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "invalid_google_token"


# --- Google OAuth (P-4b) — id_token verification mocked; no real Google client ---
#
# There is no Google OAuth client ID or a real id_token available in this
# environment, so `google.oauth2.id_token.verify_oauth2_token` (the one call
# that actually talks to Google — fetching certs + verifying the JWT
# signature/aud/exp) is mocked at its import site. Everything past that call
# — provisioning lookup, JWT minting — is real, unmocked code.
_HAS_GOOGLE_AUTH = _has_google_auth()
_needs_google_auth = pytest.mark.skipif(
    not _HAS_GOOGLE_AUTH, reason="google-auth not installed"
)


@_needs_google_auth
def test_google_login_valid_token_provisioned_user_gets_jwt(auth_live):
    """A verified id_token for a provisioned email mints our JWT with that
    user's real (agency, role) — never a self-service default."""
    with patch("google.oauth2.id_token.verify_oauth2_token") as mock_verify:
        mock_verify.return_value = {
            "email": "budi@bareskrim.polri.go.id",
            "name": "Budi Santoso (Google)",
        }
        r = client.post("/api/auth/google", json={"id_token": "mock-valid-token"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "budi@bareskrim.polri.go.id"
    assert body["user"]["name"] == "Budi Santoso (Google)"  # refreshed from the Google profile
    assert body["role"] == "police-investigator"
    assert body["agency"]["slug"] == "bareskrim"
    claims = pyjwt.decode(body["token"], options={"verify_signature": False})
    assert claims["role"] == "police-investigator"
    assert claims["agency_id"] == BARESKRIM_ID


@_needs_google_auth
def test_google_login_unknown_email_403(auth_live):
    """A verified token for an email nobody provisioned is rejected — no
    self-service signup, matching the demo-login-only provisioning model."""
    with patch("google.oauth2.id_token.verify_oauth2_token") as mock_verify:
        mock_verify.return_value = {"email": "nobody@nowhere.example", "name": "Nobody"}
        r = client.post("/api/auth/google", json={"id_token": "mock-valid-token"})

    assert r.status_code == 403
    assert r.json()["error"]["code"] == "user_not_provisioned"


@_needs_google_auth
def test_google_login_bad_token_401(auth_live):
    """Verification failure (bad signature/expired/wrong aud/malformed) never
    mints a JWT — 401, not a silent fallthrough."""
    with patch(
        "google.oauth2.id_token.verify_oauth2_token",
        side_effect=ValueError("Token expired"),
    ):
        r = client.post("/api/auth/google", json={"id_token": "expired-token"})

    assert r.status_code == 401
    assert r.json()["error"]["code"] == "invalid_google_token"


def test_google_login_disabled_in_poc_even_with_a_would_be_valid_token():
    """MODE gate is checked BEFORE verification even runs — POC never mints a
    JWT from a Google token, valid or not (no mock needed: the route 403s
    before it ever imports google-auth)."""
    r = client.post("/api/auth/google", json={"id_token": "irrelevant"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "google_login_disabled"
