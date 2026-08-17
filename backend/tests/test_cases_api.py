"""CASES — the case-file spine (create/list/get/update + rollup of case data).

TestClient against the POC memory repos (no DB). Verifies CRUD, stage
advancement, and that case-data records attach to a case via the rollup.
"""

import pytest
from fastapi.testclient import TestClient

from app.cases import repository as cases_repo
from app.casedata import repository as casedata_repo
from app.main import app
from tests.conftest import bearer

client = TestClient(app)
client.headers.update(bearer())


@pytest.fixture(autouse=True)
def clean_stores():
    cases_repo.reset_stores()
    casedata_repo.reset_stores()
    yield
    cases_repo.reset_stores()
    casedata_repo.reset_stores()


def make_case(title="Investment scam ring", **kw) -> dict:
    r = client.post("/api/cases", json={"title": title, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_create_and_get_case():
    c = make_case(crime_type="investment_scam")
    assert c["title"] == "Investment scam ring"
    assert c["stage"] == "intake"
    assert c["status"] == "open"
    got = client.get(f"/api/cases/{c['id']}").json()
    assert got["id"] == c["id"]


def test_cases_require_auth():
    anon = TestClient(app)
    assert anon.post("/api/cases", json={"title": "x"}).status_code == 401
    assert anon.get("/api/cases").status_code == 401


def test_list_cases_newest_first():
    a = make_case("Case A")
    b = make_case("Case B")
    ids = [c["id"] for c in client.get("/api/cases").json()]
    assert ids[0] == b["id"] and ids[1] == a["id"]


def test_advance_stage_and_status():
    c = make_case()
    r = client.patch(f"/api/cases/{c['id']}", json={"stage": "trace"})
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "trace"
    r2 = client.patch(f"/api/cases/{c['id']}", json={"status": "closed", "stage": "closed"})
    assert r2.json()["status"] == "closed"
    assert r2.json()["stage"] == "closed"


def test_invalid_stage_rejected():
    c = make_case()
    r = client.patch(f"/api/cases/{c['id']}", json={"stage": "not_a_stage"})
    assert r.status_code == 422


def test_update_unknown_case_404():
    assert client.patch("/api/cases/nope", json={"stage": "trace"}).status_code == 404


def test_rollup_attaches_case_data():
    c = make_case()
    cid = c["id"]
    client.post(
        "/api/casedata/bank-accounts",
        json={"bank_name": "BCA", "account_number": "5271038462", "case_id": cid},
    )
    client.post(
        "/api/casedata/crypto-transfers",
        json={
            "from_addr": "TVictimAAA", "to_addr": "TScamBBB",
            "value": 25000, "ts": "2026-07-20T08:00:00+00:00", "case_id": cid,
        },
    )
    # a record on ANOTHER case must NOT show up in this rollup
    other = make_case("Other")
    client.post(
        "/api/casedata/bank-accounts",
        json={"bank_name": "BNI", "account_number": "999", "case_id": other["id"]},
    )

    rollup = client.get(f"/api/cases/{cid}/rollup").json()
    assert rollup["case"]["id"] == cid
    assert rollup["counts"] == {
        "bank_accounts": 1, "crypto_transfers": 1, "sessions": 0, "documents": 0,
    }
    assert rollup["bank_accounts"][0]["account_number"] == "5271038462"
    assert rollup["crypto_transfers"][0]["to_addr"] == "TScamBBB"


def test_rollup_includes_honeypot_session_attached_to_case():
    """A honeypot session started with case_id shows up in the case rollup."""
    from app.infiltrate import service as infiltrate_service

    infiltrate_service.reset_stores()
    c = make_case("Honeypot case")
    cid = c["id"]

    r = client.post("/api/sessions", json={"scenario": "investment_scam", "case_id": cid})
    assert r.status_code == 201, r.text

    rollup = client.get(f"/api/cases/{cid}/rollup").json()
    assert rollup["counts"]["sessions"] == 1
    sess = rollup["sessions"][0]
    assert sess["crime_type"] == "investment_scam"
    assert sess["entity_count"] >= 1
    # the case view distinguishes calls from chats off this, not off `channel`
    assert sess["channel_type"] == "text"
    infiltrate_service.reset_stores()
