"""Process metrics in Prometheus text format — rate, latency, errors, and the
audit entries we failed to write.

Two things this module exists for, in order of importance:

**1. Making a lost audit entry visible.** ``app/core/audit.py`` never raises: if
an entry cannot be written, the action still stands and the failure is logged.
That is the right trade (a failed audit insert rolling back a completed case
update is worse), but it left a hole — ``verify_chain`` detects a *forked* or
*edited* chain and cannot detect an entry that was never written at all. No gap
appears in the prev-links, so the log verifies clean and the loss is invisible
to everything except whoever happens to be tailing stderr. For an evidentiary
system that is the wrong kind of quiet. ``audit_entries_dropped_total`` turns it
into something alerting can see, with ``audit_entries_written_total`` as the
denominator so a rate is meaningful.

**2. The operational question `/ready` cannot answer.** ``/ready`` says "is it
broken right now". It cannot say "was it broken at 03:00" or "is latency
creeping". That needs a time series, which needs a scrapeable endpoint.

**No labels carry identifiers — this is a privacy boundary, not a tuning
choice.** This app's URLs contain case ids, wallet addresses and user ids
(``/api/cases/9f79eb96-…/entities/TXyz…``). Labelling by raw path would copy
tenant identifiers and blockchain addresses into a metrics store that is
typically third-party, less protected than the database, and entirely outside
the RLS boundary the rest of this codebase is careful about — and it would blow
up cardinality until the store fell over. So the ``route`` label is always the
ROUTE TEMPLATE from the matched route (``/api/cases/{case_id}``), never the
requested URL, and anything unmatched collapses to ``<unmatched>`` rather than
becoming a label of its own. There are no agency, user, or case labels anywhere,
deliberately: see the note in ``docs/Deploy.md`` §8 on why per-tenant metrics
would be a product decision rather than a config change.

**Hand-rolled rather than ``prometheus_client``.** The exposition format is a few
lines of text, the whole surface here is three counters and one histogram, and a
dependency would bring its own multiprocess machinery we do not want. If this
ever grows past "a handful of series", swap it — the endpoint contract will not
change.

**Single process.** These counters live in memory, so they describe THIS worker.
The API runs one uvicorn worker today (``scripts/start.sh`` passes no
``--workers``), which makes them complete. If workers are ever added, a scrape
lands on whichever one answers and the numbers become per-worker and jumpy —
that needs either per-worker scrape targets or the multiprocess collector, and
it is called out in ``docs/Deploy.md`` §8.
"""

import threading
from dataclasses import dataclass, field

# A hard ceiling on distinct label combinations per metric. Nothing today should
# come close (routes × methods × statuses is bounded by the route table), so
# hitting it means a bug started feeding unbounded values — most likely a raw
# path where a template belonged. Folding into one <overflow> series keeps a
# metrics store from being taken down by our own defect, and makes the defect
# visible instead of merely expensive.
MAX_SERIES_PER_METRIC = 500
OVERFLOW = "<overflow>"

# Unmatched requests (404s, probes for /wp-login.php) share one series. Using
# the requested path here is exactly the cardinality-and-privacy mistake this
# module exists to avoid — an attacker could mint unlimited series at will.
UNMATCHED = "<unmatched>"

# Seconds. Tuned for an HTTP API in front of Postgres: tight buckets under 100ms
# where most reads land, then coarse ones out to the range where a blockchain
# provider call or a PDF render lives.
DURATION_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

_lock = threading.Lock()


def _escape(value: str) -> str:
    """Escape a label VALUE per the exposition format (backslash, quote, newline)."""
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _render_labels(names: tuple[str, ...], values: tuple[str, ...], extra: str = "") -> str:
    parts = [f'{n}="{_escape(v)}"' for n, v in zip(names, values)]
    if extra:
        parts.append(extra)
    return "{" + ",".join(parts) + "}" if parts else ""


@dataclass
class Counter:
    name: str
    help: str
    labelnames: tuple[str, ...] = ()
    _values: dict[tuple[str, ...], int] = field(default_factory=dict)

    def inc(self, *labels: str, amount: int = 1) -> None:
        key = _capped(self._values, tuple(labels), self.labelnames)
        with _lock:
            self._values[key] = self._values.get(key, 0) + amount

    def value(self, *labels: str) -> int:
        return self._values.get(tuple(labels), 0)

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} counter"]
        # Sorted so a diff between two scrapes is readable by a human.
        for key, val in sorted(self._values.items()):
            out.append(f"{self.name}{_render_labels(self.labelnames, key)} {val}")
        return out


@dataclass
class Histogram:
    name: str
    help: str
    labelnames: tuple[str, ...] = ()
    buckets: tuple[float, ...] = DURATION_BUCKETS
    _counts: dict[tuple[str, ...], list[int]] = field(default_factory=dict)
    _sums: dict[tuple[str, ...], float] = field(default_factory=dict)

    def observe(self, value: float, *labels: str) -> None:
        key = _capped(self._sums, tuple(labels), self.labelnames)
        with _lock:
            counts = self._counts.setdefault(key, [0] * (len(self.buckets) + 1))
            self._sums[key] = self._sums.get(key, 0.0) + value
            # Stored ALREADY CUMULATIVE ("le" semantics): an observation counts
            # in its own bucket and every larger one, so counts[i] is "how many
            # were <= buckets[i]". Getting this wrong yields quantiles that look
            # plausible and are wrong, which is worse than having no metric.
            for i, edge in enumerate(self.buckets):
                if value <= edge:
                    counts[i] += 1
            counts[-1] += 1  # the +Inf bucket == total observations

    def count(self, *labels: str) -> int:
        return self._counts.get(tuple(labels), [0])[-1]

    def render(self) -> list[str]:
        out = [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} histogram"]
        for key in sorted(self._sums):
            counts = self._counts[key]
            for i, edge in enumerate(self.buckets):
                labels = _render_labels(self.labelnames, key, f'le="{_fmt(edge)}"')
                out.append(f"{self.name}_bucket{labels} {counts[i]}")
            inf_labels = _render_labels(self.labelnames, key, 'le="+Inf"')
            plain = _render_labels(self.labelnames, key)
            out.append(f"{self.name}_bucket{inf_labels} {counts[-1]}")
            out.append(f"{self.name}_sum{plain} {self._sums[key]}")
            out.append(f"{self.name}_count{plain} {counts[-1]}")
        return out


def _fmt(value: float) -> str:
    """Bucket edges must render identically on every scrape or the series splits."""
    return repr(value)


def _capped(store: dict, key: tuple[str, ...], labelnames: tuple[str, ...]) -> tuple[str, ...]:
    """Fold a new label set into <overflow> once the ceiling is reached."""
    if key in store or len(store) < MAX_SERIES_PER_METRIC:
        return key
    return tuple(OVERFLOW for _ in labelnames)


# --------------------------------------------------------------------------- #
# The metrics themselves
# --------------------------------------------------------------------------- #

http_requests = Counter(
    "ittu_http_requests_total",
    "HTTP requests handled, by route template, method and status.",
    ("method", "route", "status"),
)

http_duration = Histogram(
    "ittu_http_request_duration_seconds",
    "HTTP request latency, by route template and method.",
    ("method", "route"),
)

# The reason this module was built. Every path that loses an audit entry
# increments this — see app/core/audit.py.
audit_dropped = Counter(
    "ittu_audit_entries_dropped_total",
    "Audit entries that could NOT be written and are permanently lost, by reason.",
    ("reason",),
)

audit_written = Counter(
    "ittu_audit_entries_written_total",
    "Audit entries successfully appended, by outcome (success|denied). The "
    "denominator that makes the dropped count a rate rather than a bare number.",
    ("outcome",),
)

audit_denials_suppressed = Counter(
    "ittu_audit_denials_suppressed_total",
    "Denials deliberately NOT recorded because the per-actor rate cap was "
    "reached. Expected under abuse; distinct from a dropped entry, which is a "
    "failure.",
)

_ALL = (http_requests, http_duration, audit_dropped, audit_written, audit_denials_suppressed)

# Reasons for audit_dropped, named so a dashboard legend reads as a diagnosis.
DROP_SEQ_CONTENTION = "seq_contention"
DROP_CHAIN_HEAD_UNCOMMITTED = "chain_head_uncommitted"
DROP_ERROR = "error"
DROP_NO_AGENCY = "no_agency"


# id(route object) -> full path template, plus a strong reference to the app so
# those ids cannot be recycled underneath us. Built once; see _full_templates.
_templates: dict[int, str] = {}
_templates_app: object | None = None


def _full_templates(app) -> dict[int, str]:
    """Map every route object to its FULL path template.

    Needed because ``scope["route"]`` gives the route as its own router declared
    it. FastAPI 0.139 attaches ``app.include_router(..., prefix="/api")`` as a
    LAZY ``_IncludedRouter`` rather than flattening the paths, so the matched
    route's ``.path`` is ``/cases/{case_id}``, the ``/api`` prefix lives on the
    wrapper, and ``root_path`` is not set — there is nothing in the scope to
    recover the prefix from. A test caught this: the label was silently missing
    the prefix, which is both wrong and a collision risk between two routers
    declaring the same relative path.

    The wrapper exposes neither ``.routes`` nor ``.prefix``; the real router is
    at ``.original_router`` and the prefix at ``.include_context.prefix``. Those
    are FastAPI internals and may move, so every lookup here is defensive and
    the caller degrades to the bare (prefix-less) template rather than failing —
    and never, under any circumstance, to the requested path. If a FastAPI
    upgrade changes this shape, ``test_labels_use_the_route_template_never_the_
    requested_path`` goes red, which is the intended alarm.

    Walked once and remembered, so none of this happens per request.
    """
    global _templates, _templates_app
    if _templates_app is app and _templates:
        return _templates

    mapping: dict[int, str] = {}

    def children_of(route) -> tuple[list, str]:
        """(sub-routes, the prefix they sit behind) — or ([], "") for a leaf."""
        direct = getattr(route, "routes", None)
        if direct:
            step = getattr(route, "prefix", None) or getattr(route, "path", "") or ""
            return list(direct), step
        original = getattr(route, "original_router", None)  # FastAPI _IncludedRouter
        if original is not None:
            context = getattr(route, "include_context", None)
            step = (getattr(context, "prefix", "") or "") + (
                getattr(original, "prefix", "") or ""
            )
            return list(getattr(original, "routes", []) or []), step
        return [], ""

    def walk(routes, prefix: str) -> None:
        for route in routes:
            children, step = children_of(route)
            if children:
                walk(children, prefix + step)
                continue
            path = getattr(route, "path", None)
            if isinstance(path, str) and path:
                mapping[id(route)] = prefix + path

    walk(getattr(app, "routes", []), "")
    _templates, _templates_app = mapping, app
    return mapping


def route_template(scope) -> str:
    """The matched route's TEMPLATE, never the requested URL.

    ``/api/cases/9f79eb96-…`` becomes ``/api/cases/{case_id}``. This one function
    is what keeps case ids, wallet addresses and user ids out of the metrics
    store — see the module docstring. Anything Starlette did not match to a
    route has no template, and must NOT fall back to the raw path: that is
    attacker-controlled and unbounded, so a junk URL would mint a series.
    """
    route = scope.get("route")
    if route is None:
        return UNMATCHED
    app = scope.get("app")
    if app is not None:
        full = _full_templates(app).get(id(route))
        if full:
            return full
    # Fallback: still a template (bounded by the route table), just possibly
    # missing a prefix. Never the requested path.
    template = getattr(route, "path", None)
    return template if isinstance(template, str) and template else UNMATCHED


def observe_request(*, method: str, scope, status: int, seconds: float) -> None:
    """Record one finished request. Never raises — metrics must not break a
    response that already succeeded."""
    try:
        route = route_template(scope)
        http_requests.inc(method, route, str(status))
        http_duration.observe(seconds, method, route)
    except Exception:  # noqa: BLE001 - bookkeeping must not break the request
        pass


def render() -> str:
    """The whole registry in Prometheus text exposition format."""
    lines: list[str] = []
    for metric in _ALL:
        lines.extend(metric.render())
    return "\n".join(lines) + "\n"


def reset() -> None:
    """Test hook — clears every series."""
    with _lock:
        for metric in _ALL:
            if isinstance(metric, Counter):
                metric._values.clear()
            else:
                metric._counts.clear()
                metric._sums.clear()
