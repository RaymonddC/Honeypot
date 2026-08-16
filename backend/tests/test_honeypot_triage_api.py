"""Triage — placing a connected call into a case (phase 6, §5).

TestClient against the POC memory repos (no DB, no network). Triage owns no
storage: it is a view over ``intel.scam_sessions``, so these tests create a real
voice session through the honeypot API and then work it the way an investigator
would — list it, attach it, or promote it into a new case.

Agency isolation is NOT asserted here: the memory store is single-tenant by
construction, and the real guarantee is Postgres RLS over ``intel.scam_sessions``
(``test_rls_isolation.py``), which is where it is proven.
"""

import pytest
from fastapi.testclient import TestClient

from app.infiltrate import service as infiltrate_service
from app.main import app
from tests.conftest import bearer

client = TestClient(app)
client.headers.update(bearer())


@pytest.fixture(autouse=True)
def clean_store():
    infiltrate_service.reset_stores()
    yield
    infiltrate_service.reset_stores()


def _voice_session() -> dict:
    """A connected voice call with no case — exactly what lands in triage."""
    r = client.post("/api/sessions", json={"channel_type": "voice"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["case_id"] is None, "a fresh voice session must start unassigned"
    return body


def _case(title: str = "Existing case") -> str:
    r = client.post("/api/cases", json={"title": title})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── the queue ────────────────────────────────────────────────────────────── #


def test_unassigned_voice_call_appears_in_triage():
    sess = _voice_session()
    rows = client.get("/api/honeypot/triage").json()
    assert [r["id"] for r in rows] == [sess["id"]]

    row = rows[0]
    assert row["channel_ref"] == sess["channel_ref"]
    assert row["crime_type"] == sess["crime_type"]
    # The queue carries enough to triage without opening the transcript.
    assert row["entity_count"] == sess["entity_count"]
    assert row["preview"]


def test_text_sessions_never_reach_triage():
    """Triage is the *call* queue — a chat session is not an unplaced call."""
    r = client.post("/api/sessions", json={"channel_type": "text"})
    assert r.status_code == 201, r.text
    assert client.get("/api/honeypot/triage").json() == []


def test_attached_call_leaves_the_queue():
    sess = _voice_session()
    case_id = _case()

    attached = client.post(
        f"/api/honeypot/triage/{sess['id']}/attach", json={"case_id": case_id}
    )
    assert attached.status_code == 200, attached.text
    assert client.get("/api/honeypot/triage").json() == []


# ── attach ───────────────────────────────────────────────────────────────── #


def test_attach_links_the_session_to_the_case():
    sess = _voice_session()
    case_id = _case("Judol ring")

    r = client.post(
        f"/api/honeypot/triage/{sess['id']}/attach", json={"case_id": case_id}
    )
    assert r.status_code == 200, r.text

    # The case now owns the call — visible from the case side, not just ours.
    rollup = client.get(f"/api/cases/{case_id}/rollup").json()
    assert [s["id"] for s in rollup["sessions"]] == [sess["id"]]


def test_attach_rejects_unknown_case():
    """A typo'd case id must 404, not silently strand the session."""
    sess = _voice_session()
    r = client.post(
        f"/api/honeypot/triage/{sess['id']}/attach",
        json={"case_id": "1c1c1c1c-0000-0000-0000-00000000dead"},
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "case_not_found"


def test_attach_rejects_unknown_session():
    r = client.post(
        "/api/honeypot/triage/sess_nope/attach", json={"case_id": _case()}
    )
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "session_not_found"


# ── promote ──────────────────────────────────────────────────────────────── #


def test_promote_prefills_the_case_from_the_call():
    """The classifier already decided a crime type and the call knows its own
    number — an investigator confirming a judgement shouldn't retype either."""
    sess = _voice_session()

    r = client.post(f"/api/honeypot/triage/{sess['id']}/promote", json={})
    assert r.status_code == 201, r.text
    body = r.json()

    case = body["case"]
    assert case["crime_type"] == sess["crime_type"]
    assert sess["channel_ref"] in case["title"]
    assert sess["id"] in case["summary"]  # provenance: which call opened this
    assert case["stage"] == "intake"

    # …and the call is attached, so it leaves the queue in the same step.
    assert body["session"]["id"] == sess["id"]
    assert client.get("/api/honeypot/triage").json() == []
    rollup = client.get(f"/api/cases/{case['id']}/rollup").json()
    assert [s["id"] for s in rollup["sessions"]] == [sess["id"]]


def test_promote_honors_overrides():
    sess = _voice_session()
    r = client.post(
        f"/api/honeypot/triage/{sess['id']}/promote",
        json={
            "title": "Operasi Merpati",
            "crime_type": "judol_deposit",
            "summary": "Analyst-written summary.",
        },
    )
    assert r.status_code == 201, r.text
    case = r.json()["case"]
    assert case["title"] == "Operasi Merpati"
    assert case["crime_type"] == "judol_deposit"
    assert case["summary"] == "Analyst-written summary."


def test_promote_rejects_unknown_session():
    r = client.post("/api/honeypot/triage/sess_nope/promote", json={})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "session_not_found"


# ── auth ─────────────────────────────────────────────────────────────────── #


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("get", "/api/honeypot/triage", None),
        ("post", "/api/honeypot/triage/sess_x/attach", {"case_id": "c"}),
        ("post", "/api/honeypot/triage/sess_x/promote", {}),
    ],
)
def test_triage_requires_auth(method, path, body):
    anon = TestClient(app)
    r = getattr(anon, method)(path, json=body) if body is not None else anon.get(path)
    assert r.status_code == 401
