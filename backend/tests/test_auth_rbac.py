"""RBAC gating on sensitive endpoints + GET /api/config shape (P5).

Protected (401 without Bearer): POST /api/sessions, POST /api/entities/{id}/review,
POST /api/actions/generate, POST /api/actions/{id}/dispatch, and — as of P-4a
(docs/Persistence-Plan.md) — the INFILTRATE read routes that touch the repo:
GET /api/sessions(/{id}(/messages|/audio/{seq})?)?, GET /api/entities,
GET /api/syndicates. P-3 adds GET /api/actions/{id} to that list (UNCOVER's
one read route with a per-agency identity — see the module for the deliberate
exceptions below). P-5 adds GET /api/documents/{id}: the frontend now fetches
the PDF with JS (Bearer attached) and builds a blob URL, so the old "plain
<a href> can't carry a header" excuse is gone and the route is protected like
every other repo-backed read route.
Dispatch is additionally role-gated (403 for bank/exchange compliance).
Other read-only demo endpoints (GET /api/personas, /api/metrics/response,
/api/bridge/sankey, /api/config) stay open — GET /api/metrics/response
deliberately so even post-P-3 (see its docstring in app/uncover/router.py for
why: it's a cross-agency demo view — still 401s under persistence=postgres
via the repo factory itself, just not via an explicit route-level Depends).
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
    for path in ("/api/personas", "/api/metrics/response",
                 "/api/bridge/sankey", "/api/config"):
        assert client.get(path).status_code == 200, path


def test_infiltrate_read_endpoints_require_auth():
    """P-4a: INFILTRATE read routes that touch the repo now require identity —
    401 with no Bearer, 200 once one is presented."""
    for path in ("/api/sessions", "/api/syndicates"):
        r = client.get(path)
        assert r.status_code == 401, path
        assert r.json()["error"]["code"] == "missing_token", path
        r2 = client.get(path, headers=bearer())
        assert r2.status_code == 200, path


def test_uncover_get_action_requires_auth():
    """P-3: GET /api/actions/{id} touches the repo, so it now requires
    identity too (mirrors P-4a) — 401 with no Bearer, 200 once one is
    presented."""
    from app.uncover import service
    from app.uncover.notifications import MockNotificationSink

    service.reset_stores()
    MockNotificationSink.reset()
    try:
        headers = bearer()
        gen = client.post("/api/actions/generate", json=GENERATE_BODY, headers=headers)
        assert gen.status_code == 201, gen.text
        action_id = gen.json()["id"]

        r = client.get(f"/api/actions/{action_id}")
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "missing_token"

        r2 = client.get(f"/api/actions/{action_id}", headers=headers)
        assert r2.status_code == 200
        assert r2.json()["id"] == action_id
    finally:
        service.reset_stores()
        MockNotificationSink.reset()


def test_uncover_get_document_requires_auth():
    """P-5: GET /api/documents/{id} touches the repo, so it now requires
    identity too (mirrors P-4a / P-3) — 401 with no Bearer, 200 once one is
    presented."""
    from app.uncover import service
    from app.uncover.notifications import MockNotificationSink

    service.reset_stores()
    MockNotificationSink.reset()
    try:
        headers = bearer()
        gen = client.post("/api/actions/generate", json=GENERATE_BODY, headers=headers)
        assert gen.status_code == 201, gen.text
        doc = gen.json()["documents"][0]

        r = client.get(doc["download_url"])
        assert r.status_code == 401
        assert r.json()["error"]["code"] == "missing_token"

        r2 = client.get(doc["download_url"], headers=headers)
        assert r2.status_code == 200
        assert r2.headers["content-type"] == "application/pdf"
    finally:
        service.reset_stores()
        MockNotificationSink.reset()


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


def test_config_voice_section_has_no_secrets():
    """#15: GET /api/config exposes the TTS provider + which providers/keys are
    wired — as booleans/labels only. The raw key values must never appear,
    even when they ARE configured server-side."""
    settings = get_settings()
    settings.elevenlabs_api_key = "sk-el-super-secret-12345"
    settings.google_tts_api_key = "AIzaSy-super-secret-67890"
    settings.llm_api_key = "sk-ant-super-secret-abcde"
    try:
        r = client.get("/api/config")
        assert r.status_code == 200
        body = r.json()

        assert body["tts_provider"] == "browser"
        assert set(body["tts_providers"]) >= {"google", "higgsfield", "elevenlabs"}
        assert body["live_keys"] == {"elevenlabs": True, "google": True, "llm": True}
        assert set(body["voice_defaults"]) == {"caller_number", "greeting"}

        # The secret values themselves must never leave the API.
        raw = r.text
        assert "sk-el-super-secret-12345" not in raw
        assert "AIzaSy-super-secret-67890" not in raw
        assert "sk-ant-super-secret-abcde" not in raw
    finally:
        settings.elevenlabs_api_key = ""
        settings.google_tts_api_key = ""
        settings.llm_api_key = ""


def test_config_voice_keys_absent_by_default(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # fallback llm key source
    body = client.get("/api/config").json()
    assert body["live_keys"] == {"elevenlabs": False, "google": False, "llm": False}
