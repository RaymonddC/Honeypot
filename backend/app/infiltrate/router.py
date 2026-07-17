"""INFILTRATE router — Honeypot console API (docs/API-Contract.md).

GET  /api/personas                       → [persona]
GET  /api/sessions                       → [scam_session]
POST /api/sessions                       → scam_session   # start POC replay, runs loop+extraction
GET  /api/sessions/{id}                  → scam_session
GET  /api/sessions/{id}/messages         → [message]      # hash-chained log (+ inline entities)
GET  /api/sessions/{id}/audio/{seq}      → voice marks    # POC: marks (browser speaks);
                                                          # LIVE: provider audio; text → 204
GET  /api/entities?session=&status=      → [entity]       # extracted, confidence-scored
POST /api/entities/{id}/review {status}  → entity         # confirm/reject/poisoned
GET  /api/syndicates                     → [syndicate]

Endpoints compute in-memory from the offline replay adapter (POC pattern,
mirrors P1–P3). LIVE channel/LLM adapters fail loudly — never silent network.
"""

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel

from app.core.auth import AuthContext, get_current_user
from app.infiltrate import service
from app.infiltrate.channels import ChannelAdapter
from app.infiltrate.gateway import LLMGateway
from app.infiltrate.repository import InfiltrateRepository
from app.infiltrate.service import (
    ChannelDep,
    EntityOut,
    GatewayDep,
    MessageOut,
    PersonaOut,
    RepoDep,
    SessionOut,
    StartSessionRequest,
    SyndicateOut,
    TTSDep,
    TurnOut,
    TurnRequest,
)
from app.infiltrate.voice import TTSAdapter, VoiceMarkOut

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
async def get_sessions(
    repo: InfiltrateRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),  # P-4a: read routes need identity
) -> list[SessionOut]:
    """All engaged honeypot sessions (RLS-scoped in LIVE)."""
    return await service.list_sessions(repo=repo)


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def post_session(
    body: StartSessionRequest | None = None,
    channel: ChannelAdapter = ChannelDep,
    gateway: LLMGateway = GatewayDep,
    repo: InfiltrateRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),  # honeypot ops need identity
) -> SessionOut:
    """Start a session: POC replays the scripted scam convo through the agent
    loop, hash-chains every message, extracts + reconciles entities, classifies
    the crime, and clusters a syndicate — returned as a finished session."""
    return await service.start_session(body or StartSessionRequest(), channel, gateway, repo)


@router.post("/sessions/{session_id}/turn", response_model=TurnOut)
async def post_session_turn(
    session_id: str,
    body: TurnRequest,
    repo: InfiltrateRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),  # live engagement needs identity
) -> TurnOut:
    """One live inbound utterance (Tier-B interactive session, mic or typed)
    → one agent turn: persona reply + Layer-A/B extraction + custody append +
    reclassify. 404 if ``session_id`` has no open interactive session (unknown
    id, or a finished scripted-replay session — start one with
    ``POST /sessions {\"interactive\": true}``)."""
    result = await service.run_one_turn(session_id, body.text, repo)
    if result is None:
        raise _not_found("session", session_id)
    return result


@router.get("/sessions/{session_id}", response_model=SessionOut)
async def get_session(
    session_id: str,
    repo: InfiltrateRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),  # P-4a: read routes need identity
) -> SessionOut:
    session = await service.get_session(session_id, repo=repo)
    if session is None:
        raise _not_found("session", session_id)
    return session


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def get_session_messages(
    session_id: str,
    repo: InfiltrateRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),  # P-4a: read routes need identity
) -> list[MessageOut]:
    """The hash-chained transcript; each message carries its inline extracted entities."""
    messages = await service.get_messages(session_id, repo=repo)
    if messages is None:
        raise _not_found("session", session_id)
    return messages


@router.get(
    "/sessions/{session_id}/audio/{seq}",
    response_model=VoiceMarkOut,
    responses={204: {"description": "Text-channel message — no audio"}},
)
async def get_session_audio(
    session_id: str,
    seq: int,
    tts: TTSAdapter = TTSDep,
    repo: InfiltrateRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),  # P-4a: read routes need identity
) -> VoiceMarkOut | Response:
    """Audio for one voice-session line. POC: per-line voice marks (speaker +
    est. duration, ``audio_url=null`` — the browser's SpeechSynthesis speaks
    it). LIVE: the configured ``ITTU_TTS_PROVIDER`` streams real audio.
    Text-session messages have no audio → 204."""
    session = await service.get_session(session_id, repo=repo)
    if session is None:
        raise _not_found("session", session_id)
    message = await service.get_message(session_id, seq, repo=repo)
    if message is None:
        raise _not_found("message", f"{session_id}#{seq}")
    if session.channel_type != "voice":
        return Response(status_code=204)
    result = await tts.synthesize(
        message.content, voice=message.meta.get("speaker", "persona")
    )
    return VoiceMarkOut(
        session_id=session_id,
        seq=seq,
        speaker=message.meta.get("speaker", "persona"),
        text=result.text,
        duration_seconds=message.meta.get("duration_seconds", result.duration_seconds),
        offset_seconds=message.meta.get("offset_seconds", 0.0),
        audio_url=result.audio_url,
        provider=result.provider,
    )


@router.get("/entities", response_model=list[EntityOut])
async def get_entities(
    session: str | None = Query(default=None, description="filter by session id"),
    status: str | None = Query(default=None, description="filter by review_status"),
    repo: InfiltrateRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),  # P-4a: read routes need identity
) -> list[EntityOut]:
    """Extracted, confidence-scored entities (Layer-A validated + Layer-B reconciled)."""
    return await service.list_entities(session_id=session, status=status, repo=repo)


@router.post("/entities/{entity_id}/review", response_model=EntityOut)
async def post_entity_review(
    entity_id: str,
    body: ReviewRequest,
    repo: InfiltrateRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),  # human-in-the-loop = named human
) -> EntityOut:
    """Analyst review — confirm/reject/flag-poisoned (human-in-the-loop)."""
    entity = await service.review_entity(entity_id, body.status, repo=repo)
    if entity is None:
        raise _not_found("entity", entity_id)
    return entity


@router.get("/syndicates", response_model=list[SyndicateOut])
async def get_syndicates(
    repo: InfiltrateRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),  # P-4a: read routes need identity
) -> list[SyndicateOut]:
    """Syndicate profiles clustered from extracted entities."""
    return await service.list_syndicates(repo=repo)


@router.get("/infiltrate/ping")
async def ping() -> dict[str, str]:
    return {"module": "infiltrate"}
