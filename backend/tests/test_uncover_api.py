"""UNCOVER API — generate → inspect → download → dispatch flow + metrics shape."""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.uncover import service
from app.uncover.notifications import MockNotificationSink
from tests.conftest import SOURCE, bearer

client = TestClient(app)
client.headers.update(bearer())  # P5: generate/dispatch require auth (+dispatch role)


@pytest.fixture(autouse=True)
def clean_stores():
    service.reset_stores()
    MockNotificationSink.reset()
    yield
    service.reset_stores()
    MockNotificationSink.reset()


def generate(**overrides) -> dict:
    body = {
        "case_id": "CASE-2026-0142",
        "crime_type": "investment",
        "entities": [{"type": "crypto_wallet", "value": SOURCE, "chain": "tron"}],
        "outputs": ["freeze", "ltkm", "alert", "pack"],
    } | overrides
    r = client.post("/api/actions/generate", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_generate_returns_draft_bundle_with_hashed_docs():
    b = generate()
    assert b["status"] == "draft"
    assert b["data_mode"] == "poc"
    assert b["dispatched_at"] is None
    assert b["notifications"] == []

    types = [d["type"] for d in b["documents"]]
    assert types == ["account_blocking", "str_report", "summary"]
    for d in b["documents"]:
        assert len(d["sha256"]) == 64
        assert d["size_bytes"] > 1000
        assert d["status"] == "draft"
        assert d["download_url"] == f"/api/documents/{d['id']}"

    # wallet context was pulled from TAKEDOWN (fixtures): risk data in totals
    assert b["totals"]["at_risk_usdt"] > 0
    assert b["totals"]["at_risk_idr"] > b["totals"]["at_risk_usdt"]

    # goAML draft present with analyst placeholder subject
    goaml = b["goaml_draft"]
    assert goaml["report"]["report_code"] == "STR"
    assert "TO BE COMPLETED" in goaml["subjects"][0]["full_name"]

    # routing plan covers exchange freeze + PPATK STR + OJK/Polri alerts
    doc_types = {t["document_type"] for t in b["routing_plan"]}
    assert {"account_blocking", "str_report", "alert"} <= doc_types

    # The bundle's audit view is now a filtered slice of the DURABLE core trail
    # (app/uncover/router.py::_attach_audit), not the old in-memory custody
    # chain. One entry per bundle rather than one per document — the per-document
    # facts moved INTO that entry rather than being dropped.
    actions = [a["action"] for a in b["audit"]]
    assert "action.bundle.generated" in actions, f"got {actions}"
    assert "action.document.generated" not in actions, (
        "the in-memory per-document custody entries should be gone"
    )
    generated = next(a for a in b["audit"] if a["action"] == "action.bundle.generated")
    recorded_docs = generated["detail"]["documents"]
    assert len(recorded_docs) == 3, recorded_docs
    for rd in recorded_docs:
        # Everything the per-document entries used to carry has to still be here,
        # or the collapse lost evidence rather than consolidating it.
        assert len(rd["sha256"]) == 64
        assert rd["type"] and rd["format"] and rd["template_version"]
    assert {rd["sha256"] for rd in recorded_docs} == {d["sha256"] for d in b["documents"]}
    # And the entry names the bundle it belongs to, which is what makes the
    # filtered view possible at all (see _preserve_business_key).
    assert generated["detail"]["_target_id"] == b["id"]


def test_generate_subset_outputs():
    b = generate(outputs=["freeze"])
    assert [d["type"] for d in b["documents"]] == ["account_blocking"]
    assert b["goaml_draft"] is None
    assert all(t["document_type"] == "account_blocking" for t in b["routing_plan"])


def test_get_action_roundtrip_and_404():
    b = generate()
    got = client.get(f"/api/actions/{b['id']}").json()
    assert got["id"] == b["id"]
    assert got["documents"] == b["documents"]

    r = client.get("/api/actions/act_nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "action_not_found"


def test_document_download_pdf_bytes_match_custody_hash():
    import hashlib

    b = generate()
    doc = b["documents"][0]
    r = client.get(doc["download_url"])
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.content[:5] == b"%PDF-"
    assert hashlib.sha256(r.content).hexdigest() == doc["sha256"]
    assert r.headers["x-document-sha256"] == doc["sha256"]

    r = client.get("/api/documents/doc_nope")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "document_not_found"


def test_dispatch_flow_mock_sink_human_gated():
    b = generate()
    r = client.post(f"/api/actions/{b['id']}/dispatch")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "dispatched"
    assert d["dispatched_at"] is not None
    # every routing target produced a mock notification — nothing left the system
    assert len(d["notifications"]) == len(d["routing_plan"])
    for n in d["notifications"]:
        assert n["status"] == "mock"
        assert n["data_mode"] == "poc"
        assert "would dispatch to" in n["payload"]["note"]
    # documents moved draft → issued
    assert all(doc["status"] == "issued" for doc in d["documents"])
    # `dispatch.sent` is the core-trail action name; `action.bundle.dispatched`
    # was the in-memory custody chain's, and that chain is gone.
    dispatched = next(a for a in d["audit"] if a["action"] == "dispatch.sent")
    assert dispatched["detail"]["_target_id"] == b["id"]
    # Per-notification detail was custody's ONE piece of information the core
    # trail lacked; it was moved across rather than dropped.
    recorded = dispatched["detail"]["notifications"]
    assert {n["id"] for n in recorded} == {n["id"] for n in d["notifications"]}
    assert all(n["agency"] and n["status"] for n in recorded)

    # dispatch is idempotence-guarded: second call → 409
    r2 = client.post(f"/api/actions/{b['id']}/dispatch")
    assert r2.status_code == 409
    assert r2.json()["error"]["code"] == "already_dispatched"

    # unknown action → 404
    assert client.post("/api/actions/act_nope/dispatch").status_code == 404


def test_bank_account_entity_routes_holding_bank():
    mules = client.get("/api/bridge/mules").json()
    acct = mules["items"][0]["accounts"][0]
    b = generate(
        case_id="CASE-2026-0104",
        crime_type="judol_deposit",
        entities=[{"type": "bank_account", "value": acct["account_number"],
                   "bank_name": acct["bank_name"]}],
        outputs=["freeze", "ltkm"],
    )
    banks = [t for t in b["routing_plan"] if t["agency_type"] == "bank"]
    assert banks and banks[0]["agency"] == f"Bank {acct['bank_name']}"
    assert acct["account_number"] in banks[0]["reason"]
    assert b["goaml_draft"]["accounts"][0]["account_number"] == acct["account_number"]
    # fiat-side exposure flowed into totals
    assert b["totals"]["at_risk_idr"] > 0


def test_metrics_shape_and_baselines():
    m = client.get("/api/metrics/response").json()
    assert m["range"] == "30d"
    assert m["data_mode"] == "poc"
    assert m["cases_total"] >= m["cases_in_progress"] > 0
    assert m["time_to_freeze"]["baseline_hours"] == 12.0
    assert m["funds"]["baseline_recovery_rate"] == 0.0476
    assert 0 <= m["funds"]["recovery_rate"] <= 1
    assert m["funds"]["at_risk_idr"] >= m["funds"]["frozen_idr"] > 0
    assert m["honeypot"]["active_sessions"] > 0
    assert m["wallets_scored"] > 0
    assert len(m["trend"]) == 6
    assert m["cases"], "dashboard must be populated by the demo baseline"
    # rows sorted newest first
    opened = [c["opened_at"] for c in m["cases"]]
    assert opened == sorted(opened, reverse=True)


def test_metrics_range_filter():
    m_all = client.get("/api/metrics/response", params={"range": "all"}).json()
    m_7d = client.get("/api/metrics/response", params={"range": "7d"}).json()
    assert m_7d["cases_total"] <= m_all["cases_total"]
    assert client.get(
        "/api/metrics/response", params={"range": "bogus"}
    ).status_code == 422


def test_metrics_cases_deduped_per_case_id():
    # Repeated generate→dispatch runs for the same case must yield ONE row,
    # and a live action row supersedes the baseline row for that case_id.
    case_id = "CASE-2026-0142"  # also present in the demo baseline
    for _ in range(3):
        b = generate(case_id=case_id)
        client.post(f"/api/actions/{b['id']}/dispatch")

    m = client.get("/api/metrics/response", params={"range": "all"}).json()
    rows = [c for c in m["cases"] if c["case_id"] == case_id]
    assert len(rows) == 1
    assert rows[0]["source"] == "action"
    assert rows[0]["status"] == "frozen"
    # all case_ids unique across the dashboard
    ids = [c["case_id"] for c in m["cases"]]
    assert len(ids) == len(set(ids))


def test_metrics_move_after_generate_and_dispatch():
    before = client.get("/api/metrics/response").json()
    b = generate()
    client.post(f"/api/actions/{b['id']}/dispatch")
    after = client.get("/api/metrics/response").json()

    assert after["actions"]["bundles_generated"] == before["actions"]["bundles_generated"] + 1
    assert after["actions"]["bundles_dispatched"] == before["actions"]["bundles_dispatched"] + 1
    assert after["actions"]["notifications_mock"] > before["actions"]["notifications_mock"]
    assert after["funds"]["frozen_idr"] > before["funds"]["frozen_idr"]
    # the dispatched action surfaces as a live "frozen" case row
    live = [c for c in after["cases"] if c["source"] == "action"]
    assert live and live[0]["status"] == "frozen"
    assert live[0]["time_to_freeze_minutes"] is not None


# --- the evidence hash: the defect that drove the custody collapse -----------


def test_the_evidence_hash_does_not_change_when_the_bundle_is_dispatched():
    """The displayed evidence hash must describe the EVIDENCE, nothing else.

    It used to be derived from the audit chain's head (frontend/lib/actions/
    api.ts). That head moved for reasons having nothing to do with the
    documents: it advanced on dispatch, and — because the chain was per-process
    and in-memory — it vanished entirely on restart, silently falling back to
    `documents[0].sha256`. So the same bundle displayed different "evidence
    hashes" over its life. It is now a digest of the document hashes, so it can
    only move if the evidence moves.
    """
    b = generate()
    at_generate = b["evidence_hash"]
    assert len(at_generate) == 64, f"expected a sha256, got {at_generate!r}"

    on_reread = client.get(f"/api/actions/{b['id']}").json()["evidence_hash"]
    assert on_reread == at_generate, "re-reading the same bundle changed its hash"

    dispatched = client.post(f"/api/actions/{b['id']}/dispatch").json()
    assert dispatched["evidence_hash"] == at_generate, (
        "dispatch appended an audit entry and the evidence hash moved with it — "
        "that is the old chain-head derivation, back again"
    )
    # …and the audit view DID grow, so the hash's stability is not just an
    # artefact of nothing having happened.
    assert len(dispatched["audit"]) > len(b["audit"]), (
        "dispatch should have added an audit entry; if not, this test proves nothing"
    )


def test_the_evidence_hash_tracks_the_documents_and_not_their_order():
    from app.uncover.service import evidence_hash

    class _Doc:
        def __init__(self, h):
            self.sha256 = h

    a, b_, c = _Doc("a" * 64), _Doc("b" * 64), _Doc("c" * 64)
    assert evidence_hash([a, b_, c]) == evidence_hash([c, a, b_]), (
        "generation order must not change the fingerprint of the same evidence"
    )
    assert evidence_hash([a, b_]) != evidence_hash([a, b_, c]), (
        "an extra document is different evidence and must hash differently"
    )
    assert evidence_hash([]) == ""


def test_a_bundles_audit_seq_is_the_agency_position_not_a_per_bundle_counter():
    """Documents the visible contract change, so nobody 'fixes' the numbering.

    The old custody chain numbered a bundle's entries 1, 2. The core trail is
    per AGENCY, so a bundle's entries carry their position in that chain and are
    deliberately non-contiguous. Rendering them as if the bundle had its own
    gapless chain would be the same over-claim the /audit banner was corrected
    for — the gaps are the agency's other actions, not missing entries.
    """
    client.post("/api/cases", json={"title": "noise before"})  # advance the chain
    b = generate()
    seqs = [a["seq"] for a in b["audit"]]
    assert seqs, "the bundle should have at least its generation entry"
    assert seqs[0] > 1, (
        f"expected a position in the agency chain, got {seqs} — if this is 1 the "
        "view is being renumbered per bundle, which is not what it is"
    )
