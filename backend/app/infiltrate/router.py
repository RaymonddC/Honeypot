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
from collections import OrderedDict
from contextlib import asynccontextmanager
from typing import Literal
from urllib.parse import parse_qsl

import httpx
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core.adapters import get_adapter
from app.core.audit import ENTITY_REVIEWED, record_action
from app.core.auth import AuthContext, get_current_user, require_capability
from app.core.capabilities import HONEYPOT_ENGAGE, HONEYPOT_READ
from app.core.db import get_optional_tenant_session
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
import secrets

from app.infiltrate.telephony import (
    build_gather_twiml,
    build_play_and_hangup_twiml,
    build_say_and_hangup_twiml,
    build_stream_twiml,
    verify_twilio_signature,
)
from app.infiltrate.voice import (
    VOICE_GREETING,
    TTSAdapter,
    VoiceMarkOut,
    check_elevenlabs_voice,
    check_gemini,
    check_google,
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
        "voice_persona": "gemini_voice_persona",
        "voice_scammer": "gemini_voice_scammer",
    },
    "google": {
        "voice_persona": "google_tts_voice_persona",
        "voice_scammer": "google_tts_voice_scammer",
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
    _auth: AuthContext = Depends(require_capability(HONEYPOT_ENGAGE)),  # live contact with a suspect
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
    _auth: AuthContext = Depends(require_capability(HONEYPOT_ENGAGE)),  # live contact with a suspect
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


@router.get("/tts/gemini-check")
async def get_tts_gemini_check(
    voice: str = Query("persona", description="persona|scammer — picks the sample line"),
    voice_name: str = Query("", description="prebuilt voice to test; blank = configured default"),
    _auth: AuthContext = Depends(require_capability(HONEYPOT_ENGAGE)),  # live contact with a suspect
) -> Response:
    """Readiness check for Gemini TTS: run a short **test synthesis** (the exact
    ``generateContent`` path a call uses) in the given voice and, on success,
    return the WAV so the Control Panel PLAYS a sample. ``voice_name`` tests a
    just-typed prebuilt voice (blank = the role's configured default). On
    failure, return a JSON body ``{provider:'gemini', ok:false, status?, error?}``
    — where error is ``no_key`` / ``config:…`` (bad model) / ``http_429`` (quota →
    enable billing) / ``http_400`` (invalid voice name / bad model) / ``http_404``
    (region) / ``http_403`` (key rejected). Turns a silent degrade-to-browser
    into a one-click diagnosis. NB: each check spends one Gemini request (the free
    tier is only 10/day). The key stays server-side."""
    text = _VOICE_SAMPLE.get(voice, "Halo, selamat siang, apa kabar?")
    res = await check_gemini(voice=voice, text=text, voice_name=voice_name)
    if res.get("ok") and res.get("audio"):
        return Response(
            content=res["audio"],
            media_type="audio/wav",
            headers={"X-Voice-Check": "ok", "Cache-Control": "no-store"},
        )
    return JSONResponse(
        {
            "provider": "gemini",
            "ok": False,
            "status": res.get("status"),
            "error": res.get("error"),
        }
    )


@router.get("/tts/google-check")
async def get_tts_google_check(
    voice: str = Query("persona", description="persona|scammer — picks the sample line"),
    voice_name: str = Query("", description="id-ID voice to test; blank = configured default"),
    _auth: AuthContext = Depends(require_capability(HONEYPOT_ENGAGE)),  # live contact with a suspect
) -> Response:
    """Readiness check for Google Cloud TTS: run a short **test synthesis** in the
    given voice and, on success, return the MP3 so the Control Panel PLAYS a
    sample. ``voice_name`` tests a just-picked id-ID voice (blank = the role's
    configured default). On failure, return JSON
    ``{provider:'google', ok:false, status?, error?}`` — error is ``no_key`` /
    ``http_400`` (bad voice/params) / ``http_403`` (key rejected or Text-to-Speech
    API not enabled) / ``http_429`` (quota). The key stays server-side."""
    text = _VOICE_SAMPLE.get(voice, "Halo, selamat siang, apa kabar?")
    res = await check_google(voice=voice, text=text, voice_name=voice_name)
    if res.get("ok") and res.get("audio"):
        return Response(
            content=res["audio"],
            media_type="audio/mpeg",
            headers={"X-Voice-Check": "ok", "Cache-Control": "no-store"},
        )
    return JSONResponse(
        {
            "provider": "google",
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
    _auth: AuthContext = Depends(require_capability(HONEYPOT_READ)),  # reviewing the record
) -> list[SessionOut]:
    """All engaged honeypot sessions (RLS-scoped in LIVE)."""
    return await service.list_sessions(repo=repo)


@router.post("/sessions", response_model=SessionOut, status_code=201)
async def post_session(
    body: StartSessionRequest | None = None,
    channel: ChannelAdapter = ChannelDep,
    gateway: LLMGateway = GatewayDep,
    repo: InfiltrateRepository = RepoDep,
    _auth: AuthContext = Depends(require_capability(HONEYPOT_ENGAGE)),  # live contact with a suspect
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
    _auth: AuthContext = Depends(require_capability(HONEYPOT_ENGAGE)),  # live contact with a suspect
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
    _auth: AuthContext = Depends(require_capability(HONEYPOT_READ)),  # reviewing the record
) -> SessionOut:
    session = await service.get_session(session_id, repo=repo)
    if session is None:
        raise _not_found("session", session_id)
    return session


@router.get("/sessions/{session_id}/messages", response_model=list[MessageOut])
async def get_session_messages(
    session_id: str,
    repo: InfiltrateRepository = RepoDep,
    _auth: AuthContext = Depends(require_capability(HONEYPOT_READ)),  # reviewing the record
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
    _auth: AuthContext = Depends(require_capability(HONEYPOT_READ)),  # reviewing the record
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
    _auth: AuthContext = Depends(get_current_user),  # SHARED intelligence:
    # the honeypot's OUTPUT, not the operation. An institution that may not
    # run a deception session still needs the wallets and accounts it
    # surfaced — that is the whole point of sharing a case picture.
) -> list[EntityOut]:
    """Extracted, confidence-scored entities (Layer-A validated + Layer-B reconciled)."""
    return await service.list_entities(session_id=session, status=status, repo=repo)


@router.post("/entities/{entity_id}/review", response_model=EntityOut)
async def post_entity_review(
    entity_id: str,
    body: ReviewRequest,
    repo: InfiltrateRepository = RepoDep,
    auth: AuthContext = Depends(get_current_user),  # human-in-the-loop = named human
    session=Depends(get_optional_tenant_session),
    request: Request = None,  # audit origin (ip/user-agent)
) -> EntityOut:
    """Analyst review — confirm/reject/flag-poisoned (human-in-the-loop)."""
    entity = await service.review_entity(entity_id, body.status, repo=repo)
    if entity is None:
        raise _not_found("entity", entity_id)
    # The most consequential human judgement in the pipeline: a "confirmed"
    # entity becomes the basis for a freeze request. Who decided, and when, is
    # exactly what a court asks about.
    await record_action(
        session,
        agency_id=str(auth.agency.id),
        action=ENTITY_REVIEWED,
        actor_user_id=str(auth.user.id),
        actor_name=auth.user.name,
        request=request,
        target_type="entity",
        target_id=entity_id,
        target_label=f"{entity.type} {entity.value}",
        detail={"status": body.status, "value": entity.value, "type": entity.type},
    )
    return entity


@router.get("/syndicates", response_model=list[SyndicateOut])
async def get_syndicates(
    repo: InfiltrateRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),  # SHARED intelligence:
    # the honeypot's OUTPUT, not the operation. An institution that may not
    # run a deception session still needs the wallets and accounts it
    # surfaced — that is the whole point of sharing a case picture.
) -> list[SyndicateOut]:
    """Syndicate profiles clustered from extracted entities."""
    return await service.list_syndicates(repo=repo)


# Lines the honeypot can speak on a call, addressed by KEY rather than by text.
#
# This is the security boundary for the audio route below. That route has to be
# unauthenticated — Twilio fetches <Play> URLs over the open internet with no
# credentials — so if it synthesized whatever text a caller put in the URL, it
# would be a free public text-to-speech proxy billed to our provider account.
# A fixed vocabulary makes the cost bounded and the output predictable.
VOICE_LINES: dict[str, str] = {
    # THE line the session's first custody message records
    # (service._start_interactive_session writes VOICE_GREETING as message #1).
    #
    # It is imported rather than written out again because the two drifted, and
    # the drift was the bug: the phone played "Halo, selamat siang. Ini dengan
    # siapa ya?" while the transcript recorded "halo, selamat siang.. dengan ibu
    # Sari di sini. ini siapa ya nak?". A hash-chained record of a call that
    # says something the caller never heard is worse than no record — it is
    # evidence of the wrong conversation.
    "greeting": VOICE_GREETING,
    # Said when the caller has gone quiet twice, or the turn cap is reached.
    "goodbye": "Maaf ya, saya tanya anak saya dulu. Nanti telepon lagi ya.",
    # Said when the persona cannot answer (LLM error). Stalling is in character,
    # so a failure sounds like hesitation rather than a broken line.
    "stall": "Aduh, maaf ya, suaranya putus-putus. Bisa diulang?",
}

# Synthesized bytes, kept per (line, provider). These lines never change, so the
# first call pays for synthesis and every later one is free and instant — which
# also matters on the call itself: Twilio is holding a live caller while it
# fetches this URL.
_audio_cache: dict[tuple[str, str], bytes] = {}

# --- The live conversation (<Gather> loop) -----------------------------------
#
# Everything below is DEMO-GRADE and in-process on purpose. It creates no
# INFILTRATE session and writes nothing to Postgres, which is what lets the
# persona run LIVE while the deployment stays ITTU_MODE=poc: the mode-coherence
# guard (config.assert_modes_are_coherent) exists to stop rows being stamped
# with a mode that is not theirs, and a call that persists no rows has no stamp
# to get wrong. The cost is that the transcript and any disclosed accounts do
# NOT reach the case file — wiring that needs the number->agency resolution the
# media-stream handler documents and deliberately refuses.

#: Spoken replies are short. See LiteLLMGateway.complete's max_tokens note.
VOICE_MAX_TOKENS = 90
#: Hard stop on one call. Bounds both the LLM spend and how long a caller can
#: hold a worker; a honeypot wants a long call, but not an unbounded one.
MAX_TURNS = 14
#: Two silences ends it. One is a caller thinking; two is a dead line.
MAX_SILENCES = 2
#: Bounds on the in-process stores. Eviction is oldest-first (insertion order).
MAX_CONVERSATIONS = 200
MAX_DYNAMIC_AUDIO = 256

#: CallSid -> {"messages": [...], "turns": int, "silences": int}
_conversations: "OrderedDict[str, dict]" = OrderedDict()

#: token -> synthesized MP3 for ONE reply. Keys are minted by us
#: (secrets.token_urlsafe), never taken from a URL, so the public audio route
#: still only ever serves audio this process generated.
_dynamic_audio: "OrderedDict[str, bytes]" = OrderedDict()

#: Strong references to in-flight warm-up tasks. asyncio only holds weak ones,
#: so a fire-and-forget task can be garbage-collected before it finishes.
_warming: set = set()


def _remember(store: OrderedDict, key: str, value) -> None:
    """Insert with oldest-first eviction. These are unbounded inputs from the
    outside world (one entry per inbound call), so they need a ceiling: a
    honeypot is exactly the service someone might call ten thousand times."""
    store[key] = value
    store.move_to_end(key)
    cap = MAX_CONVERSATIONS if store is _conversations else MAX_DYNAMIC_AUDIO
    while len(store) > cap:
        store.popitem(last=False)


def _live_tts_provider(settings) -> str | None:
    """The configured LIVE TTS provider, or None if we should fall back to <Say>.

    Deliberately conservative: it checks the provider is one we know AND that
    its key is present, because emitting <Play> for audio we cannot produce
    gives the caller silence — strictly worse than Twilio's generic voice.
    """
    from app.infiltrate.voice import LIVE_TTS_PROVIDERS

    provider = (settings.tts_provider or "").strip().lower()
    if provider not in LIVE_TTS_PROVIDERS:
        return None
    key_for = {
        "elevenlabs": settings.elevenlabs_api_key,
        "google": settings.google_tts_api_key,
        "gemini": settings.gemini_api_key,
    }
    # A provider we know but whose key we cannot see: treat as unavailable.
    return provider if key_for.get(provider, "") else None


async def _synthesize(text: str, settings) -> bytes:
    """Speak one line with the configured provider. Raises HTTPException on failure."""
    provider = _live_tts_provider(settings)
    if provider is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "tts_unavailable",
                "message": (
                    "No LIVE TTS provider is configured (ITTU_TTS_PROVIDER plus "
                    "its API key), so there is no audio to play."
                ),
            },
        )
    from app.infiltrate.voice import LIVE_TTS_PROVIDERS

    try:
        adapter = LIVE_TTS_PROVIDERS[provider](settings)
        spoken = await adapter.synthesize(text)
    except Exception as exc:  # noqa: BLE001 - provider errors are operational
        # Never surface the provider's response body: it can echo the API key
        # back in an error. Log the type, return a clean 502.
        logger.error("telephony: TTS provider %s failed: %s", provider, type(exc).__name__)
        raise HTTPException(
            status_code=502,
            detail={"code": "tts_failed", "message": "Voice synthesis failed."},
        ) from exc
    audio = spoken.audio_bytes or b""
    if not audio:
        raise HTTPException(
            status_code=502,
            detail={"code": "tts_empty", "message": "Voice synthesis returned no audio."},
        )
    return audio


@router.get("/telephony/audio/{line_key}.mp3")
async def get_telephony_audio(line_key: str) -> Response:
    """Synthesized audio for one line — what Twilio's <Play> fetches.

    **Unauthenticated by necessity**: Twilio pulls this URL with no credentials,
    exactly as it posts the answer webhook without our JWT. Unlike the webhook
    there is no signature to check — Twilio does not sign media fetches.

    So the protection is that this route NEVER synthesizes text taken from the
    URL. It serves exactly two things: a line from the fixed VOICE_LINES
    vocabulary, or a reply this process already generated and filed under a
    random token. Anything else is a 404 before a provider is touched.
    Without that, a public endpoint that speaks arbitrary text is a free
    text-to-speech proxy billed to our provider account.
    """
    dynamic = _dynamic_audio.get(line_key)
    if dynamic is not None:
        # A persona reply: unique per call, so it must not be cached by Twilio's
        # edge or by anything between us — and it is genuinely single-use.
        return Response(
            content=dynamic,
            media_type="audio/mpeg",
            headers={"Cache-Control": "no-store"},
        )

    text = VOICE_LINES.get(line_key)
    if text is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "unknown_line", "message": f"No voice line {line_key!r}."},
        )

    settings = get_settings()
    provider = _live_tts_provider(settings)
    cached = _audio_cache.get((line_key, provider)) if provider else None
    if cached is None:
        cached = await _synthesize(text, settings)
        _audio_cache[(line_key, provider)] = cached

    # A fixed line never changes, so let Twilio's edge hold it.
    return Response(
        content=cached,
        media_type="audio/mpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@asynccontextmanager
async def _telephony_repo():
    """A repository for a call that carries no JWT, scoped to the declared agency.

    An inbound Twilio request has no identity, so ``get_infiltrate_repository``
    cannot serve it — under Postgres its tenant session 401s by design. This
    yields one anyway, scoped to ``ITTU_TELEPHONY_AGENCY``.

    That connects through ``worker_session`` (the owning role), so **RLS is not
    filtering these queries** and this code carries both obligations the policies
    would otherwise discharge, exactly as ``honeypot_ops.dialer`` does:
    ``agency_id`` is passed explicitly, and ``data_mode`` is the deployment's own
    mode so a call cannot be written into the other evidentiary universe.

    The agency is DECLARED in config, not looked up from the dialled number. A
    lookup would have to read ``honeypot.numbers`` to find the agency it needs in
    order to read ``honeypot.numbers``; a declared slug cannot resolve to a
    tenant nobody intended.

    Yields ``None`` when no agency is configured, or in memory persistence where
    there is no tenant to scope to — callers fall back to the unrecorded path.
    """
    settings = get_settings()
    slug = (settings.telephony_agency or "").strip()
    if not slug:
        yield None
        return
    if settings.persistence != "postgres":
        # Memory mode has no agencies and no RLS; the process-wide singleton is
        # the whole store, and start_session/run_one_turn work against it.
        from app.infiltrate.repository import _memory_repository

        yield _memory_repository()
        return

    from sqlalchemy import select

    from app.core.auth import SEED_AGENCIES
    from app.core.db import worker_session
    from app.core.models import Agency
    from app.infiltrate.repository import PostgresInfiltrateRepository

    # Slug -> id the same way the rest of auth does it: `core.agencies` has no
    # slug column, the id is a deterministic uuid5 of the slug (auth._agency_id),
    # and the seeded rows carry exactly those ids. Resolving through the seed
    # table rather than recomputing the hash means an unknown slug is caught
    # here instead of producing a well-formed id for an agency that never
    # existed — which would fail later as a foreign-key error, mid-call.
    seed = next((a for a in SEED_AGENCIES if a.slug == slug), None)
    if seed is None:
        logger.error(
            "telephony: ITTU_TELEPHONY_AGENCY=%r is not a known agency slug (%s) "
            "— the call will be answered but nothing recorded",
            slug, ", ".join(a.slug for a in SEED_AGENCIES),
        )
        yield None
        return

    async with worker_session() as session:
        exists = (
            await session.execute(select(Agency.id).where(Agency.id == seed.id))
        ).scalar_one_or_none()
        if exists is None:
            logger.error(
                "telephony: agency %r (%s) is not in this database — answering "
                "unrecorded rather than writing rows nothing owns",
                slug, seed.id,
            )
            yield None
            return
        yield PostgresInfiltrateRepository(
            session, agency_id=seed.id, data_mode=settings.mode
        )


async def _open_case_session(call_sid: str, from_number: str) -> str | None:
    """Open a recorded INFILTRATE session for this call, or None if unrecorded.

    Best-effort on purpose. Recording is worth a lot, but not worth dropping a
    live call for: if the database is unreachable the persona still answers, and
    the conversation falls back to the in-process path.
    """
    from app.infiltrate.service import StartSessionRequest, start_session

    try:
        async with _telephony_repo() as repo:
            if repo is None:
                return None
            out = await start_session(
                StartSessionRequest(channel_type="voice", interactive=True),
                channel=None, gateway=None, repo=repo,
            )
            logger.info(
                "telephony: call %s recording into session %s (from %s)",
                call_sid, out.id, from_number or "<unknown>",
            )
            return out.id
    except Exception as exc:  # noqa: BLE001 - never drop a call over storage
        logger.error(
            "telephony: could not open a session for call %s (%s) — answering "
            "unrecorded", call_sid, type(exc).__name__,
        )
        return None


async def _recorded_turn(session_id: str, heard: str) -> str | None:
    """One turn through the real pipeline: LLM + extraction + custody + reclassify.

    Returns the persona's line, or None if the turn could not be recorded — the
    caller then falls back so the conversation continues either way.
    """
    from app.infiltrate.service import run_one_turn

    try:
        async with _telephony_repo() as repo:
            if repo is None:
                return None
            out = await run_one_turn(session_id, heard, repo)
            if out is None:
                return None
            # TurnOut carries the pair [inbound, outbound persona] rather than a
            # `reply` field; the persona's line is the outbound one.
            for msg in reversed(out.messages or []):
                if msg.direction == "outbound":
                    return (msg.content or "").strip() or None
            return None
    except Exception as exc:  # noqa: BLE001 - never drop a call over storage
        logger.error("telephony: recorded turn failed (%s)", type(exc).__name__)
        return None


async def _warm_llm() -> None:
    """Import litellm off the critical path, while the greeting is still playing.

    ``_litellm_complete`` imports litellm lazily, inside the call. That is right
    for a POC deployment that never uses it, but it puts a heavy one-off import
    on the FIRST spoken turn — measured at 35s on the deployed instance, against
    Twilio's 15s action-URL timeout. The caller's first sentence would time out
    and drop the call; every later turn was 1.5s.

    Answering the call is the natural window: the greeting plays, the caller
    speaks, Twilio transcribes — several seconds during which nothing else needs
    the worker. Done in a THREAD because a synchronous 30-second import on the
    event loop would freeze every other request in this process.

    Warmed here rather than at startup: boot is already slow on this instance,
    and a deployment that never takes a call should not pay for litellm at all.
    """
    import asyncio
    import importlib

    try:
        await asyncio.to_thread(importlib.import_module, "litellm")
    except Exception as exc:  # noqa: BLE001 - warming is best-effort by design
        # Never fail the call over this: the turn will just pay the import.
        logger.warning("telephony: LLM warm-up failed (%s)", type(exc).__name__)


def _conversation_enabled(settings) -> bool:
    """Can the persona actually hold a conversation?

    Needs a voice (TTS) and a brain (an LLM key). Twilio supplies the ears via
    <Gather input="speech">, so there is no STT requirement. Without a brain the
    call falls back to the single-line answer rather than gathering speech we
    have nothing to answer with — silence after a question is worse than a short
    honest call.
    """
    return bool(_live_tts_provider(settings)) and bool(settings.effective_llm_api_key)


def _new_call_state(session_id: str | None = None) -> dict:
    """Blank per-call state. ``messages`` is filled in on the first turn, not
    here: the answer webhook knows the session id but has no reason to build a
    prompt for a caller who may never speak."""
    return {"messages": None, "turns": 0, "silences": 0, "session_id": session_id}


async def _persona_reply(call_sid: str, heard: str, settings) -> str:
    """One persona turn. Returns the line to speak."""
    from app.infiltrate.gateway import LiteLLMGateway
    from app.infiltrate.personas import VOICE_ADDENDUM, get_persona

    state = _conversations.get(call_sid)
    if state is None:
        state = _new_call_state()
        _remember(_conversations, call_sid, state)
    if state["messages"] is None:
        # Bu Sari — the investment-scam persona — plus the spoken-channel rules
        # that make her ask for the account out loud instead of by message.
        # Shared with the recorded path (service._start_interactive_session), so
        # both routes run the same persona rather than drifting apart.
        persona = get_persona(None)
        state["messages"] = [
            {"role": "system", "content": persona.system_prompt() + VOICE_ADDENDUM}
        ]

    state["messages"].append({"role": "user", "content": heard})
    state["turns"] += 1

    # Recorded path first: run_one_turn drives the SAME agent loop and then does
    # Layer-A/B extraction, custody append and reclassification — so an account
    # spoken on this call becomes an entity on a real session instead of being
    # discarded when the caller hangs up. Falls through to the unrecorded reply
    # below if storage is unavailable: recording is worth a lot, but not worth
    # dropping a live call for.
    if state.get("session_id"):
        recorded = await _recorded_turn(state["session_id"], heard)
        if recorded:
            state["messages"].append({"role": "assistant", "content": recorded})
            return recorded

    try:
        gateway = LiteLLMGateway(settings)
        out = await gateway.complete(
            messages=state["messages"], max_tokens=VOICE_MAX_TOKENS
        )
        reply = (out.content or "").strip()
    except Exception as exc:  # noqa: BLE001 - provider errors are operational
        logger.error("telephony: persona LLM failed: %s", type(exc).__name__)
        reply = ""

    if not reply:
        # Stalling is IN CHARACTER for this persona, so a model failure sounds
        # like a bad line rather than a broken system. It is also not recorded
        # as a persona turn — otherwise a flapping provider would silently eat
        # the turn budget.
        state["turns"] -= 1
        return VOICE_LINES["stall"]

    state["messages"].append({"role": "assistant", "content": reply})
    return reply


@router.post("/telephony/gather")
async def post_telephony_gather(request: Request) -> Response:
    """One conversational turn: what the caller said in, the persona's reply out.

    Twilio does the speech-to-text (``<Gather input="speech">``) and POSTs the
    transcript here as ``SpeechResult``. Same signature check as the answer
    webhook — this endpoint drives an LLM and a TTS provider, so an unsigned
    caller who found the URL could run up a bill and fabricate a conversation.
    """
    settings = get_settings()
    body = (await request.body()).decode("utf-8", errors="replace")
    params = dict(parse_qsl(body, keep_blank_values=True))

    base = settings.public_base_url.rstrip("/")
    url = f"{base}{request.url.path}" if base else str(request.url)
    if not verify_twilio_signature(
        settings.twilio_auth_token,
        url,
        params,
        request.headers.get("X-Twilio-Signature", ""),
    ):
        logger.warning("telephony: rejected an unsigned gather callback for %s", url)
        raise HTTPException(
            status_code=403,
            detail={
                "code": "invalid_twilio_signature",
                "message": "Request is not a validly signed Twilio webhook.",
            },
        )

    call_sid = params.get("CallSid", "")
    heard = (params.get("SpeechResult") or "").strip()
    state = _conversations.get(call_sid)

    def _end(line_key: str) -> Response:
        _conversations.pop(call_sid, None)
        return Response(
            content=build_play_and_hangup_twiml(
                f"{base}/api/telephony/audio/{line_key}.mp3"
            ),
            media_type="application/xml",
        )

    # Silence. Twilio reaches the <Redirect> after the gather with no
    # SpeechResult — one is a caller thinking, two is a dead line.
    if not heard:
        silences = (state or {}).get("silences", 0) + 1
        if state is not None:
            state["silences"] = silences
        if silences >= MAX_SILENCES or state is None:
            logger.info("telephony: call %s ended on silence", call_sid)
            return _end("goodbye")
        return Response(
            content=build_gather_twiml(
                f"{base}/api/telephony/audio/stall.mp3",
                f"{base}/api/telephony/gather",
            ),
            media_type="application/xml",
        )

    if state is not None and state["turns"] >= MAX_TURNS:
        logger.info("telephony: call %s hit the turn cap", call_sid)
        return _end("goodbye")

    logger.info("telephony: call %s heard %r", call_sid, heard[:120])
    reply = await _persona_reply(call_sid, heard, settings)

    # Synthesize THIS reply and file it under a token we mint. The audio route
    # serves it by that token and never re-synthesizes from the URL.
    token = f"r_{secrets.token_urlsafe(12)}"
    try:
        _remember(_dynamic_audio, token, await _synthesize(reply, settings))
    except HTTPException:
        return _end("goodbye")

    return Response(
        content=build_gather_twiml(
            f"{base}/api/telephony/audio/{token}.mp3",
            f"{base}/api/telephony/gather",
        ),
        media_type="application/xml",
    )


@router.post("/telephony/voice")
async def post_telephony_voice(request: Request) -> Response:
    """Twilio's answer webhook — the URL a honeypot number points at.

    **Deliberately unauthenticated**: Twilio cannot present our JWT. The
    ``X-Twilio-Signature`` HMAC *is* the authentication, so the check below is
    the only thing standing between this endpoint and anyone who learns the URL
    posting fake call events. It is therefore mandatory, not best-effort: an
    unconfigured auth token fails CLOSED (`verify_twilio_signature` returns
    False on an empty token) rather than waving requests through.

    Returns a short spoken line and hangs up. The eventual
    ``<Connect><Stream>`` needs the phase-5 media bridge, and pointing Twilio at
    a socket nobody serves would connect a real caller to silence — so this
    stays honest until the bridge exists. Everything up to that point (number →
    webhook → signature → TwiML) is exercised for real by ringing the number.
    """
    settings = get_settings()
    # Parse the urlencoded body directly rather than via request.form(), which
    # drags in python-multipart for a shape Twilio never sends: voice webhooks
    # are application/x-www-form-urlencoded (or JSON, which carries no signed
    # body params at all — its digest rides in the URL as bodySHA256).
    body = (await request.body()).decode("utf-8", errors="replace")
    params = dict(parse_qsl(body, keep_blank_values=True))

    # Twilio signs the exact PUBLIC url it called. Behind Render/Vercel, TLS is
    # terminated upstream and request.url is an internal http:// host, so a URL
    # rebuilt from the request would never match — hence ITTU_PUBLIC_BASE_URL.
    base = settings.public_base_url.rstrip("/")
    url = f"{base}{request.url.path}" if base else str(request.url)

    if not verify_twilio_signature(
        settings.twilio_auth_token,
        url,
        params,
        request.headers.get("X-Twilio-Signature", ""),
    ):
        logger.warning(
            "telephony: rejected an unsigned/invalid Twilio webhook for %s "
            "(token configured: %s)",
            url,
            bool(settings.twilio_auth_token),
        )
        raise HTTPException(
            status_code=403,
            detail={
                "code": "invalid_twilio_signature",
                "message": "Request is not a validly signed Twilio webhook.",
            },
        )

    logger.info("telephony: answered call %s", params.get("CallSid", "<no sid>"))

    # Hand the call to the media bridge when one can actually be reached.
    # Pointing Twilio at a socket nobody serves connects a real caller to
    # silence, so both preconditions are checked: a public base URL (Twilio
    # dials it from the internet) and a stream token (the socket refuses
    # without one). Missing either, fall back to speaking a line and hanging
    # up — a short, polite call beats an open line playing nothing.
    if settings.public_base_url and settings.telephony_stream_token:
        wss = (
            settings.public_base_url.rstrip("/").replace("https://", "wss://", 1)
            .replace("http://", "ws://", 1)
            + f"/api/telephony/stream?token={settings.telephony_stream_token}"
        )
        try:
            return Response(
                content=build_stream_twiml(wss, greeting=None),
                media_type="application/xml",
            )
        except ValueError as exc:
            # build_stream_twiml refuses ws:// and non-websocket URLs. A
            # misconfigured base URL must not silently degrade to a dead socket.
            logger.error("telephony: cannot build a stream URL (%s) — saying goodbye", exc)

    # Speak in OUR voice when a LIVE TTS provider is configured: an id-ID
    # WaveNet/ElevenLabs line is the difference between a persona and an IVR,
    # and a caller decides which they are hearing in about two seconds.
    # Falls back to <Say> — Twilio's own voice — when no provider is available,
    # because a generic voice is still a working call and <Play> pointing at
    # audio we cannot synthesize is silence.
    if base and _live_tts_provider(settings):
        greeting = f"{base}/api/telephony/audio/greeting.mp3"
        try:
            # A brain as well as a voice: answer and LISTEN. Otherwise the
            # persona greets the caller and hangs up, which is a doorbell.
            if _conversation_enabled(settings):
                call_sid = params.get("CallSid", "")
                _conversations.pop(call_sid, None)  # fresh call
                # Open the recorded session now, while the greeting plays, so the
                # caller's first sentence already has somewhere to be filed.
                session_id = await _open_case_session(call_sid, params.get("From", ""))
                if session_id:
                    _remember(_conversations, call_sid, {
                        "messages": None,       # built lazily by _persona_reply
                        "turns": 0, "silences": 0, "session_id": session_id,
                    })
                # Fire-and-forget: pay litellm's import now, while the greeting
                # plays, instead of on the caller's first sentence.
                import asyncio

                task = asyncio.create_task(_warm_llm())
                _warming.add(task)  # hold a reference or it can be GC'd mid-flight
                task.add_done_callback(_warming.discard)
                return Response(
                    content=build_gather_twiml(greeting, f"{base}/api/telephony/gather"),
                    media_type="application/xml",
                )
            return Response(
                content=build_play_and_hangup_twiml(greeting),
                media_type="application/xml",
            )
        except ValueError as exc:
            # build_play_and_hangup_twiml refuses a non-https URL — Twilio would
            # not fetch it anyway, so fall through rather than answer with silence.
            logger.error("telephony: cannot build a <Play> URL (%s) — using <Say>", exc)

    return Response(
        content=build_say_and_hangup_twiml(VOICE_LINES["greeting"]),
        media_type="application/xml",
    )


@router.websocket("/telephony/stream")
async def telephony_stream(websocket: WebSocket) -> None:
    """Twilio Media Streams socket — the live call itself.

    **Authenticated by a token in the URL, not by our JWT.** Twilio cannot
    present a bearer token on a WebSocket, and unlike its webhooks it does not
    sign stream frames — the answer TwiML is the only thing we control, so the
    secret rides in the URL we put there. Compared with ``compare_digest`` so a
    wrong token cannot be found one character at a time.

    Refuses when no token is configured: an open socket is an LLM bill and, worse,
    a way to fabricate a "call" in an evidentiary record.
    """
    settings = get_settings()
    expected = settings.telephony_stream_token
    supplied = websocket.query_params.get("token", "")
    if not expected or not secrets.compare_digest(supplied, expected):
        # Close BEFORE accepting: never run a persona for an unauthenticated peer.
        await websocket.close(code=1008)
        logger.warning(
            "telephony: rejected a media stream (token configured: %s)", bool(expected)
        )
        return

    await websocket.accept()

    from app.infiltrate import service
    from app.infiltrate.bridge import MediaBridge, pcm_from_tts

    # Boundary adapters, resolved for the infiltrate module's effective MODE —
    # the same path every other adapter takes, so a LIVE deployment gets the
    # LIVE ones without a second selection mechanism here.
    stt = get_adapter("stt", "infiltrate", settings)
    tts = get_adapter("tts", "infiltrate", settings)

    async def transcribe(pcm16: bytes) -> str:
        return await stt.transcribe(pcm16)

    async def reply(session_id: str | None, text: str) -> str:
        if not session_id:
            return ""
        result = await service.run_one_turn(session_id, text, None)
        return getattr(result, "reply", "") or ""

    async def synthesize(text: str) -> tuple[bytes, int]:
        spoken = await tts.synthesize(text)
        if not spoken.audio_bytes:
            return b"", 8000
        return pcm_from_tts(spoken.audio_bytes, spoken.mime_type)

    # ⚠️ INBOUND SESSION CREATION IS NOT WIRED, and this refuses rather than
    # running a persona that cannot answer.
    #
    # An inbound call needs an agency to file the session under, and the only
    # honest source is the honeypot NUMBER that was dialled — `honeypot.numbers`
    # carries `agency_id`. But that table is RLS-scoped by agency, so reading it
    # requires knowing the agency we are trying to look up: the same chicken-
    # and-egg `worker_session` solves with an owner-role read, and adding a
    # second RLS-bypass path is a decision to take deliberately rather than in
    # passing (docs/Security-Evidence.md §2).
    #
    # Until then: accept, log, close. A socket that stays open with a mute
    # persona is worse than a refused one — the caller hears silence on an
    # answered call, which is the exact failure the answer webhook already
    # avoids by not pointing at a socket nobody serves.
    async def _no_session(_call_sid: str) -> str | None:
        logger.error(
            "telephony: inbound session creation is not wired — refusing the "
            "stream rather than answering with a mute persona. Needs "
            "number->agency resolution (see the comment in this handler)."
        )
        return None

    bridge = MediaBridge(
        transcribe=transcribe, reply=reply, synthesize=synthesize,
        on_start=_no_session,
    )
    try:
        state = await bridge.handle(websocket)
        logger.info(
            "telephony: stream for call %s ended after %d turn(s)",
            state.call_sid, state.turns,
        )
    except WebSocketDisconnect:
        logger.info("telephony: caller hung up")


@router.get("/infiltrate/ping")
async def ping() -> dict[str, str]:
    return {"module": "infiltrate"}
