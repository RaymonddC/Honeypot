"""Dramatiq worker entrypoint — the broker + every actor the worker must serve.

Run a worker with:

    dramatiq app.workers

Dramatiq only imports THIS module, so an actor that isn't reachable from here is
never registered and its queue is never consumed. The imports below are
therefore load-bearing, not tidiness: each one registers actors with the broker.

The broker itself lives in ``app.core.broker`` (imported first, and also by each
actor module) so actors bind to Redis whether they're declared in this worker
process or pulled in by the API — see that module for why the ordering matters.
"""

# Sets the Redis broker. Must precede the actor imports below.
from app.core.broker import broker  # noqa: F401

# Actor registration (imported for side effects):
#   dispatch_notifications — C1 signed/retried webhook delivery
#   dial_target            — outbound honeypot dialing (POC-simulated in phase 4)
from app.honeypot_ops.dialer import dial_target  # noqa: F401
from app.uncover.notifications import dispatch_notifications  # noqa: F401

import dramatiq  # noqa: E402


@dramatiq.actor
def heartbeat() -> None:
    """No-op example actor (P0 scaffold — proves the wiring)."""
