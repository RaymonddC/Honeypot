"""The crypto surface can be switched off — and off means ABSENT, not forbidden.

`ITTU_CRYPTO_ENABLED=false` hides TAKEDOWN in full and the crypto half of TRACE.
This is a product decision, not a permission: it applies to everyone, including a
role holding every capability.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, get_settings

Settings.model_config["env_file"] = None


def _client(*, crypto: bool) -> TestClient:
    os.environ["ITTU_PERSISTENCE"] = "memory"
    os.environ.pop("ITTU_MODULE_MODES", None)
    os.environ["ITTU_CRYPTO_ENABLED"] = "true" if crypto else "false"
    get_settings.cache_clear()
    from app.main import create_app

    return TestClient(create_app())


@pytest.fixture(autouse=True)
def _restore():
    """Undo BOTH kinds of global state these tests touch.

    The env var and the settings cache are obvious. The user store is not:
    logging in CREATES a demo user in the shared in-memory store, and leaving a
    second Bareskrim admin behind makes UAM's "last active admin" guard see two
    where its test expects one. That failed in the full suite while passing
    alone — the worst shape of test pollution, and the second time this exact
    trap has been hit in this codebase.
    """
    from app.core import auth as auth_mod

    users_before = dict(auth_mod._USERS)
    yield
    auth_mod._USERS.clear()
    auth_mod._USERS.update(users_before)
    os.environ.pop("ITTU_CRYPTO_ENABLED", None)
    get_settings.cache_clear()


def _bearer(client: TestClient, role: str = "platform-admin") -> dict[str, str]:
    token = client.post(
        "/api/auth/login", json={"agency_id": "bareskrim", "role": role}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


CRYPTO_ROUTES = [
    ("GET", "/api/wallets/TRabc/risk"),
    ("GET", "/api/wallets/TRabc/graph"),
    ("POST", "/api/investigate"),
    ("GET", "/api/bridge/sankey"),
    ("GET", "/api/bridge/correlations"),
]

FIAT_ROUTES = [
    ("GET", "/api/bridge/accounts"),
    ("GET", "/api/bridge/mules"),
]


def test_crypto_routes_are_absent_when_the_flag_is_off():
    """404, not 403. 403 would advertise that a crypto feature exists and is
    being withheld — the question this deployment is choosing not to answer."""
    with _client(crypto=False) as c:
        headers = _bearer(c)
        for method, path in CRYPTO_ROUTES:
            kwargs = {"json": {}} if method == "POST" else {}
            r = c.request(method, path, headers=headers, **kwargs)
            assert r.status_code == 404, f"{path} answered {r.status_code}"
            assert r.json()["error"]["code"] == "feature_disabled", path


def test_the_fiat_side_of_trace_survives():
    """"Bank accounts only" has to still work. A mule ACCOUNT is a bank account,
    and hiding crypto must not take the fiat investigation with it."""
    with _client(crypto=False) as c:
        headers = _bearer(c)
        for method, path in FIAT_ROUTES:
            assert c.request(method, path, headers=headers).status_code < 400, path


def test_a_platform_admin_is_refused_too():
    """A feature gate, not a permission gate. The most privileged role in the
    system still gets 404 — there is nothing to be granted."""
    with _client(crypto=False) as c:
        r = c.get("/api/wallets/TRabc/risk", headers=_bearer(c, "platform-admin"))
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "feature_disabled"


def test_turning_it_on_reaches_the_real_handlers():
    """The gate is the only thing in the way — with it on, these routes fail (or
    succeed) on their own merits rather than on the flag."""
    with _client(crypto=True) as c:
        headers = _bearer(c)
        r = c.get("/api/wallets/TRabc/risk", headers=headers)
        assert r.status_code != 404 or r.json()["error"]["code"] != "feature_disabled"
        assert c.get("/api/bridge/sankey", headers=headers).status_code < 400


def test_the_config_endpoint_tells_the_ui_which_way_it_is_set():
    """The frontend hides the Takedown nav from this. Unauthenticated, like the
    MODE badge: it describes the product, not anyone's access."""
    with _client(crypto=False) as c:
        assert c.get("/api/config").json()["crypto_enabled"] is False
    with _client(crypto=True) as c:
        assert c.get("/api/config").json()["crypto_enabled"] is True


def test_the_default_is_off():
    """A deployment that says nothing does not offer crypto. The safe direction
    for a feature that is deliberately withheld."""
    os.environ.pop("ITTU_CRYPTO_ENABLED", None)
    get_settings.cache_clear()
    assert get_settings().crypto_enabled is False
