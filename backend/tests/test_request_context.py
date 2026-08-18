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


def test_requests_are_logged_without_query_strings(caplog):
    """Query strings are fine today and are exactly where a token or phone
    number lands tomorrow — and log lines outlive the reasoning that made them
    safe. Method, path, status and duration answer the operational question."""
    with caplog.at_level(logging.INFO, logger="ittu.request"):
        client.get("/api/entities?session=sess_secret_value")
    line = next(r.getMessage() for r in caplog.records if "/api/entities" in r.getMessage())
    assert "GET /api/entities" in line
    assert "sess_secret_value" not in line, "query string must not reach the log"


def test_health_probes_do_not_flood_the_log(caplog):
    """/health is polled constantly; logging each poll buries the real lines."""
    with caplog.at_level(logging.INFO, logger="ittu.request"):
        client.get("/health")
    assert not [r for r in caplog.records if "/health" in r.getMessage()]
