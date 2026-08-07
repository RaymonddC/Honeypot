"""C1 — production-ready dispatch: HMAC signing, idempotency, the Dispatch Log
feed, and retry. Zero network (httpx mocked); POC/in-memory persistence."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.uncover import service
from app.uncover.notifications import (
    LiveNotificationSink,
    MockNotificationSink,
    deliver_webhook,
    new_idempotency_key,
    sign_payload,
    signature_headers,
)
from tests.conftest import SOURCE, bearer

client = TestClient(app)
client.headers.update(bearer())


@pytest.fixture(autouse=True)
def clean_stores():
    service.reset_stores()
    MockNotificationSink.reset()
    yield
    service.reset_stores()
    MockNotificationSink.reset()


# --------------------------------------------------------------------------- #
# Signing (pure)
# --------------------------------------------------------------------------- #


def test_sign_payload_is_deterministic_and_verifiable():
    body = b'{"a":1}'
    a = sign_payload(body, "shhh", "1700000000")
    b = sign_payload(body, "shhh", "1700000000")
    assert a == b and len(a) == 64            # stable hex sha256
    assert sign_payload(body, "different", "1700000000") != a
    assert sign_payload(body, "shhh", "1700000001") != a  # timestamp is bound in


def test_signature_headers_recompute_matches():
    body = b'{"freeze":"BCA-527"}'
    headers = signature_headers(body, "opssecret")
    assert "X-ITTU-Timestamp" in headers
    parts = dict(p.split("=", 1) for p in headers["X-ITTU-Signature"].split(","))
    # a recipient recomputes v1 over "{t}.{body}" with the shared secret
    assert parts["v1"] == sign_payload(body, "opssecret", parts["t"])
    assert parts["t"] == headers["X-ITTU-Timestamp"]


# --------------------------------------------------------------------------- #
# deliver_webhook (httpx mocked) — signing / idempotency / classification
# --------------------------------------------------------------------------- #


class _FakeClient:
    calls: list[dict] = []
    status_code = 200
    exc: Exception | None = None

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return None

    async def post(self, url, json=None, content=None, headers=None, **k):
        _FakeClient.calls.append(
            {"url": url, "json": json, "content": content, "headers": headers or {}}
        )
        if _FakeClient.exc:
            raise _FakeClient.exc
        r = httpx.Response(_FakeClient.status_code)
        return r


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeClient.calls = []
    _FakeClient.status_code = 200
    _FakeClient.exc = None
    yield


async def test_deliver_webhook_signs_and_sets_idempotency_header(monkeypatch):
    monkeypatch.setattr("app.uncover.notifications.httpx.AsyncClient", _FakeClient)
    packet = {"action_id": "act_1", "reason": "freeze"}

    status, err = await deliver_webhook(
        "https://ops.example/hook", packet, secret="k", idempotency_key="idem_x"
    )

    assert (status, err) == ("sent", None)
    call = _FakeClient.calls[0]
    assert call["json"] is None and call["content"] is not None  # signed → raw body
    assert call["headers"]["X-ITTU-Idempotency-Key"] == "idem_x"
    sig = call["headers"]["X-ITTU-Signature"]
    parts = dict(p.split("=", 1) for p in sig.split(","))
    assert parts["v1"] == sign_payload(call["content"], "k", parts["t"])


async def test_deliver_webhook_unsigned_posts_json(monkeypatch):
    monkeypatch.setattr("app.uncover.notifications.httpx.AsyncClient", _FakeClient)
    packet = {"reason": "freeze"}

    status, err = await deliver_webhook("https://ops.example/hook", packet)

    assert status == "sent"
    call = _FakeClient.calls[0]
    assert call["json"] == packet                 # unsigned → plain JSON body
    assert "X-ITTU-Signature" not in call["headers"]


async def test_deliver_webhook_classifies_failures(monkeypatch):
    monkeypatch.setattr("app.uncover.notifications.httpx.AsyncClient", _FakeClient)

    _FakeClient.status_code = 503
    assert await deliver_webhook("u", {}) == ("failed", "http_503")

    _FakeClient.exc = httpx.ConnectError("refused")
    assert await deliver_webhook("u", {}) == ("failed", "transport_error:ConnectError")


# --------------------------------------------------------------------------- #
# Sinks — idempotency + attempt tracking on the returned record
# --------------------------------------------------------------------------- #


async def test_live_sink_records_idempotency_attempt_and_error(monkeypatch):
    monkeypatch.setattr("app.uncover.notifications.httpx.AsyncClient", _FakeClient)
    sink = LiveNotificationSink(Settings(notification_webhook_url="https://ops/x"))

    _FakeClient.status_code = 200
    note = await sink.dispatch({"agency": "PPATK", "agency_type": "regulator"})
    assert note.status == "sent"
    assert note.idempotency_key and note.idempotency_key.startswith("idem_")
    assert note.attempt_count == 1 and note.last_error is None and note.sent_at

    _FakeClient.status_code = 500
    bad = await sink.dispatch({"agency": "PPATK", "agency_type": "regulator"})
    assert bad.status == "failed" and bad.attempt_count == 1
    assert bad.last_error == "http_500" and bad.sent_at is None


async def test_mock_sink_has_key_but_zero_attempts():
    note = await MockNotificationSink().dispatch({"agency": "OJK", "agency_type": "regulator"})
    assert note.status == "mock"
    assert note.idempotency_key and note.attempt_count == 0


def test_idempotency_keys_are_unique():
    assert new_idempotency_key() != new_idempotency_key()


# --------------------------------------------------------------------------- #
# Dispatch Log feed + retry (API, POC mock sink)
# --------------------------------------------------------------------------- #


def _generate_and_dispatch() -> dict:
    body = {
        "case_id": "CASE-2026-0142",
        "crime_type": "investment",
        "entities": [{"type": "crypto_wallet", "value": SOURCE, "chain": "tron"}],
        "outputs": ["freeze", "ltkm", "alert", "pack"],
    }
    b = client.post("/api/actions/generate", json=body).json()
    return client.post(f"/api/actions/{b['id']}/dispatch").json()


def test_feed_lists_dispatched_notifications_with_filters():
    d = _generate_and_dispatch()
    feed = client.get("/api/notifications").json()
    assert len(feed) == len(d["notifications"])
    assert {n["id"] for n in feed} == {n["id"] for n in d["notifications"]}
    assert all(n["status"] == "mock" for n in feed)
    assert all(n["idempotency_key"] for n in feed)

    # status filter
    assert client.get("/api/notifications", params={"status": "mock"}).json()
    assert client.get("/api/notifications", params={"status": "sent"}).json() == []
    # agency_type filter narrows the set
    regs = client.get("/api/notifications", params={"agency_type": "regulator"}).json()
    assert regs and all(n["agency_type"] == "regulator" for n in regs)


def test_feed_requires_auth():
    noauth = TestClient(app)
    assert noauth.get("/api/notifications").status_code == 401


def test_retry_unknown_notification_404():
    r = client.post("/api/notifications/ntf_nope/retry")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "notification_not_found"


def test_retry_poc_notification_reruns_mock():
    d = _generate_and_dispatch()
    nid = d["notifications"][0]["id"]
    r = client.post(f"/api/notifications/{nid}/retry")
    assert r.status_code == 200
    out = r.json()
    assert out["id"] == nid
    assert out["status"] == "mock"          # POC: still a mock, nothing left
    # the retried record is still the same one in the feed (no duplicate)
    feed_ids = [n["id"] for n in client.get("/api/notifications").json()]
    assert feed_ids.count(nid) == 1
