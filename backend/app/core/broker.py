"""The Dramatiq broker — ONE definition, imported before any actor is declared.

Why this module exists: ``@dramatiq.actor`` binds to whatever broker is current
**at decoration time**. If a module defining an actor is imported without the
Redis broker having been set, that actor is silently bound to dramatiq's default
(RabbitMQ) instead, and ``.send()`` from the API would enqueue into a broker no
worker is reading — the message just disappears. Setting the broker afterwards
does not rebind actors that already exist.

Previously the setup lived only in ``app/workers/__init__.py``, which nothing
imports except ``dramatiq app.workers``. Every actor imported through the API
(``app.uncover.notifications``, and now the dialer) therefore bound to the
default broker. Importing THIS module at the top of any actor-defining module
makes the binding correct in both the API and the worker process.

Constructing a ``RedisBroker`` does not connect — it only builds a lazy
connection pool — so importing this is safe with no Redis running (tests, CI,
and any POC deployment that never enqueues).
"""

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.config import get_settings

broker = RedisBroker(url=get_settings().redis_url)
dramatiq.set_broker(broker)
