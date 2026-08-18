"""Request correlation — one id that ties a user's report to a log line.

The gap this closes: when something failed, the only signal was "it didn't
work". Reproducing meant guessing which of thousands of log lines belonged to
that request. Now every response carries ``X-Request-ID``, every error envelope
repeats it, and the request's log line uses the same id — so "it failed, id
a1b2c3d4" is enough to find exactly what happened.

An inbound ``X-Request-ID`` is honoured rather than replaced, because Render
(and any proxy or client) may already have assigned one; generating a fresh id
here would break the trail at our boundary, which is precisely where it needs to
join up.

**What is deliberately not logged:** query strings and request bodies. Query
strings are fine today, but they are exactly where a token or a phone number
ends up tomorrow, and log lines outlive the reasoning that made them safe.
Method, path, status and duration answer the operational question without that
risk.
"""

import contextvars
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

_log = logging.getLogger("ittu.request")

# Readable by anything that wants to tag its own output with the current request
# (see `current_request_id`), without threading the id through every signature.
_request_id: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="")

# Health probes hit constantly; logging each one buries the lines that matter.
# /ready is still logged — it is checked by a human when something is wrong, and
# knowing WHEN it was checked is part of the story.
QUIET_PATHS = {"/health"}

REQUEST_ID_HEADER = "X-Request-ID"


def current_request_id() -> str:
    """The in-flight request's id, or "" outside a request (e.g. in a worker)."""
    return _request_id.get()


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign/propagate a request id, then log the request's outcome."""

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request, call_next):
        incoming = request.headers.get(REQUEST_ID_HEADER, "").strip()
        # Cap the length: an id is echoed into responses and logs, so an
        # attacker-supplied 10MB header should not become a 10MB log line.
        request_id = (incoming[:64] or uuid.uuid4().hex[:12])
        token = _request_id.set(request_id)
        request.state.request_id = request_id

        started = time.perf_counter()
        status = 500  # if the handler explodes, that IS the outcome to log
        try:
            response = await call_next(request)
            status = response.status_code
            response.headers[REQUEST_ID_HEADER] = request_id
            return response
        finally:
            elapsed_ms = (time.perf_counter() - started) * 1000
            if request.url.path not in QUIET_PATHS:
                # Deliberately no query string and no body — see the module docstring.
                _log.info(
                    "%s %s -> %s (%.1fms) [%s]",
                    request.method,
                    request.url.path,
                    status,
                    elapsed_ms,
                    request_id,
                )
            _request_id.reset(token)
