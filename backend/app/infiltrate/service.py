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

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends
from pydantic import BaseModel, Field

from app.core.adapters import get_adapter
from app.infiltrate import classifier, extraction
from app.infiltrate.agent import AgentRun, run_session
from app.infiltrate.channels import ChannelAdapter
from app.infiltrate.custody import GENESIS, MessageChain
from app.infiltrate.gateway import LLMGateway
from app.infiltrate.personas import Persona, all_personas, get_persona

MODULE = "infiltrate"


# --------------------------------------------------------------------------- #
# Adapter dependencies (resolved under INFILTRATE's effective MODE)
# --------------------------------------------------------------------------- #


def get_channel_adapter() -> ChannelAdapter:
    return get_adapter("channel", MODULE)


def get_llm_gateway() -> LLMGateway:
    return get_adapter("llm", MODULE)


ChannelDep = Depends(get_channel_adapter)
GatewayDep = Depends(get_llm_gateway)


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
    case_id: str | None = None


# --------------------------------------------------------------------------- #
# In-memory POC stores
# --------------------------------------------------------------------------- #

_SESSIONS: dict[str, SessionOut] = {}
_MESSAGES: dict[str, list[MessageOut]] = {}       # session_id -> messages
_ENTITIES: dict[str, EntityOut] = {}              # entity_id -> entity
_SYNDICATES: dict[str, SyndicateOut] = {}


def reset_stores() -> None:  # test hook
    _SESSIONS.clear()
    _MESSAGES.clear()
    _ENTITIES.clear()
    _SYNDICATES.clear()


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


def _build_session(run: AgentRun, persona: Persona, req: StartSessionRequest) -> SessionOut:
    """Turn a completed AgentRun into custody-hashed messages + reconciled entities."""
    session_id = f"sess_{uuid.uuid4().hex[:12]}"
    # Deterministic timeline (no Date.now dependency in the hash content itself).
    base_ts = datetime(2026, 7, 7, 12, 0, 0, tzinfo=timezone.utc)
    chain = MessageChain(session_id)

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

        # Inbound (scammer) — custody + Layer-A extraction reconciled w/ Layer-B.
        cm_in = chain.append("inbound", tr.inbound.content, ts_in, tr.inbound.meta)
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
            _ENTITIES[me.id] = me

        messages.append(MessageOut(
            id=in_id, session_id=session_id, seq=cm_in.seq, direction="inbound",
            content=cm_in.content, ts=cm_in.ts, sha256=cm_in.sha256,
            prev_sha256=cm_in.prev_sha256, meta=cm_in.meta, entities=msg_ents,
        ))

        # Outbound (persona) — custody only; carries the covert tool_calls (Glass Box).
        cm_out = chain.append("outbound", tr.outbound.content, ts_out, tr.outbound.meta)
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
        channel_type="text",
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
        _SYNDICATES[syndicate.id] = syndicate

    _SESSIONS[session_id] = session
    _MESSAGES[session_id] = messages
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
    req: StartSessionRequest, channel: ChannelAdapter, gateway: LLMGateway
) -> SessionOut:
    persona = get_persona(req.persona_id)
    run = await run_session(persona, channel, gateway)
    return _build_session(run, persona, req)


async def seed_demo_session() -> SessionOut | None:
    """Seed one POC replay session at startup so GET /sessions is populated live.

    Idempotent + POC-only: if a session already exists (or INFILTRATE is LIVE),
    do nothing. Lets the Honeypot console show the demo narrative on first load
    without a manual POST — the ``● live api`` path instead of the mock fallback.
    """
    if _SESSIONS:
        return None
    try:
        channel = get_channel_adapter()
        gateway = get_llm_gateway()
    except Exception:
        return None  # LIVE adapters fail loud → skip seeding, never crash boot
    if getattr(gateway, "data_mode", "poc") != "poc":
        return None
    return await start_session(StartSessionRequest(), channel, gateway)


def list_sessions() -> list[SessionOut]:
    return list(_SESSIONS.values())


def get_session(session_id: str) -> SessionOut | None:
    return _SESSIONS.get(session_id)


def get_messages(session_id: str) -> list[MessageOut] | None:
    return _MESSAGES.get(session_id)


def list_entities(session_id: str | None = None, status: str | None = None) -> list[EntityOut]:
    items = list(_ENTITIES.values())
    if session_id is not None:
        items = [e for e in items if e.session_id == session_id]
    if status is not None:
        items = [e for e in items if e.review_status == status]
    return items


def get_entity(entity_id: str) -> EntityOut | None:
    return _ENTITIES.get(entity_id)


def review_entity(entity_id: str, status: str) -> EntityOut | None:
    ent = _ENTITIES.get(entity_id)
    if ent is None:
        return None
    ent.review_status = status
    if status == "confirmed":
        ent.method = "human"  # analyst confirmation is the highest provenance
    return ent


def list_syndicates() -> list[SyndicateOut]:
    return list(_SYNDICATES.values())


def list_personas() -> list[PersonaOut]:
    return [
        PersonaOut(id=p.id, name=p.name, age=p.age,
                   occupation=p.occupation.split(" (")[0], region=p.region)
        for p in all_personas()
    ]
