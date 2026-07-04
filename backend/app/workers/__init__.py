"""Dramatiq broker setup (Redis) + example actor.

Run a worker with:

    dramatiq app.workers

CPU-bound work (ML, graph algorithms) goes here — off the API event loop.
"""

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.core.config import get_settings

broker = RedisBroker(url=get_settings().redis_url)
dramatiq.set_broker(broker)


@dramatiq.actor
def heartbeat() -> None:
    """No-op example actor (P0 scaffold — proves the wiring)."""
