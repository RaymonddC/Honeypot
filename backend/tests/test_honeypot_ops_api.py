"""HONEYPOT OPS — the number pool + dial campaigns (phase 3, CRUD only).

TestClient against the POC memory repo (no DB, no network). Verifies CRUD,
E.164 normalization/validation + dedupe on bulk upload, the campaign status
transitions, and that nothing here dials.
"""

import pytest
from fastapi.testclient import TestClient

from app.honeypot_ops import repository as ops_repo
from app.main import app
from tests.conftest import bearer

client = TestClient(app)
client.headers.update(bearer())


@pytest.fixture(autouse=True)
def clean_store():
    ops_repo.reset_stores()
    yield
    ops_repo.reset_stores()


def _campaign(name: str = "Judol sweep") -> str:
    r = client.post("/api/honeypot/campaigns", json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── numbers ─────────────────────────────────────────────────────────────── #


def test_register_and_list_number():
    r = client.post(
        "/api/honeypot/numbers",
        json={
            "phone_number": "+6281234567890",
            "twilio_sid": "PN0123456789abcdef",
            "label": "Bareskrim honeypot #1",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["phone_number"] == "+6281234567890"
    assert body["status"] == "active"
    assert body["id"].startswith("num_")

    listed = client.get("/api/honeypot/numbers").json()
    assert len(listed) == 1
    assert listed[0]["label"] == "Bareskrim honeypot #1"


def test_number_normalizes_pasted_separators():
    """Operators paste numbers with spaces/dashes — store canonical E.164."""
    r = client.post(
        "/api/honeypot/numbers", json={"phone_number": "+62 812-3456 7890"}
    )
    assert r.status_code == 201, r.text
    assert r.json()["phone_number"] == "+6281234567890"


@pytest.mark.parametrize("bad", ["081234567890", "not-a-number", "+0812345678", "+62"])
def test_number_rejects_non_e164(bad):
    """A bare local number is rejected, not guessed at — auto-prefixing a
    country code would silently dial the wrong person."""
    r = client.post("/api/honeypot/numbers", json={"phone_number": bad})
    assert r.status_code == 422, r.text


def test_duplicate_number_is_conflict():
    client.post("/api/honeypot/numbers", json={"phone_number": "+6281234567890"})
    r = client.post("/api/honeypot/numbers", json={"phone_number": "+6281234567890"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "number_already_registered"


def test_retire_and_relabel_number():
    num_id = client.post(
        "/api/honeypot/numbers", json={"phone_number": "+6281234567890"}
    ).json()["id"]

    r = client.patch(
        f"/api/honeypot/numbers/{num_id}",
        json={"status": "retired", "label": "burned"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "retired"
    assert r.json()["label"] == "burned"


def test_update_unknown_number_404s():
    r = client.patch("/api/honeypot/numbers/num_nope", json={"status": "retired"})
    assert r.status_code == 404


def test_numbers_require_auth():
    anon = TestClient(app)  # no bearer header
    assert anon.get("/api/honeypot/numbers").status_code == 401
    assert (
        anon.post("/api/honeypot/numbers", json={"phone_number": "+6281234567890"}).status_code
        == 401
    )


# ── campaigns ───────────────────────────────────────────────────────────── #


def test_create_and_list_campaign():
    r = client.post(
        "/api/honeypot/campaigns",
        json={"name": "Judol sweep", "pacing_per_minute": 10},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Judol sweep"
    assert body["status"] == "draft"
    assert body["pacing_per_minute"] == 10
    assert body["target_count"] == 0
    assert body["id"].startswith("camp_")

    listed = client.get("/api/honeypot/campaigns").json()
    assert len(listed) == 1


def test_get_unknown_campaign_404s():
    assert client.get("/api/honeypot/campaigns/camp_nope").status_code == 404


def test_campaigns_require_auth():
    anon = TestClient(app)
    assert anon.get("/api/honeypot/campaigns").status_code == 401


# ── bulk target upload ──────────────────────────────────────────────────── #


def test_upload_targets_json_array():
    cid = _campaign()
    r = client.post(
        f"/api/honeypot/campaigns/{cid}/targets",
        json={"numbers": ["+6281111111111", "+6282222222222"]},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == 2
    assert body["rejected"] == []

    camp = client.get(f"/api/honeypot/campaigns/{cid}").json()
    assert camp["target_count"] == 2
    assert camp["counts"] == {"queued": 2}


def test_upload_targets_from_pasted_csv():
    """CSV export shape: number first on the row, extra columns ignored."""
    cid = _campaign()
    pasted = (
        "+6281111111111,Kredibel,reported 3x\n"
        "+62 822-2222-2222,Lapor,\n"
        "\n"  # blank lines tolerated
        "+6283333333333\n"
    )
    r = client.post(f"/api/honeypot/campaigns/{cid}/targets", json={"text": pasted})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == 3
    assert [t["phone_number"] for t in body["targets"]] == [
        "+6281111111111",
        "+6282222222222",
        "+6283333333333",
    ]


def test_upload_reports_per_row_rejects_without_failing():
    """One bad row must not sink the upload — a pasted dial list is messy."""
    cid = _campaign()
    r = client.post(
        f"/api/honeypot/campaigns/{cid}/targets",
        json={
            "numbers": [
                "+6281111111111",
                "not-a-number",       # invalid
                "+6281111111111",     # duplicate within this upload
                "+6282222222222",
            ]
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["added"] == 2
    reasons = {x["reason"] for x in body["rejected"]}
    assert reasons == {"invalid", "duplicate_in_upload"}


def test_upload_dedupes_against_existing_targets():
    cid = _campaign()
    client.post(f"/api/honeypot/campaigns/{cid}/targets", json={"numbers": ["+6281111111111"]})
    r = client.post(
        f"/api/honeypot/campaigns/{cid}/targets",
        json={"numbers": ["+6281111111111", "+6282222222222"]},
    )
    body = r.json()
    assert body["added"] == 1
    assert body["rejected"] == [
        {"value": "+6281111111111", "reason": "already_in_campaign"}
    ]
    assert client.get(f"/api/honeypot/campaigns/{cid}").json()["target_count"] == 2


def test_upload_to_unknown_campaign_404s():
    r = client.post(
        "/api/honeypot/campaigns/camp_nope/targets", json={"numbers": ["+6281111111111"]}
    )
    assert r.status_code == 404


def test_list_targets():
    cid = _campaign()
    client.post(f"/api/honeypot/campaigns/{cid}/targets", json={"numbers": ["+6281111111111"]})
    r = client.get(f"/api/honeypot/campaigns/{cid}/targets")
    assert r.status_code == 200, r.text
    targets = r.json()
    assert len(targets) == 1
    assert targets[0]["status"] == "queued"
    assert targets[0]["attempt_count"] == 0


# ── lifecycle (status only — no dialing in this phase) ──────────────────── #


def test_start_and_pause_campaign():
    cid = _campaign()
    client.post(f"/api/honeypot/campaigns/{cid}/targets", json={"numbers": ["+6281111111111"]})

    r = client.post(f"/api/honeypot/campaigns/{cid}/start")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "running"

    r = client.post(f"/api/honeypot/campaigns/{cid}/pause")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "paused"

    # resume
    assert client.post(f"/api/honeypot/campaigns/{cid}/start").json()["status"] == "running"


def test_start_empty_campaign_is_conflict():
    cid = _campaign()
    r = client.post(f"/api/honeypot/campaigns/{cid}/start")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "campaign_empty"


def test_pause_non_running_campaign_is_conflict():
    cid = _campaign()
    r = client.post(f"/api/honeypot/campaigns/{cid}/pause")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "campaign_not_running"


def test_start_does_not_dial():
    """Starting a campaign moves status and nothing else by default: targets stay
    queued with no attempt. Enqueueing is opt-in (ITTU_DIAL_ENQUEUE_ON_START) and
    needs Postgres, so the POC demo never requires Redis or a running worker."""
    cid = _campaign()
    client.post(f"/api/honeypot/campaigns/{cid}/targets", json={"numbers": ["+6281111111111"]})
    client.post(f"/api/honeypot/campaigns/{cid}/start")

    targets = client.get(f"/api/honeypot/campaigns/{cid}/targets").json()
    assert [t["status"] for t in targets] == ["queued"]
    assert targets[0]["attempt_count"] == 0
    # No session_id on a target: the call log is one-to-many and lives on
    # intel.scam_sessions.dial_target_id (migration 20260816_14).
    assert "session_id" not in targets[0]


# ── requeue (§3.6) ──────────────────────────────────────────────────────── #


def _seed_target(cid: str, number: str, *, status: str, attempts: int = 0):
    """Put a target into a finished state without running the dialer.

    The memory repo is the POC store and nothing in it dials, so a test that
    needs a *worked* target sets the row directly. The real transitions are
    covered against Postgres in test_honeypot_dialer_pg.py.
    """
    store = ops_repo._memory_repository()
    for i, t in enumerate(store._targets):
        if t.campaign_id == cid and t.phone_number == number:
            store._targets[i] = t.model_copy(
                update={"status": status, "attempt_count": attempts}
            )
            return store._targets[i]
    raise AssertionError(f"no target {number} in {cid}")


def test_requeue_resets_finished_targets_and_keeps_attempt_history():
    cid = _campaign()
    client.post(
        f"/api/honeypot/campaigns/{cid}/targets",
        json={"numbers": ["+6281111111111", "+6282222222222"]},
    )
    _seed_target(cid, "+6281111111111", status="no_answer", attempts=2)
    _seed_target(cid, "+6282222222222", status="failed", attempts=3)

    r = client.post(f"/api/honeypot/campaigns/{cid}/requeue", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["requeued"] == 2
    assert body["skipped"] == 0

    targets = {t["phone_number"]: t for t in client.get(
        f"/api/honeypot/campaigns/{cid}/targets"
    ).json()}
    assert targets["+6281111111111"]["status"] == "queued"
    assert targets["+6282222222222"]["status"] == "queued"
    # attempt_count is history, never reset — "tried 3 times" must survive.
    assert targets["+6281111111111"]["attempt_count"] == 2
    assert targets["+6282222222222"]["attempt_count"] == 3


def test_requeue_never_touches_a_dialing_target():
    """A dialing target has a call IN FLIGHT — requeueing it would place a
    second call to the same person. It is skipped and counted, not silently
    dropped."""
    cid = _campaign()
    client.post(f"/api/honeypot/campaigns/{cid}/targets", json={"numbers": ["+6283333333333"]})
    _seed_target(cid, "+6283333333333", status="dialing", attempts=1)

    body = client.post(
        f"/api/honeypot/campaigns/{cid}/requeue",
        json={"target_ids": [
            t["id"] for t in client.get(f"/api/honeypot/campaigns/{cid}/targets").json()
        ]},
    ).json()
    assert body["requeued"] == 0
    assert body["skipped"] == 1
    assert client.get(f"/api/honeypot/campaigns/{cid}/targets").json()[0]["status"] == "dialing"


def test_requeue_defaults_skip_engaged_but_can_be_asked_for():
    """Re-calling someone you already spoke to is deliberate, so `engaged` is
    requeueable but not swept by default."""
    cid = _campaign()
    client.post(f"/api/honeypot/campaigns/{cid}/targets", json={"numbers": ["+6284444444444"]})
    _seed_target(cid, "+6284444444444", status="engaged", attempts=1)

    assert client.post(f"/api/honeypot/campaigns/{cid}/requeue", json={}).json()["requeued"] == 0

    r = client.post(
        f"/api/honeypot/campaigns/{cid}/requeue", json={"statuses": ["engaged"]}
    )
    assert r.json()["requeued"] == 1
    assert client.get(f"/api/honeypot/campaigns/{cid}/targets").json()[0]["status"] == "queued"


def test_requeue_by_target_id_selects_only_that_target():
    cid = _campaign()
    client.post(
        f"/api/honeypot/campaigns/{cid}/targets",
        json={"numbers": ["+6285555555555", "+6286666666666"]},
    )
    _seed_target(cid, "+6285555555555", status="no_answer", attempts=1)
    _seed_target(cid, "+6286666666666", status="no_answer", attempts=1)
    listed = client.get(f"/api/honeypot/campaigns/{cid}/targets").json()
    picked = next(t for t in listed if t["phone_number"] == "+6285555555555")

    body = client.post(
        f"/api/honeypot/campaigns/{cid}/requeue", json={"target_ids": [picked["id"]]}
    ).json()
    assert body["requeued"] == 1

    after = {t["phone_number"]: t["status"] for t in client.get(
        f"/api/honeypot/campaigns/{cid}/targets"
    ).json()}
    assert after["+6285555555555"] == "queued"
    assert after["+6286666666666"] == "no_answer"  # untouched


def test_requeue_unknown_campaign_is_404():
    r = client.post("/api/honeypot/campaigns/camp_nope/requeue", json={})
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "campaign_not_found"


def test_requeue_requires_auth():
    cid = _campaign()
    bare = TestClient(app)
    assert bare.post(f"/api/honeypot/campaigns/{cid}/requeue", json={}).status_code == 401
