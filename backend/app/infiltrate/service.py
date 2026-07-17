"""INFILTRATE service — run a POC honeypot session end-to-end, expose read models.

Flow (docs/INFILTRATE-Design.md data flow): start a session → drive the agent
loop over the channel (persona + covert tools) → hash-chain every message into
custody → run Layer-A regex extraction per message + reconcile with the Layer-B
covert hints → classify the crime → cluster a syndicate → return the assembled
session. Everything is in-memory (POC pattern, mirrors P1–P3); the intel.*
tables are the persistence target for later phases.

Adapters (channel + llm) are resolved through the MODE registry via FastAPI
``Depends`` — POC gives the offline replay + scripted persona, LIVE fails loud.
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends
from pydantic import BaseModel, Field

from app.core.adapters import get_adapter
from app.core.config import get_settings
from app.infiltrate import classifier, extraction
from app.infiltrate.agent import COVERT_TOOLS, AgentRun, _dispatch_tools, run_session
from app.infiltrate.channels import ChannelAdapter
from app.infiltrate.custody import GENESIS, MessageChain
from app.infiltrate.gateway import (
    InteractiveScriptedGateway,
    LiteLLMGateway,
    LLMGateway,
    ScriptedLLMGateway,
)
from app.infiltrate.personas import Persona, all_personas, get_persona
from app.infiltrate.repository import (
    InfiltrateRepository,
    _memory_repository,
    get_infiltrate_repository,
)
from app.infiltrate.voice import (
    LIVE_TTS_PROVIDERS,
    VOICE_CALLER_NUMBER,
    VOICE_GREETING,
    VOICE_SCRIPT,
    TTSAdapter,
    estimate_duration,
)

MODULE = "infiltrate"

# Fixed, deterministic session epoch (no Date.now dependency in hash content).
_BASE_TS = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Adapter dependencies (resolved under INFILTRATE's effective MODE)
# --------------------------------------------------------------------------- #


def get_channel_adapter() -> ChannelAdapter:
    return get_adapter("channel", MODULE)


def get_llm_gateway() -> LLMGateway:
    return get_adapter("llm", MODULE)


def get_voice_channel_adapter() -> ChannelAdapter:
    """Voice transport (POC: call replay; LIVE: PSTN bridge, fails loud)."""
    return get_adapter("channel_voice", MODULE)


def get_tts_adapter() -> TTSAdapter:
    """TTS boundary — the real-voice upgrade (#15) is MODE-independent.

    ``ITTU_TTS_PROVIDER=browser`` (default) → POC voice marks (the browser
    speaks). Naming a live provider (elevenlabs | google | higgsfield) selects
    its adapter even while INFILTRATE stays POC — it fails loudly at
    construction without its key (never a silent downgrade). Under
    INFILTRATE MODE=live the registry's live factory resolves as before.
    """
    settings = get_settings()
    provider = settings.tts_provider.strip().lower()
    impl = LIVE_TTS_PROVIDERS.get(provider)
    if impl is not None:
        return impl(settings)
    return get_adapter("tts", MODULE)


ChannelDep = Depends(get_channel_adapter)
GatewayDep = Depends(get_llm_gateway)
TTSDep = Depends(get_tts_adapter)
RepoDep = Depends(get_infiltrate_repository)


# --------------------------------------------------------------------------- #
# API shapes (locked with P4-Frontend)
# --------------------------------------------------------------------------- #


class PersonaOut(BaseModel):
    id: str
    name: str
    age: int
    occupation: str
    region: str


class EntityOut(BaseModel):
    id: str
    session_id: str
    message_id: str | None
    type: str                         # bank_account|crypto_wallet|phone|url
    value: str
    normalized_value: str
    chain: str | None = None
    bank_name: str | None = None
    context: str = ""
    method: str                       # regex|llm|human
    confidence: float
    review_status: str = "unverified"
    provenance: dict = Field(default_factory=dict)
    data_mode: str = "poc"
    created_at: datetime


class MessageOut(BaseModel):
    id: str
    session_id: str
    seq: int
    direction: str                    # inbound (scammer) | outbound (persona)
    content: str
    ts: datetime
    sha256: str
    prev_sha256: str
    meta: dict = Field(default_factory=dict)
    entities: list[EntityOut] = Field(default_factory=list)


class ClassificationOut(BaseModel):
    crime_type: str
    confidence: float
    model_version: str
    signals: list[str] = Field(default_factory=list)


class CustodyOut(BaseModel):
    messages_logged: int
    chain_intact: bool
    genesis: str = GENESIS
    head_sha256: str


class SignalOut(BaseModel):
    signal: str
    detail: str = ""
    message_id: str | None = None


class EscalationOut(BaseModel):
    reason: str
    detail: str = ""
    message_id: str | None = None
    ts: datetime | None = None


class SyndicateMemberOut(BaseModel):
    entity_id: str
    type: str
    value: str
    link_type: str
    confidence: float


class SyndicateOut(BaseModel):
    id: str
    label: str
    notes: str = ""
    linguistic_fingerprint: dict = Field(default_factory=dict)
    session_ids: list[str] = Field(default_factory=list)
    entity_count: int = 0
    members: list[SyndicateMemberOut] = Field(default_factory=list)
    data_mode: str = "poc"
    created_at: datetime


class SessionOut(BaseModel):
    id: str
    case_id: str | None = None
    persona: PersonaOut
    channel_type: str = "text"
    channel: str
    channel_ref: str
    status: str                       # active|escalated|closed
    crime_type: str | None = None
    classification: ClassificationOut | None = None
    data_mode: str = "poc"
    started_at: datetime
    ended_at: datetime | None = None
    message_count: int
    entity_count: int
    escalations: list[EscalationOut] = Field(default_factory=list)
    scam_signals: list[SignalOut] = Field(default_factory=list)
    custody: CustodyOut
    syndicate_id: str | None = None


class StartSessionRequest(BaseModel):
    persona_id: str | None = None
    channel: str | None = "telegram"
    channel_type: Literal["text", "voice"] = "text"
    case_id: str | None = None
    # Tier-B live call: start an OPEN session (persona greets, then waits for
    # POST /sessions/{id}/turn) instead of running the scripted replay.
    interactive: bool = False


class TurnRequest(BaseModel):
    """One live inbound utterance (the scammer's transcribed speech).

    Field is ``text`` (not ``content``) to match the live-mic call client
    (``frontend/lib/honeypot/live.ts postLiveTurn``).
    """

    text: str = Field(min_length=1)


class TurnOut(BaseModel):
    """Result of one live agent turn (POST /sessions/{id}/turn)."""

    session_id: str
    turn: int                                     # 0-based turn index executed
    messages: list[MessageOut]                    # [inbound, outbound persona]
    entities: list[EntityOut] = Field(default_factory=list)   # new this turn
    classification: ClassificationOut | None = None
    status: str
    model: str                                    # which brain replied
    custody: CustodyOut | None = None


# --------------------------------------------------------------------------- #
# Persistence — sessions/messages/entities/syndicates live behind
# InfiltrateRepository (docs/Persistence-Plan.md P-2); resolved per-request via
# RepoDep (FastAPI Depends) or directly via get_infiltrate_repository() for
# non-request callers (lifespan seeding, the reset_stores() test hook).
# --------------------------------------------------------------------------- #


class _LiveState:
    """Mutable per-session conversation state for live ``/turn`` calls.

    Holds what the finished-replay read models can't reconstruct: the LLM
    conversation history, the open custody chain, the running call-timeline
    offset and the next turn index. Registered for every session (replay
    sessions can be continued live too).
    """

    __slots__ = (
        "persona", "conversation", "chain", "offset_seconds",
        "next_turn", "channel", "channel_ref", "is_voice", "interactive",
    )

    def __init__(
        self, persona: Persona, conversation: list[dict], chain: MessageChain,
        offset_seconds: float, next_turn: int, channel: str, channel_ref: str,
        is_voice: bool, interactive: bool,
    ) -> None:
        self.persona = persona
        self.conversation = conversation
        self.chain = chain
        self.offset_seconds = offset_seconds
        self.next_turn = next_turn
        self.channel = channel
        self.channel_ref = channel_ref
        self.is_voice = is_voice
        self.interactive = interactive


_LIVE_STATES: dict[str, _LiveState] = {}          # session_id -> live state (ephemeral, no table)


def reset_stores() -> None:  # test hook
    """Sync test hook — resets the in-memory singleton directly (NOT through
    ``get_infiltrate_repository``, which is a FastAPI dependency under P-2b and
    Postgres-aware). Tests only ever run against the memory store, so this
    intentionally bypasses persistence-mode selection rather than becoming
    async itself — keeps every existing sync test call site unchanged."""
    _memory_repository().reset()
    _LIVE_STATES.clear()


# --------------------------------------------------------------------------- #
# Session assembly
# --------------------------------------------------------------------------- #


def _entity_out(
    ent: extraction.ExtractedEntity, session_id: str, message_id: str,
    message_sha: str, created_at: datetime,
) -> EntityOut:
    return EntityOut(
        id=f"ent_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        message_id=message_id,
        type=ent.type,
        value=ent.value,
        normalized_value=ent.normalized_value,
        chain=ent.chain,
        bank_name=ent.bank_name,
        context=ent.context,
        method=ent.method,
        confidence=round(ent.confidence, 3),
        review_status="unverified",
        provenance={
            "turn": ent.turn,
            "methods": ent.methods,
            "validators_passed": ent.validators_passed,
            "message_sha256": message_sha,
        },
        created_at=created_at,
    )


async def _build_session(
    run: AgentRun, persona: Persona, req: StartSessionRequest,
    channel_type: str = "text", *, repo: InfiltrateRepository,
) -> SessionOut:
    """Turn a completed AgentRun into custody-hashed messages + reconciled entities."""
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    # Deterministic timeline (no Date.now dependency in the hash content itself).
    base_ts = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)
    chain = MessageChain(session_id)
    # Voice sessions carry per-line timing meta for the call timeline/captions.
    is_voice = channel_type == "voice"
    offset_seconds = 0.0

    # Layer-B hints keyed by turn (covert record_entity calls).
    hints_by_turn: dict[int, list[dict]] = {}
    for h in run.entity_hints:
        hints_by_turn.setdefault(h.get("turn", -1), []).append(h)

    messages: list[MessageOut] = []
    entities: list[EntityOut] = []
    escalations: list[EscalationOut] = []
    scam_signals: list[SignalOut] = []
    transcript_parts: list[str] = []

    for tr in run.turns:
        ts_in = base_ts + timedelta(seconds=tr.turn * 2)
        ts_out = base_ts + timedelta(seconds=tr.turn * 2 + 1)

        in_meta = dict(tr.inbound.meta)
        out_meta = dict(tr.outbound.meta)
        if is_voice:
            # Voice marks: who speaks the line, for how long, starting when.
            in_dur = estimate_duration(tr.inbound.content)
            in_meta.update({
                "speaker": "scammer",
                "duration_seconds": in_dur,
                "offset_seconds": round(offset_seconds, 1),
            })
            offset_seconds += in_dur
            out_dur = estimate_duration(tr.outbound.content)
            out_meta.update({
                "speaker": "persona",
                "duration_seconds": out_dur,
                "offset_seconds": round(offset_seconds, 1),
            })
            offset_seconds += out_dur

        # Inbound (scammer) — custody + Layer-A extraction reconciled w/ Layer-B.
        cm_in = chain.append("inbound", tr.inbound.content, ts_in, in_meta)
        in_id = f"msg_{uuid.uuid4().hex[:12]}"
        transcript_parts.append(tr.inbound.content)

        layer_a = extraction.extract_layer_a(tr.inbound.content)
        for e in layer_a:
            e.turn = tr.turn
        layer_b = [
            vb for h in hints_by_turn.get(tr.turn, [])
            if (vb := extraction.validate_layer_b_hint(h)) is not None
        ]
        reconciled = extraction.reconcile(layer_a, layer_b)
        msg_ents = [
            _entity_out(e, session_id, in_id, cm_in.sha256, ts_in) for e in reconciled
        ]
        entities.extend(msg_ents)
        for me in msg_ents:
            await repo.save_entity(me)

        messages.append(MessageOut(
            id=in_id, session_id=session_id, seq=cm_in.seq, direction="inbound",
            content=cm_in.content, ts=cm_in.ts, sha256=cm_in.sha256,
            prev_sha256=cm_in.prev_sha256, meta=cm_in.meta, entities=msg_ents,
        ))

        # Outbound (persona) — custody only; carries the covert tool_calls (Glass Box).
        cm_out = chain.append("outbound", tr.outbound.content, ts_out, out_meta)
        out_id = f"msg_{uuid.uuid4().hex[:12]}"
        messages.append(MessageOut(
            id=out_id, session_id=session_id, seq=cm_out.seq, direction="outbound",
            content=cm_out.content, ts=cm_out.ts, sha256=cm_out.sha256,
            prev_sha256=cm_out.prev_sha256, meta=cm_out.meta, entities=[],
        ))

        # Attribute signals/escalations to the inbound message of their turn.
        for sig in run.scam_signals:
            if sig.get("turn") == tr.turn:
                scam_signals.append(SignalOut(
                    signal=sig.get("signal", ""), detail=sig.get("detail", ""),
                    message_id=in_id,
                ))
        for esc in run.escalations:
            if esc.get("turn") == tr.turn:
                escalations.append(EscalationOut(
                    reason=esc.get("reason", ""), detail=esc.get("detail", ""),
                    message_id=in_id, ts=ts_in,
                ))

    # Classify the whole conversation.
    cls = classifier.classify(
        " ".join(transcript_parts),
        scam_signals=run.scam_signals,
        entity_types=[e.type for e in entities],
    )
    classification = ClassificationOut(
        crime_type=cls.crime_type, confidence=cls.confidence,
        model_version=cls.model_version, signals=cls.signals,
    )

    ended = base_ts + timedelta(seconds=len(run.turns) * 2)
    session = SessionOut(
        id=session_id,
        case_id=req.case_id,
        persona=PersonaOut(
            id=persona.id, name=persona.name, age=persona.age,
            occupation=persona.occupation.split(" (")[0], region=persona.region,
        ),
        channel_type=channel_type,
        channel=run.channel,
        channel_ref=run.channel_ref,
        status="escalated" if run.escalated else "closed",
        crime_type=cls.crime_type,
        classification=classification,
        data_mode=run.data_mode,
        started_at=base_ts,
        ended_at=ended,
        message_count=len(messages),
        entity_count=len(entities),
        escalations=escalations,
        scam_signals=scam_signals,
        custody=CustodyOut(
            messages_logged=len(chain.messages()),
            chain_intact=chain.verify(),
            head_sha256=chain.head,
        ),
    )

    # Cluster the extracted entities into a syndicate profile.
    syndicate = _cluster_syndicate(session, entities)
    if syndicate is not None:
        session.syndicate_id = syndicate.id
        await repo.save_syndicate(syndicate)

    await repo.save_session(session)
    await repo.save_messages(session_id, messages)
    return session


def _cluster_syndicate(session: SessionOut, entities: list[EntityOut]) -> SyndicateOut | None:
    """POC syndicate clustering — group this session's entities into one profile."""
    if not entities:
        return None
    link_types = {
        "crypto_wallet": "collection_wallet",
        "bank_account": "mule_account",
        "phone": "contact_number",
        "url": "platform_site",
    }
    members = [
        SyndicateMemberOut(
            entity_id=e.id, type=e.type, value=e.normalized_value,
            link_type=link_types.get(e.type, "linked"),
            confidence=e.confidence,
        )
        for e in entities
    ]
    label = f"{session.channel_ref} ring" if session.channel_ref else "Unlabeled ring"
    return SyndicateOut(
        id=f"syn_{uuid.uuid4().hex[:12]}",
        label=label,
        notes=f"Clustered from honeypot session {session.id} "
              f"({session.crime_type}).",
        linguistic_fingerprint={
            "urgency_markers": any(s.signal == "urgency_pressure" for s in session.scam_signals),
            "guaranteed_returns": any(
                s.signal == "guaranteed_returns" for s in session.scam_signals
            ),
            "channel": session.channel,
        },
        session_ids=[session.id],
        entity_count=len(members),
        members=members,
        data_mode=session.data_mode,
        created_at=session.started_at,
    )


# --------------------------------------------------------------------------- #
# Public service functions
# --------------------------------------------------------------------------- #


async def start_session(
    req: StartSessionRequest, channel: ChannelAdapter, gateway: LLMGateway,
    repo: InfiltrateRepository,
) -> SessionOut:
    persona = get_persona(req.persona_id)
    if req.interactive:
        # Tier-B live call (docs/Live-Voice-Calls.md): open a session with just
        # the persona's greeting and wait for POST /sessions/{id}/turn — no
        # scripted replay. Works for voice (mic) or text (typed) live demos.
        return await _start_interactive_session(req, persona, repo)
    if req.channel_type == "voice":
        # Voice transport swaps in; the agent loop / extraction / custody /
        # classifier / clustering downstream are reused verbatim. LIVE resolves
        # the PSTN stub and fails loud (never silently degrades to POC).
        channel = get_voice_channel_adapter()
        if getattr(channel, "data_mode", "poc") == "poc":
            gateway = ScriptedLLMGateway(script=VOICE_SCRIPT)
    run = await run_session(persona, channel, gateway)
    return await _build_session(run, persona, req, channel_type=req.channel_type, repo=repo)


async def _start_interactive_session(
    req: StartSessionRequest, persona: Persona, repo: InfiltrateRepository,
) -> SessionOut:
    """Open an interactive (Tier-B) session: persona greets, then waits.

    No agent-loop turns run yet — just custody message #1 (the greeting).
    Registers a ``_LiveState`` so ``run_one_turn`` can continue the
    conversation turn-by-turn from ``POST /sessions/{id}/turn``.
    """
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    is_voice = req.channel_type == "voice"
    channel = "voice" if is_voice else (req.channel or "telegram")
    channel_ref = VOICE_CALLER_NUMBER if is_voice else ""
    greeting = VOICE_GREETING if is_voice else "halo, ini dengan siapa ya?"

    chain = MessageChain(session_id)
    offset_seconds = 0.0
    meta: dict = {"turn": 0}
    if is_voice:
        dur = estimate_duration(greeting)
        meta.update({"speaker": "persona", "duration_seconds": dur, "offset_seconds": 0.0})
        offset_seconds = dur

    cm = chain.append("outbound", greeting, _BASE_TS, meta)
    msg_id = f"msg_{uuid.uuid4().hex[:12]}"
    message = MessageOut(
        id=msg_id, session_id=session_id, seq=cm.seq, direction="outbound",
        content=cm.content, ts=cm.ts, sha256=cm.sha256, prev_sha256=cm.prev_sha256,
        meta=cm.meta, entities=[],
    )

    session = SessionOut(
        id=session_id,
        case_id=req.case_id,
        persona=PersonaOut(
            id=persona.id, name=persona.name, age=persona.age,
            occupation=persona.occupation.split(" (")[0], region=persona.region,
        ),
        channel_type=req.channel_type,
        channel=channel,
        channel_ref=channel_ref,
        status="active",
        crime_type=None,
        classification=None,
        data_mode="poc",
        started_at=_BASE_TS,
        ended_at=None,
        message_count=1,
        entity_count=0,
        custody=CustodyOut(
            messages_logged=len(chain.messages()), chain_intact=chain.verify(), head_sha256=chain.head,
        ),
    )

    await repo.save_session(session)
    await repo.save_messages(session_id, [message])
    _LIVE_STATES[session_id] = _LiveState(
        persona=persona,
        conversation=[{"role": "system", "content": persona.system_prompt()}],
        chain=chain,
        offset_seconds=offset_seconds,
        next_turn=0,
        channel=channel,
        channel_ref=channel_ref,
        is_voice=is_voice,
        interactive=True,
    )
    return session


def _resolve_turn_gateway(settings) -> LLMGateway:
    """Brain for one live ``/turn`` call: real LLM if a key is configured,
    otherwise the deterministic keyless stall persona (never 500s)."""
    if settings.effective_llm_api_key:
        try:
            return LiteLLMGateway(settings)
        except NotImplementedError:
            pass  # fall through to the keyless persona
    return InteractiveScriptedGateway(settings)


async def run_one_turn(
    session_id: str, text: str, repo: InfiltrateRepository,
) -> TurnOut | None:
    """One live inbound utterance → persona reply, reusing the pipeline:
    agent turn (LLM + covert tools) → Layer-A/B extraction → custody append →
    reclassify. Returns ``None`` if ``session_id`` has no open live state
    (unknown session, or a finished scripted-replay session)."""
    state = _LIVE_STATES.get(session_id)
    session = await repo.get_session(session_id)
    if state is None or session is None:
        return None

    settings = get_settings()
    gateway = _resolve_turn_gateway(settings)
    turn = state.next_turn
    ts_in = _BASE_TS + timedelta(seconds=(turn + 1) * 2)
    ts_out = ts_in + timedelta(seconds=1)

    # --- inbound (scammer/operator utterance) — custody + extraction --------
    in_meta: dict = {"turn": turn}
    if state.is_voice:
        in_dur = estimate_duration(text)
        in_meta.update({
            "speaker": "scammer", "duration_seconds": in_dur,
            "offset_seconds": round(state.offset_seconds, 1),
        })
        state.offset_seconds += in_dur
    cm_in = state.chain.append("inbound", text, ts_in, in_meta)
    in_id = f"msg_{uuid.uuid4().hex[:12]}"

    state.conversation.append({"role": "user", "content": text})
    try:
        resp = await gateway.complete(state.conversation, tools=COVERT_TOOLS, turn=turn)
    except Exception as exc:
        # Live LLM/provider failed mid-call (e.g. a 9Router provider fallback
        # error, timeout, or malformed response) — degrade to the deterministic
        # keyless persona so an interactive /turn never 500s. Log the reason so a
        # silent fallback is diagnosable (why the persona went scripted).
        logging.getLogger("uvicorn.error").warning(
            "live LLM turn failed on %s (%s: %s) — using scripted fallback",
            getattr(gateway, "model_version", "?"), type(exc).__name__, exc,
            exc_info=True,
        )
        gateway = InteractiveScriptedGateway(settings)
        resp = await gateway.complete(state.conversation, tools=COVERT_TOOLS, turn=turn)

    # A model given tools may answer with ONLY a tool-call and no text — keep the
    # persona from going silent by borrowing an in-character stall line.
    if not (resp.content or "").strip():
        stall = await InteractiveScriptedGateway(settings).complete(
            state.conversation, turn=turn
        )
        resp.content = stall.content

    # Covert side-effects (record_entity/flag_scam_signal/escalate_to_analyst)
    # for this turn only — reuses the same dispatcher as the scripted loop.
    hint_run = AgentRun(
        persona_id=state.persona.id, channel=state.channel,
        channel_ref=state.channel_ref, data_mode=gateway.data_mode,
    )
    _dispatch_tools(hint_run, resp.tool_calls, turn)

    layer_a = extraction.extract_layer_a(text)
    for e in layer_a:
        e.turn = turn
    layer_b = [
        vb for h in hint_run.entity_hints
        if (vb := extraction.validate_layer_b_hint(h)) is not None
    ]
    reconciled = extraction.reconcile(layer_a, layer_b)
    new_entities = [_entity_out(e, session_id, in_id, cm_in.sha256, ts_in) for e in reconciled]
    for ne in new_entities:
        await repo.save_entity(ne)

    inbound_msg = MessageOut(
        id=in_id, session_id=session_id, seq=cm_in.seq, direction="inbound",
        content=cm_in.content, ts=cm_in.ts, sha256=cm_in.sha256,
        prev_sha256=cm_in.prev_sha256, meta=cm_in.meta, entities=new_entities,
    )

    # --- outbound (persona reply) — custody only -----------------------------
    out_meta: dict = {
        "turn": turn + 1, "model": resp.model,
        "tool_calls": [tc.model_dump() for tc in resp.tool_calls],
    }
    if state.is_voice:
        out_dur = estimate_duration(resp.content)
        out_meta.update({
            "speaker": "persona", "duration_seconds": out_dur,
            "offset_seconds": round(state.offset_seconds, 1),
        })
        state.offset_seconds += out_dur
    cm_out = state.chain.append("outbound", resp.content, ts_out, out_meta)
    out_id = f"msg_{uuid.uuid4().hex[:12]}"
    outbound_msg = MessageOut(
        id=out_id, session_id=session_id, seq=cm_out.seq, direction="outbound",
        content=cm_out.content, ts=cm_out.ts, sha256=cm_out.sha256,
        prev_sha256=cm_out.prev_sha256, meta=cm_out.meta, entities=[],
    )
    state.conversation.append({"role": "assistant", "content": resp.content})
    state.next_turn += 1

    # --- fold into the session read model + reclassify -----------------------
    await repo.append_messages(session_id, [inbound_msg, outbound_msg])
    all_msgs = await repo.get_messages(session_id) or []
    session.message_count = len(all_msgs)
    session.entity_count += len(new_entities)

    for esc in hint_run.escalations:
        session.escalations.append(EscalationOut(
            reason=esc.get("reason", ""), detail=esc.get("detail", ""),
            message_id=in_id, ts=ts_in,
        ))
    for sig in hint_run.scam_signals:
        session.scam_signals.append(SignalOut(
            signal=sig.get("signal", ""), detail=sig.get("detail", ""), message_id=in_id,
        ))
    if hint_run.escalations:
        session.status = "escalated"

    transcript = " ".join(m.content for m in all_msgs if m.direction == "inbound")
    session_entities = await list_entities(session_id=session_id, repo=repo)
    cls = classifier.classify(
        transcript,
        scam_signals=[s.model_dump() for s in session.scam_signals],
        entity_types=[e.type for e in session_entities],
    )
    classification = ClassificationOut(
        crime_type=cls.crime_type, confidence=cls.confidence,
        model_version=cls.model_version, signals=cls.signals,
    )
    session.classification = classification
    session.crime_type = cls.crime_type
    session.custody = CustodyOut(
        messages_logged=len(state.chain.messages()),
        chain_intact=state.chain.verify(),
        head_sha256=state.chain.head,
    )
    await repo.save_session(session)  # persist the in-place mutations above

    return TurnOut(
        session_id=session_id, turn=turn, messages=[inbound_msg, outbound_msg],
        entities=new_entities, classification=classification, status=session.status,
        model=resp.model, custody=session.custody,
    )


async def seed_demo_session() -> SessionOut | None:
    """Seed one POC replay session at startup so GET /sessions is populated live.

    Idempotent + POC-only: if a session already exists (or INFILTRATE is LIVE),
    do nothing. Lets the Honeypot console show the demo narrative on first load
    without a manual POST — the ``● live api`` path instead of the mock fallback.

    Called directly from ``main.py`` lifespan (not FastAPI ``Depends``), so it
    resolves its own repo the same way it already resolves the channel/gateway
    adapters below. Under ``persistence=="postgres"`` there's no request/JWT
    to derive an agency + RLS-scoped session from here, so that case is
    delegated to ``_seed_demo_session_postgres`` instead of going through
    ``get_infiltrate_repository()`` (a FastAPI dependency that would otherwise
    see its ``session``/``auth`` params as unresolved ``Depends(...)``
    sentinels when called bare, outside FastAPI's DI).
    """
    settings = get_settings()
    if settings.persistence == "postgres":
        return await _seed_demo_session_postgres(settings)
    repo = await get_infiltrate_repository()
    if await repo.list_sessions():
        return None
    try:
        channel = get_channel_adapter()
        gateway = get_llm_gateway()
    except Exception:
        return None  # LIVE adapters fail loud → skip seeding, never crash boot
    if getattr(gateway, "data_mode", "poc") != "poc":
        return None
    return await start_session(StartSessionRequest(), channel, gateway, repo)


async def _seed_demo_session_postgres(settings) -> SessionOut | None:
    """Postgres seeding path (P-2b): opens its OWN session (``SessionLocal``,
    not FastAPI DI — the lifespan has no request/JWT to resolve an
    ``AuthContext`` from) and seeds under the demo agency, Bareskrim Polri —
    its uuid5 id is already seeded by migration ``20260708_05`` and matches
    ``app.core.auth.SEED_AGENCIES``, so a demo JWT for that agency sees the
    seeded session immediately. Idempotent per agency, same as the memory path."""
    from sqlalchemy import text as sa_text

    from app.core.auth import SEED_AGENCIES
    from app.core.db import SessionLocal
    from app.infiltrate.repository import PostgresInfiltrateRepository

    bareskrim = next(a for a in SEED_AGENCIES if a.slug == "bareskrim")
    async with SessionLocal() as session, session.begin():
        await session.execute(
            sa_text("SELECT set_config('app.current_agency', :v, true)"),
            {"v": str(bareskrim.id)},
        )
        repo = PostgresInfiltrateRepository(
            session, agency_id=bareskrim.id, data_mode=settings.mode
        )
        if await repo.list_sessions():
            return None
        try:
            channel = get_channel_adapter()
            gateway = get_llm_gateway()
        except Exception:
            return None  # LIVE adapters fail loud → skip seeding, never crash boot
        if getattr(gateway, "data_mode", "poc") != "poc":
            return None
        return await start_session(StartSessionRequest(), channel, gateway, repo)


async def list_sessions(*, repo: InfiltrateRepository) -> list[SessionOut]:
    return await repo.list_sessions()


async def get_session(session_id: str, *, repo: InfiltrateRepository) -> SessionOut | None:
    return await repo.get_session(session_id)


async def get_messages(
    session_id: str, *, repo: InfiltrateRepository,
) -> list[MessageOut] | None:
    return await repo.get_messages(session_id)


async def get_message(
    session_id: str, seq: int, *, repo: InfiltrateRepository,
) -> MessageOut | None:
    """One message by its custody sequence number (for the audio endpoint)."""
    messages = await repo.get_messages(session_id)
    if messages is None:
        return None
    return next((m for m in messages if m.seq == seq), None)


async def list_entities(
    session_id: str | None = None, status: str | None = None,
    *, repo: InfiltrateRepository,
) -> list[EntityOut]:
    return await repo.list_entities(session_id=session_id, status=status)


async def get_entity(entity_id: str, *, repo: InfiltrateRepository) -> EntityOut | None:
    return await repo.get_entity(entity_id)


async def review_entity(
    entity_id: str, status: str, *, repo: InfiltrateRepository,
) -> EntityOut | None:
    ent = await repo.get_entity(entity_id)
    if ent is None:
        return None
    ent.review_status = status
    if status == "confirmed":
        ent.method = "human"  # analyst confirmation is the highest provenance
    await repo.save_entity(ent)
    return ent


async def list_syndicates(*, repo: InfiltrateRepository) -> list[SyndicateOut]:
    return await repo.list_syndicates()


def list_personas() -> list[PersonaOut]:
    return [
        PersonaOut(id=p.id, name=p.name, age=p.age,
                   occupation=p.occupation.split(" (")[0], region=p.region)
        for p in all_personas()
    ]
