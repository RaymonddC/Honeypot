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

# Model registry (imported for side effects, like migrations/env.py does).
# SQLAlchemy resolves a ForeignKey by TABLE NAME when the mapper is configured,
# so every model module must be imported before an actor maps a row — otherwise
# the first ORM write raises NoReferencedTableError (e.g. writing a ScamSession
# fails on scam_sessions.agency_id -> core.agencies when app.core.models was
# never imported). The API can't hit this because it imports every router, and
# tests can't because they import broadly; a worker process only imports what
# the actor chain happens to pull in, so it must be explicit here.
from app.action import models as _action_models  # noqa: F401
from app.casedata import models as _casedata_models  # noqa: F401
from app.chain import models as _chain_models  # noqa: F401
from app.core import models as _core_models  # noqa: F401
from app.fiat import models as _fiat_models  # noqa: F401
from app.honeypot_ops import models as _honeypot_models  # noqa: F401
from app.intel import models as _intel_models  # noqa: F401

# Actor registration (imported for side effects):
#   dispatch_notifications — C1 signed/retried webhook delivery
#   dial_target            — outbound honeypot dialing (POC-simulated in phase 4)
from app.honeypot_ops.dialer import dial_target  # noqa: F401
from app.uncover.notifications import dispatch_notifications  # noqa: F401

import dramatiq  # noqa: E402


@dramatiq.actor
def heartbeat() -> None:
    """No-op example actor (P0 scaffold — proves the wiring)."""
