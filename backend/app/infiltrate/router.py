"""INFILTRATE router — Honeypot console API (docs/API-Contract.md).

GET  /api/personas                       → [persona]
GET  /api/sessions                       → [scam_session]
POST /api/sessions                       → scam_session   # start POC replay, runs loop+extraction
GET  /api/sessions/{id}                  → scam_session
GET  /api/sessions/{id}/messages         → [message]      # hash-chained log (+ inline entities)
GET  /api/entities?session=&status=      → [entity]       # extracted, confidence-scored
POST /api/entities/{id}/review {status}  → entity         # confirm/reject/poisoned
GET  /api/syndicates                     → [syndicate]

Endpoints compute in-memory from the offline replay adapter (POC pattern,
mirrors P1–P3). LIVE channel/LLM adapters fail loudly — never silent network.
"""

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from app.infiltrate import service
from app.infiltrate.channels import ChannelAdapter
from app.infiltrate.gateway import LLMGateway
from app.infiltrate.service import (
    ChannelDep,
    EntityOut,
    GatewayDep,
    MessageOut,
    PersonaOut,
    SessionOut,
    StartSessionRequest,
    SyndicateOut,
)

router = APIRouter(tags=["infiltrate"])


def _not_found(kind: str, item_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": f"{kind}_not_found", "message": f"No {kind} with id {item_id}"},
    )


class ReviewRequest(BaseModel):
    status: Literal["unverified", "confirmed", "rejected", "poisoned"]


@router.get("/personas", response_model=list[PersonaOut])
async def get_personas() -> list[PersonaOut]:
    """The honeypot persona pool (POC ships 'Bu Sari')."""
    return service.list_personas()


@router.get("/sessions", response_model=list[SessionOut])
async def get_sessions() -> list[SessionOut]:
    """All engaged honeypot sessions (RLS-scoped in LIVE)."""
    return service.list_sessions()


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def post_session(
    body: StartSessionRequest | None = None,
    channel: ChannelAdapter = ChannelDep,
    gateway: LLMGateway = GatewayDep,
) -> SessionOut:
    """Start a session: POC replays the scripted scam convo through the agent
    loop, hash-chains every message, extracts + reconciles entities, classifies
    the crime, and clusters a syndicate — returned as a finished session."""
    return await service.start_session(body or StartSessionRequest(), channel, gateway)


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: str) -> SessionOut:
    session = service.get_session(session_id)
    if session is None:
        raise _not_found("session", session_id)
    return session


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def get_session_messages(session_id: str) -> list[MessageOut]:
    """The hash-chained transcript; each message carries its inline extracted entities."""
    messages = service.get_messages(session_id)
    if messages is None:
        raise _not_found("session", session_id)
    return messages


@router.get("/entities", response_model=list[EntityOut])
async def get_entities(
    session: str | None = Query(default=None, description="filter by session id"),
    status: str | None = Query(default=None, description="filter by review_status"),
) -> list[EntityOut]:
    """Extracted, confidence-scored entities (Layer-A validated + Layer-B reconciled)."""
    return service.list_entities(session_id=session, status=status)


@router.post("/entities/{entity_id}/review", response_model=EntityOut)
async def post_entity_review(entity_id: str, body: ReviewRequest) -> EntityOut:
    """Analyst review — confirm/reject/flag-poisoned (human-in-the-loop)."""
    entity = service.review_entity(entity_id, body.status)
    if entity is None:
        raise _not_found("entity", entity_id)
    return entity


@router.get("/syndicates", response_model=list[SyndicateOut])
async def get_syndicates() -> list[SyndicateOut]:
    """Syndicate profiles clustered from extracted entities."""
    return service.list_syndicates()


@router.get("/infiltrate/ping")
async def ping() -> dict[str, str]:
    return {"module": "infiltrate"}
