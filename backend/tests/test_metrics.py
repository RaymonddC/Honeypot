"""Metrics — GET /metrics, and the counters that make a lost audit entry visible.

Two things are worth testing here and one of them is not "does the endpoint
return 200".

**The privacy boundary.** This app's URLs carry case ids, wallet addresses and
user ids. A metrics store is typically third-party, less protected than the
database, and entirely outside the RLS boundary the rest of this codebase is
careful about — so a raw path in a label would copy tenant identifiers into it,
and blow up cardinality besides. The label must always be the route TEMPLATE.
Several tests below hammer that specific property with real ids, because it is
the failure that would be discovered late and could not be undone (the data is
already in someone else's system by then).

**The dropped-audit-entry counter.** ``verify_chain`` detects a forked or edited
chain and CANNOT detect an entry that was never written — no gap appears in the
prev-links. The counter is the only thing that makes that loss visible, so a test
that only checks it renders would miss the point; these drive real failures
through ``record_action``/``record_denial`` and assert the counter moved.
"""

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

from app.core import metrics
from app.core.audit import (
    DENIAL_CAP,
    USER_ROLE_CHANGED,
    record_action,
    record_denial,
    reset_audit_store,
)
from app.core.config import get_settings
from app.main import app

client = TestClient(app)

TOKEN = "test-scrape-token"  # noqa: S105 - test fixture, not a credential


@pytest.fixture(autouse=True)
def _clean_metrics():
    metrics.reset()
    reset_audit_store()
    yield
    metrics.reset()
    reset_audit_store()


@pytest.fixture
def scrapeable():
    """Enable /metrics for one test."""
    settings = get_settings()
    prior = settings.metrics_token
    settings.metrics_token = TOKEN
    yield {"Authorization": f"Bearer {TOKEN}"}
    settings.metrics_token = prior


def _scrape(headers) -> str:
    r = client.get("/metrics", headers=headers)
    assert r.status_code == 200, r.text
    return r.text


# --- the privacy boundary -----------------------------------------------------


def test_labels_use_the_route_template_never_the_requested_path(scrapeable):
    """THE test. A case id in the URL must not become a label.

    Route templates are bounded by the route table; requested paths are
    attacker-controlled and carry tenant data. Getting this wrong is not a
    tuning mistake — it exports identifiers into a system outside the RLS
    boundary, and you cannot un-send them.
    """
    case_id = str(uuid.uuid4())
    wallet = "TXtR9dQpR7mK2vN8fLbY3wZaQ4pJ6"
    client.get(f"/api/cases/{case_id}")
    client.get(f"/api/trace/{wallet}")

    body = _scrape(scrapeable)

    assert case_id not in body, "a case id reached the metrics output"
    assert wallet not in body, "a wallet address reached the metrics output"
    # And the template IS present, so we know the request was actually counted
    # and this did not pass merely because nothing was recorded.
    assert "/api/cases/{case_id}" in body, (
        f"expected the route template in the output; got:\n{body}"
    )


def test_no_tenant_identifier_is_ever_a_label(scrapeable):
    """No agency_id, user_id or case_id labels, at all, by construction."""
    from tests.conftest import bearer

    headers = bearer()
    created = client.post("/api/cases", json={"title": "Metrics"}, headers=headers)
    body = _scrape(scrapeable)

    for forbidden in ("agency_id=", "user_id=", "case_id=", "actor="):
        assert forbidden not in body, f"{forbidden!r} appears as a label:\n{body}"
    if created.status_code == 201:
        assert created.json()["id"] not in body


def test_an_unmatched_path_collapses_to_one_series(scrapeable):
    """Otherwise anyone could mint unlimited series by requesting junk URLs —
    both a cardinality bomb and a way to write arbitrary text into our metrics."""
    for i in range(5):
        client.get(f"/definitely-not-a-route-{i}")

    body = _scrape(scrapeable)
    assert "definitely-not-a-route" not in body, "raw 404 paths became labels"
    assert metrics.UNMATCHED in body
    unmatched_series = [
        line for line in body.splitlines()
        if line.startswith("ittu_http_requests_total{") and metrics.UNMATCHED in line
    ]
    assert len(unmatched_series) == 1, (
        f"expected one folded series for 5 junk URLs, got {unmatched_series}"
    )


def test_series_are_capped_so_a_future_leak_cannot_take_the_store_down():
    """Belt and braces behind the template rule: if a bug ever starts feeding
    unbounded label values, fold them rather than emitting them forever."""
    counter = metrics.Counter("t_total", "t", ("route",))
    for i in range(metrics.MAX_SERIES_PER_METRIC + 50):
        counter.inc(f"/route-{i}")

    assert len(counter._values) == metrics.MAX_SERIES_PER_METRIC + 1, (
        f"expected the cap plus one overflow series, got {len(counter._values)}"
    )
    assert counter.value(metrics.OVERFLOW) == 50


# --- access control -----------------------------------------------------------


def test_metrics_404s_when_no_token_is_configured():
    """An unconfigured deployment must look like one with no metrics at all —
    not like one with metrics you failed to authenticate against."""
    settings = get_settings()
    prior = settings.metrics_token
    settings.metrics_token = ""
    try:
        assert client.get("/metrics").status_code == 404
        assert client.get("/metrics", headers={"Authorization": "Bearer x"}).status_code == 404
    finally:
        settings.metrics_token = prior


def test_metrics_requires_the_token_and_404s_without_it(scrapeable):
    """Unlike /health and /ready — those carry booleans a probe needs and cannot
    supply a token for. This lists every route and its traffic volume."""
    assert client.get("/metrics").status_code == 404
    assert client.get("/metrics", headers={"Authorization": "Bearer wrong"}).status_code == 404
    assert client.get("/metrics", headers=scrapeable).status_code == 200


def test_the_exposition_is_prometheus_text_with_the_negotiable_version(scrapeable):
    r = client.get("/metrics", headers=scrapeable)
    assert r.headers["content-type"].startswith("text/plain")
    assert "version=0.0.4" in r.headers["content-type"], (
        f"scrapers content-negotiate on this: {r.headers['content-type']}"
    )


# --- request metrics ----------------------------------------------------------


def test_requests_and_latency_are_recorded_per_route_method_and_status(scrapeable):
    client.get("/health")
    client.get("/health")
    client.get("/api/cases/not-a-uuid-at-all")

    body = _scrape(scrapeable)
    assert 'ittu_http_requests_total{method="GET",route="/health",status="200"} 2' in body, (
        f"expected two counted /health calls:\n{body}"
    )
    assert "ittu_http_request_duration_seconds_bucket" in body
    assert 'ittu_http_request_duration_seconds_count{method="GET",route="/health"} 2' in body


def test_histogram_buckets_are_cumulative():
    """Non-cumulative buckets produce quantiles that look plausible and are
    wrong, which is worse than having no metric at all."""
    h = metrics.Histogram("t_seconds", "t", ("route",), buckets=(0.1, 1.0))
    h.observe(0.05, "/a")   # <= 0.1  and <= 1.0
    h.observe(0.5, "/a")    #          <= 1.0
    h.observe(5.0, "/a")    #                    only +Inf

    rendered = "\n".join(h.render())
    assert 't_seconds_bucket{route="/a",le="0.1"} 1' in rendered, rendered
    assert 't_seconds_bucket{route="/a",le="1.0"} 2' in rendered, rendered
    assert 't_seconds_bucket{route="/a",le="+Inf"} 3' in rendered, rendered
    assert 't_seconds_count{route="/a"} 3' in rendered, rendered


def test_label_values_are_escaped():
    """An unescaped quote or newline in a label produces output a scraper
    rejects — losing every metric, not just the malformed one."""
    counter = metrics.Counter("t_total", "t", ("route",))
    counter.inc('we"ird\nvalue\\here')
    rendered = "\n".join(counter.render())
    assert '\\"' in rendered and "\\n" in rendered and "\\\\" in rendered, rendered
    assert len(rendered.splitlines()) == 3, f"a raw newline split the output:\n{rendered}"


# --- the point of the exercise: a lost audit entry is visible -----------------


def test_a_dropped_audit_entry_increments_the_counter(scrapeable):
    """The hole this closes: verify_chain CANNOT see an entry that was never
    written — no gap appears in the prev-links — so the chain verifies clean
    while a record is missing. This counter is the only signal."""

    class Exploding:
        def add(self, *a, **k):
            raise RuntimeError("db is down")

        async def execute(self, *a, **k):
            raise RuntimeError("db is down")

    settings = get_settings()
    prior = settings.persistence
    settings.persistence = "postgres"  # or the memory repo answers and nothing fails
    try:
        assert asyncio.run(
            record_action(Exploding(), agency_id="ag-1", action=USER_ROLE_CHANGED)
        ) is None
    finally:
        settings.persistence = prior

    assert metrics.audit_dropped.value(metrics.DROP_ERROR) == 1, (
        "an audit entry was silently lost and nothing counted it"
    )
    body = _scrape(scrapeable)
    assert 'ittu_audit_entries_dropped_total{reason="error"} 1' in body, body


def test_an_unattributed_entry_counts_as_dropped(scrapeable):
    asyncio.run(record_action(None, agency_id=None, action=USER_ROLE_CHANGED))
    assert metrics.audit_dropped.value(metrics.DROP_NO_AGENCY) == 1
    assert 'reason="no_agency"' in _scrape(scrapeable)


def test_written_entries_give_the_dropped_count_a_denominator(scrapeable):
    """A bare "3 dropped" is unreadable — 3 out of 4 is an outage, 3 out of
    400000 is a blip. Successes and denials are counted separately."""
    asyncio.run(record_action(None, agency_id="ag-1", action=USER_ROLE_CHANGED))
    asyncio.run(
        record_denial(
            agency_id="ag-1", action=USER_ROLE_CHANGED, denial_code="privilege_escalation",
            actor_user_id="u-1",
        )
    )
    body = _scrape(scrapeable)
    assert 'ittu_audit_entries_written_total{outcome="success"} 1' in body, body
    assert 'ittu_audit_entries_written_total{outcome="denied"} 1' in body, body


def test_rate_capped_denials_are_counted_apart_from_failures(scrapeable):
    """Suppression is a policy decision; a drop is a failure. Conflating them
    would make the alert that matters fire on ordinary abuse."""

    async def run():
        for _ in range(DENIAL_CAP + 3):
            await record_denial(
                agency_id="ag-cap", action=USER_ROLE_CHANGED,
                denial_code="privilege_escalation", actor_user_id="noisy",
            )

    asyncio.run(run())

    assert metrics.audit_denials_suppressed.value() == 3
    assert metrics.audit_dropped.value(metrics.DROP_ERROR) == 0, (
        "suppression must not be counted as a failure to write"
    )
    body = _scrape(scrapeable)
    assert "ittu_audit_denials_suppressed_total 3" in body, body
