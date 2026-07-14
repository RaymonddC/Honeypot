"""LIVE notification sink — webhook dispatch (zero network, httpx mocked)."""

import httpx
import pytest

from app.core.config import Settings
from app.uncover.notifications import LiveNotificationSink

PACKET = {
    "action_id": "act_1",
    "case_id": "CASE-1",
    "agency": "PPATK",
    "agency_type": "regulator",
    "channel": "goaml",
    "document_ids": ["doc_1"],
    "document_hashes": ["ff" * 32],
}


class _FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300


class _FakeAsyncClient:
    """Records the last POST call; returns a scripted response or raises."""

    calls: list[dict] = []
    response: _FakeResponse | None = None
    exc: Exception | None = None

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        return None

    async def post(self, url: str, json: dict | None = None, **kwargs):
        _FakeAsyncClient.calls.append({"url": url, "json": json})
        if _FakeAsyncClient.exc is not None:
            raise _FakeAsyncClient.exc
        return _FakeAsyncClient.response


@pytest.fixture(autouse=True)
def _reset_fake_client():
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.response = None
    _FakeAsyncClient.exc = None
    yield


def _sink(monkeypatch, webhook_url: str) -> LiveNotificationSink:
    monkeypatch.setattr("app.uncover.notifications.httpx.AsyncClient", _FakeAsyncClient)
    settings = Settings(notification_webhook_url=webhook_url)
    return LiveNotificationSink(settings)


async def test_dispatch_posts_packet_and_returns_sent_on_2xx(monkeypatch):
    sink = _sink(monkeypatch, "https://ops.example.com/hooks/ittu")
    _FakeAsyncClient.response = _FakeResponse(200)

    note = await sink.dispatch(PACKET)

    assert len(_FakeAsyncClient.calls) == 1
    call = _FakeAsyncClient.calls[0]
    assert call["url"] == "https://ops.example.com/hooks/ittu"
    assert call["json"] == PACKET

    assert note.status == "sent"
    assert note.channel == "webhook"
    assert note.data_mode == "live"
    assert note.action_id == "act_1"
    assert note.case_id == "CASE-1"
    assert note.target_agency == "PPATK"
    assert note.agency_type == "regulator"
    assert note.sent_at is not None
    # No URL/secrets ever leak into the returned payload.
    assert "https://ops.example.com" not in str(note.payload)
    assert "url" not in note.payload


async def test_dispatch_returns_failed_on_non_2xx_response(monkeypatch):
    sink = _sink(monkeypatch, "https://ops.example.com/hooks/ittu")
    _FakeAsyncClient.response = _FakeResponse(500)

    note = await sink.dispatch(PACKET)

    assert note.status == "failed"
    assert len(_FakeAsyncClient.calls) == 1


async def test_dispatch_returns_failed_on_httpx_error(monkeypatch):
    sink = _sink(monkeypatch, "https://ops.example.com/hooks/ittu")
    _FakeAsyncClient.exc = httpx.ConnectError("connection refused")

    note = await sink.dispatch(PACKET)

    assert note.status == "failed"


async def test_dispatch_without_webhook_url_fails_loud(monkeypatch):
    sink = _sink(monkeypatch, "")

    with pytest.raises(NotImplementedError, match="ITTU_NOTIFICATION_WEBHOOK_URL"):
        await sink.dispatch(PACKET)

    assert _FakeAsyncClient.calls == []
