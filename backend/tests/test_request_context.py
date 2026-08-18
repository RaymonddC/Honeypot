"""Request correlation (app/core/requests.py).

The gap this closes: a user reporting "it didn't work" gave nothing to search
on. Now every response carries X-Request-ID, error bodies repeat it, and the
request's log line uses the same id.
"""

import logging

from fastapi.testclient import TestClient

from app.core.requests import REQUEST_ID_HEADER
from app.main import app

client = TestClient(app)


def test_every_response_carries_a_request_id():
    for path in ("/health", "/api/config", "/api/cases"):  # ok, open, and 401
        assert client.get(path).headers.get(REQUEST_ID_HEADER)


def test_error_bodies_repeat_the_id_so_a_user_can_quote_it():
    """A user copies what they can SEE. An id only in a header is invisible to
    them, which defeats the point."""
    r = client.get("/api/cases")  # 401
    assert r.status_code == 401
    assert r.json()["error"]["request_id"] == r.headers[REQUEST_ID_HEADER]


def test_an_inbound_id_is_honoured_not_replaced():
    """Render (or any proxy/client) may already have assigned one; generating a
    fresh id at our boundary would break the trail exactly where it should join."""
    r = client.get("/api/cases", headers={REQUEST_ID_HEADER: "from-proxy-123"})
    assert r.headers[REQUEST_ID_HEADER] == "from-proxy-123"


def test_an_absurdly_long_inbound_id_is_truncated():
    """The id is echoed into responses AND logs, so an attacker-supplied huge
    header must not become a huge log line."""
    r = client.get("/api/cases", headers={REQUEST_ID_HEADER: "x" * 5000})
    assert len(r.headers[REQUEST_ID_HEADER]) <= 64


class _Capture(logging.Handler):
    """Capture records straight off the `ittu.request` logger.

    Not caplog: TestClient runs the app in a separate thread, and caplog's
    root-handler capture races with that — the test passed alone and flaked in
    the full suite. Attaching to the logger itself is deterministic regardless
    of which thread emits.
    """

    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


def _capture_request_logs() -> _Capture:
    handler = _Capture()
    logger = logging.getLogger("ittu.request")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return handler


def test_requests_are_logged_without_query_strings():
    """Query strings are fine today and are exactly where a token or phone
    number lands tomorrow — and log lines outlive the reasoning that made them
    safe. Method, path, status and duration answer the operational question."""
    handler = _capture_request_logs()
    try:
        client.get("/api/entities?session=sess_secret_value")
    finally:
        logging.getLogger("ittu.request").removeHandler(handler)
    matching = [m for m in handler.messages if "/api/entities" in m]
    assert matching, f"the request was not logged at all; saw {handler.messages}"
    line = matching[0]
    assert "GET /api/entities" in line
    assert "sess_secret_value" not in line, "query string must not reach the log"


def test_health_probes_do_not_flood_the_log():
    """/health is polled constantly; logging each poll buries the real lines."""
    handler = _capture_request_logs()
    try:
        client.get("/health")
    finally:
        logging.getLogger("ittu.request").removeHandler(handler)
    assert not [m for m in handler.messages if "/health" in m]
