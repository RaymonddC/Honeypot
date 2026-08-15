"""INFILTRATE router — Honeypot console API (docs/API-Contract.md).

GET  /api/personas                       → [persona]
GET  /api/scenarios                       → [scenario]      # the 3 MVP scam typologies
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

import logging
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.auth import AuthContext, get_current_user
from app.core.config import get_settings
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
    ScenarioOut,
    SessionOut,
    StartSessionRequest,
    SyndicateOut,
    TTSDep,
    TurnOut,
    TurnRequest,
)
from app.infiltrate.voice import (
    TTSAdapter,
    VoiceMarkOut,
    check_elevenlabs_voice,
    estimate_duration,
    list_elevenlabs_voices,
    resolve_tts_adapter,
    synthesize_line,
)

router = APIRouter(tags=["infiltrate"])
logger = logging.getLogger(__name__)

# Per-request voice overrides (Control Panel "Advanced voice"): query param →
# Settings field name, scoped by provider. ElevenLabs only for now; other
# providers drop in the same way (add their model/voice Settings fields here).
_VOICE_OVERRIDE_FIELDS: dict[str, dict[str, str]] = {
    "elevenlabs": {
        "model": "elevenlabs_model",
        "voice_persona": "elevenlabs_voice_persona",
        "voice_scammer": "elevenlabs_voice_scammer",
    },
    "gemini": {
        "model": "gemini_tts_model",
    },
}


def _not_found(kind: str, item_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": f"{kind}_not_found", "message": f"No {kind} with id {item_id}"},
    )


class ReviewRequest(BaseModel):
    status: Literal["unverified", "confirmed", "rejected", "poisoned"]


class TtsVoicesOut(BaseModel):
    provider: str = "elevenlabs"
    configured: bool          # is an ElevenLabs key set server-side
    voices: list[dict] = []   # [{id, name}] the key can synthesize
    error: str | None = None  # short reason if the lookup failed


@router.get("/tts/voices", response_model=TtsVoicesOut)
async def get_tts_voices(
    _auth: AuthContext = Depends(get_current_user),  # Control Panel is post-login
) -> TtsVoicesOut:
    """List the voices the server's ElevenLabs key can synthesize (id + name),
    so the Control Panel can flag a bad voice ID before a call. The key never
    leaves the server — only voice id/name reach the browser."""
    settings = get_settings()
    if not settings.elevenlabs_api_key:
        return TtsVoicesOut(configured=False)
    try:
        return TtsVoicesOut(configured=True, voices=await list_elevenlabs_voices(settings))
    except httpx.HTTPError as exc:
        # bad key / ElevenLabs down — surface a short reason, never the key
        return TtsVoicesOut(configured=True, error=f"lookup_failed: {type(exc).__name__}")


class TtsVoiceCheckOut(BaseModel):
    """JSON error shape when a voice check fails (success returns audio bytes)."""

    voice_id: str
    ok: bool
    status: int | None = None
    error: str | None = None  # no_key | http_401 | http_402 | http_404 | http_422 | transport:<Type>


# Short per-speaker sample line so the played preview reflects real usage.
_VOICE_SAMPLE = {
    "persona": "Halo, selamat siang, iya betul ini Ibu Sari.",
    "scammer": "Halo Bu, ada penawaran investasi spesial untuk Anda.",
}


@router.get("/tts/voice-check")
async def get_tts_voice_check(
    voice_id: str = Query(..., min_length=1),
    voice: str = Query("persona", description="persona|scammer — picks the sample line"),
    _auth: AuthContext = Depends(get_current_user),  # Control Panel is post-login
) -> Response:
    """Test one ElevenLabs voice ID by a short **test synthesis** and return the
    audio so the Control Panel PLAYS a sample (not just validates). Uses the
    Text-to-Speech scope (the exact call a honeypot line makes), so it works
    even with a key restricted to TTS (unlike GET /tts/voices, which needs the
    Voices-read scope). The key never leaves the server. On failure, returns a
    JSON body ``{voice_id, ok:false, status?, error?}`` instead of audio."""
    text = _VOICE_SAMPLE.get(voice, "Halo, selamat siang, apa kabar?")
    res = await check_elevenlabs_voice(voice_id, text=text)
    if res.get("ok") and res.get("audio"):
        return Response(
            content=res["audio"],
            media_type="audio/mpeg",
            headers={"X-Voice-Check": "ok", "Cache-Control": "no-store"},
        )
    return JSONResponse(
        {
            "voice_id": voice_id,
            "ok": False,
            "status": res.get("status"),
            "error": res.get("error"),
        }
    )


@router.get("/personas", response_model=list[PersonaOut])
async def get_personas() -> list[PersonaOut]:
    """The honeypot persona pool (one per scam scenario)."""
    return service.list_personas()


@router.get("/scenarios", response_model=list[ScenarioOut])
async def get_scenarios() -> list[ScenarioOut]:
    """The 3 MVP honeypot scam scenarios — investment scam, judol deposit,
    crypto phishing. Pass ``{\"scenario\": <key>}`` to POST /sessions to replay one."""
    return service.list_scenarios()


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
    provider: str | None = Query(
        default=None,
        description="per-request TTS override: elevenlabs|gemini|google|browser",
    ),
    model: str | None = Query(default=None, description="TTS model override (provider-specific)"),
    voice_persona: str | None = Query(default=None, description="voice ID for the persona speaker"),
    voice_scammer: str | None = Query(default=None, description="voice ID for the scammer speaker"),
    tts: TTSAdapter = TTSDep,
    repo: InfiltrateRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),  # P-4a: read routes need identity
) -> VoiceMarkOut | Response:
    """Audio for one voice-session line.

    - **LIVE** (`ITTU_TTS_PROVIDER=elevenlabs|google`): returns the synthesized
      audio **bytes** (`audio/mpeg`) — cached so a replay never re-pays the
      provider. If synthesis fails (bad key, rate limit, network) the call must
      not break: it **degrades** to the voice-marks path below so the browser
      speaks the line, exactly like POC.
    - **POC** (default `browser`): per-line voice marks (speaker + est.
      duration, `audio_url=null`) — the browser's SpeechSynthesis speaks it.
    - Text-session messages have no audio → 204.
    """
    session = await service.get_session(session_id, repo=repo)
    if session is None:
        raise _not_found("session", session_id)
    message = await service.get_message(session_id, seq, repo=repo)
    if message is None:
        raise _not_found("message", f"{session_id}#{seq}")
    if session.channel_type != "voice":
        return Response(status_code=204)

    speaker = message.meta.get("speaker", "persona")
    result = None
    try:
        # ``?provider=`` overrides the env-configured adapter per request, so an
        # operator can A/B ElevenLabs/Gemini/Google from the Control Panel with no
        # backend restart. ``model``/``voice_*`` are optional per-request config
        # overrides (Advanced voice) applied on a Settings copy — never mutating
        # the singleton. Absent = env default; a bad value still degrades to marks.
        overrides: dict[str, str] = {}
        _values = {"model": model, "voice_persona": voice_persona, "voice_scammer": voice_scammer}
        for param, field in _VOICE_OVERRIDE_FIELDS.get((provider or "").strip().lower(), {}).items():
            if _values[param]:
                overrides[field] = _values[param]
        # Defensive: if an operator accidentally passes an ElevenLabs model id
        # (e.g. "eleven_flash_v2_5") to Gemini via the Control Panel `model=`
        # query param, that's invalid for Gemini and will produce a 404/400.
        # Drop obviously-ElevenLabs values rather than forwarding them to the
        # Gemini adapter; the call proceeds on the configured Gemini model. Any
        # other value is passed through — the adapter normalizes/validates it
        # (accepts bare "gemini-2.5-flash-preview-tts" or a "models/…" form).
        if (provider or "").strip().lower() == "gemini" and overrides.get("gemini_tts_model"):
            val = overrides["gemini_tts_model"]
            if val.lower().startswith("eleven"):
                logger.warning(
                    "Ignoring ElevenLabs model override %r for provider=gemini", val
                )
                overrides.pop("gemini_tts_model", None)
        adapter = resolve_tts_adapter(provider, default=tts, overrides=overrides or None)
        result = await synthesize_line(adapter, message.content, voice=speaker)
    except Exception as exc:  # noqa: BLE001 — never let a TTS outage break the call
        # Log the type + repr (never blank, unlike str() on empty-message errors)
        # so the real reason is visible when a provider degrades to browser speech.
        logger.warning(
            "TTS synth failed for %s#%s (provider=%s) — degrading to browser speech: %s: %r",
            session_id, seq, provider or getattr(tts, "provider", "?"),
            type(exc).__name__, exc,
        )

    if result is not None and result.audio_bytes:
        return Response(
            content=result.audio_bytes,
            media_type=result.mime_type,
            headers={
                "X-TTS-Provider": result.provider,
                "Cache-Control": "private, max-age=3600",
            },
        )

    # POC marks (or degraded LIVE) → the browser speaks `text` on its own.
    duration = message.meta.get("duration_seconds")
    if duration is None:
        duration = result.duration_seconds if result else estimate_duration(message.content)
    return VoiceMarkOut(
        session_id=session_id,
        seq=seq,
        speaker=speaker,
        text=message.content,
        duration_seconds=duration,
        offset_seconds=message.meta.get("offset_seconds", 0.0),
        audio_url=None,
        provider=result.provider if result else getattr(tts, "provider", "poc-voice-marks"),
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
