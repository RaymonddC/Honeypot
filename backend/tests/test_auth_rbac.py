"""RBAC gating on sensitive endpoints + GET /api/config shape (P5).

Protected (401 without Bearer): POST /api/sessions, POST /api/entities/{id}/review,
POST /api/actions/generate, POST /api/actions/{id}/dispatch.
Dispatch is additionally role-gated (403 for bank/exchange compliance).
Read-only demo endpoints stay open.
"""

import pytest
from fastapi.testclient import TestClient

from app.core.config import MODULES, get_settings
from app.main import app
from tests.conftest import SOURCE, bearer

client = TestClient(app)

GENERATE_BODY = {
    "case_id": "CASE-2026-0142",
    "crime_type": "investment",
    "entities": [{"type": "crypto_wallet", "value": SOURCE, "chain": "tron"}],
    "outputs": ["freeze"],
}


# --- 401 without a token ----------------------------------------------------------


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("post", "/api/sessions", {}),
        ("post", "/api/entities/ent_x/review", {"status": "confirmed"}),
        ("post", "/api/actions/generate", GENERATE_BODY),
        ("post", "/api/actions/act_x/dispatch", None),
    ],
)
def test_protected_endpoints_401_without_token(method, path, body):
    r = getattr(client, method)(path, json=body)
    assert r.status_code == 401
    assert r.json()["error"]["code"] == "missing_token"


def test_read_endpoints_stay_open():
    for path in ("/api/sessions", "/api/personas", "/api/syndicates",
                 "/api/metrics/response", "/api/bridge/sankey", "/api/config"):
        assert client.get(path).status_code == 200, path


# --- role gating: dispatch --------------------------------------------------------


@pytest.mark.parametrize("role,agency", [
    ("bank-compliance", "bank-bca"),
    ("exchange-compliance", "indodax"),
])
def test_dispatch_403_for_compliance_roles(role, agency):
    r = client.post("/api/actions/act_x/dispatch", headers=bearer(role, agency))
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize("role,agency", [
    ("police-investigator", "bareskrim"),
    ("regulator-analyst", "ppatk"),
    ("platform-admin", "ppatk"),
])
def test_dispatch_passes_role_gate(role, agency):
    # authz passes → the request reaches the handler (404: unknown action id)
    r = client.post("/api/actions/act_x/dispatch", headers=bearer(role, agency))
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "action_not_found"


def test_compliance_can_generate_but_not_dispatch():
    from app.uncover import service
    from app.uncover.notifications import MockNotificationSink

    service.reset_stores()
    MockNotificationSink.reset()
    try:
        headers = bearer("bank-compliance", "bank-bca")
        b = client.post("/api/actions/generate", json=GENERATE_BODY, headers=headers)
        assert b.status_code == 201
        r = client.post(f"/api/actions/{b.json()['id']}/dispatch", headers=headers)
        assert r.status_code == 403
    finally:
        service.reset_stores()
        MockNotificationSink.reset()


# --- GET /api/config ---------------------------------------------------------------


def test_config_shape_all_modules_poc_by_default():
    body = client.get("/api/config").json()
    assert body["mode"] == "poc"
    assert set(body["modules"]) == set(MODULES)
    assert set(MODULES) == {"infiltrate", "trace", "takedown", "uncover", "intel", "auth"}
    assert all(mode == "poc" for mode in body["modules"].values())

    adapters = body["adapters"]
    assert {a["boundary"] for a in adapters} >= {
        "blockchain", "fiat", "llm", "channel", "notification",
    }
    for a in adapters:
        assert set(a) == {"boundary", "module", "mode", "impl", "active"}
        assert a["mode"] in ("poc", "live")
        # POC everywhere → exactly the poc impls are active
        assert a["active"] is (a["mode"] == "poc")
    # both impls are registered per boundary (POC + LIVE)
    blockchain = {a["mode"]: a for a in adapters if a["boundary"] == "blockchain"}
    assert blockchain["poc"]["impl"] == "CachedTronAdapter"
    assert blockchain["poc"]["module"] == "takedown"
    assert set(blockchain) == {"poc", "live"}


def test_config_reflects_module_mode_override():
    settings = get_settings()
    settings.module_modes["takedown"] = "live"
    try:
        body = client.get("/api/config").json()
        assert body["mode"] == "poc"  # global default untouched
        assert body["modules"]["takedown"] == "live"
        assert body["modules"]["trace"] == "poc"
        blockchain = {a["mode"]: a for a in body["adapters"] if a["boundary"] == "blockchain"}
        assert blockchain["live"]["active"] is True   # TronscanAdapter now selected
        assert blockchain["poc"]["active"] is False
        fiat = {a["mode"]: a for a in body["adapters"] if a["boundary"] == "fiat"}
        assert fiat["poc"]["active"] is True          # trace still POC
    finally:
        settings.module_modes.pop("takedown", None)
