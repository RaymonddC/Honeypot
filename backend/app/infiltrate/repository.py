"""INFILTRATE persistence boundary (docs/Persistence-Plan.md P-2).

Repository interface behind the 4 intel stores (sessions/messages/entities/
syndicates) that ``infiltrate/service.py`` used to own as bare module-level
dicts. An in-memory impl backs the POC + the existing fast test suite today;
a Postgres impl lands in P-2b.

Persistence is selected by ``settings.persistence`` — a separate axis from the
poc/live MODE registry (``app.core.adapters``). MODE picks *which adapter*
answers an external boundary (channel/llm/tts/...); persistence picks *where
state lives*. The two are orthogonal, so this factory intentionally does NOT
go through ``app.core.adapters.register`` / ``get_adapter`` (P-2 lead call).
"""

from functools import lru_cache
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.core.config import get_settings

if TYPE_CHECKING:
    from app.infiltrate.service import EntityOut, MessageOut, SessionOut, SyndicateOut


@runtime_checkable
class InfiltrateRepository(Protocol):
    """Storage surface ``infiltrate/service.py`` needs — derived from the
    actual read/write call sites of the 4 stores it used to own directly.
    Returns/accepts the SAME Pydantic models the service already builds
    (``SessionOut``/``MessageOut``/``EntityOut``/``SyndicateOut``); the
    contract at the service boundary does not change.

    Every read/write method is ``async`` (P-2b): the Postgres impl does real
    I/O over an ``AsyncSession``, and a Protocol can't have one impl awaiting
    and another not. ``InMemoryInfiltrateRepository``'s methods are ``async``
    too — trivial 1-line coroutines wrapping the same dict ops, no behavior
    change — so both impls satisfy one signature. ``reset()`` stays sync: it's
    a memory-only test hook (``service.reset_stores`` calls the singleton
    directly, never through this Protocol — see its docstring).
    """

    # -- sessions ----------------------------------------------------------- #
    async def save_session(self, session: "SessionOut") -> None: ...

    async def get_session(self, session_id: str) -> "SessionOut | None": ...

    async def list_sessions(self) -> list["SessionOut"]: ...

    # -- messages (keyed by session_id) -------------------------------------- #
    async def save_messages(self, session_id: str, messages: list["MessageOut"]) -> None:
        """Set/replace the full message list for a session (first assembly)."""
        ...

    async def append_messages(self, session_id: str, messages: list["MessageOut"]) -> None:
        """Add messages to an existing session's transcript (live ``/turn``)."""
        ...

    async def get_messages(self, session_id: str) -> list["MessageOut"] | None: ...

    # -- entities ------------------------------------------------------------- #
    async def save_entity(self, entity: "EntityOut") -> None:
        """Insert a new entity, or persist in-place edits (e.g. review-status
        updates — the service mutates the returned object, then re-saves)."""
        ...

    async def get_entity(self, entity_id: str) -> "EntityOut | None": ...

    async def list_entities(
        self, session_id: str | None = None, status: str | None = None
    ) -> list["EntityOut"]: ...

    # -- syndicates ------------------------------------------------------------ #
    async def save_syndicate(self, syndicate: "SyndicateOut") -> None: ...

    async def list_syndicates(self) -> list["SyndicateOut"]: ...

    # -- test/seed hook ---------------------------------------------------------- #
    def reset(self) -> None:
        """Clear all stored state — existing test hook (``service.reset_stores``).
        Sync, memory-only (see class docstring)."""
        ...


class InMemoryInfiltrateRepository:
    """POC impl — the 4 module-level dicts that used to live in service.py,
    unchanged in behavior, moved behind ``InfiltrateRepository``.

    Methods are ``async`` to satisfy the Protocol (P-2b) — trivial coroutines
    around the same synchronous dict ops, no actual I/O, no behavior change."""

    def __init__(self) -> None:
        self._sessions: dict[str, "SessionOut"] = {}
        self._messages: dict[str, list["MessageOut"]] = {}
        self._entities: dict[str, "EntityOut"] = {}
        self._syndicates: dict[str, "SyndicateOut"] = {}

    async def save_session(self, session: "SessionOut") -> None:
        self._sessions[session.id] = session

    async def get_session(self, session_id: str) -> "SessionOut | None":
        return self._sessions.get(session_id)

    async def list_sessions(self) -> list["SessionOut"]:
        return list(self._sessions.values())

    async def save_messages(self, session_id: str, messages: list["MessageOut"]) -> None:
        self._messages[session_id] = messages

    async def append_messages(self, session_id: str, messages: list["MessageOut"]) -> None:
        self._messages.setdefault(session_id, []).extend(messages)

    async def get_messages(self, session_id: str) -> list["MessageOut"] | None:
        return self._messages.get(session_id)

    async def save_entity(self, entity: "EntityOut") -> None:
        self._entities[entity.id] = entity

    async def get_entity(self, entity_id: str) -> "EntityOut | None":
        return self._entities.get(entity_id)

    async def list_entities(
        self, session_id: str | None = None, status: str | None = None
    ) -> list["EntityOut"]:
        items = list(self._entities.values())
        if session_id is not None:
            items = [e for e in items if e.session_id == session_id]
        if status is not None:
            items = [e for e in items if e.review_status == status]
        return items

    async def save_syndicate(self, syndicate: "SyndicateOut") -> None:
        self._syndicates[syndicate.id] = syndicate

    async def list_syndicates(self) -> list["SyndicateOut"]:
        return list(self._syndicates.values())

    def reset(self) -> None:
        self._sessions.clear()
        self._messages.clear()
        self._entities.clear()
        self._syndicates.clear()


@lru_cache
def _memory_repository() -> InMemoryInfiltrateRepository:
    """Process-wide singleton (mirrors ``get_settings()``'s caching) so the
    repo behaves exactly like the module dicts it replaces — one store per
    process, shared across requests, not re-created per call."""
    return InMemoryInfiltrateRepository()


def get_infiltrate_repository() -> InfiltrateRepository:
    """FastAPI-dependency-friendly factory — selects the impl from
    ``settings.persistence``. "memory" (default) is today's POC behavior;
    "postgres" is P-2b."""
    settings = get_settings()
    if settings.persistence == "postgres":
        raise NotImplementedError(
            "Postgres INFILTRATE repository lands in P-2b (docs/Persistence-Plan.md)"
        )
    return _memory_repository()
