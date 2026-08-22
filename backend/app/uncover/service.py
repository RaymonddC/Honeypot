"""UNCOVER Action Orchestrator — {case, entities, outputs} → draft bundle.

Flow (docs/UNCOVER-Design.md): gather case data (TAKEDOWN scores for wallets,
TRACE bridge data for bank accounts) → fan out to the document generators →
SHA-256 hash + store (in-memory object store, POC) + audit-log → return a
draft bundle. **Dispatch is separate and human-gated** — generation never
auto-fires an outward action.

Stores are persisted behind ``UncoverRepository`` (docs/Persistence-Plan.md
P-3) — an in-memory impl backs the POC + existing tests unchanged; a Postgres
impl backs ``settings.persistence == "postgres"`` against ``action.*``.
"""

import uuid
from datetime import datetime, timezone
from typing import Literal

from fastapi import Depends
from pydantic import BaseModel, Field

from app.core.adapters import ChainDataAdapter, FiatDataAdapter, get_adapter
from app.fiat.generator import IDR_PER_USDT
from app.fiat.schemas import FiatGenParams
from app.takedown.service import investigate
from app.trace.service import build_bridge
from app.uncover import documents as docs
from app.uncover.custody import sha256_hex
from app.core.config import get_settings
from app.uncover.notifications import (
    NotificationOut,
    NotificationSink,
    RoutingTarget,
    dispatch_notifications,
    new_idempotency_key,
    route_targets,
)
from app.uncover.repository import (
    UncoverRepository,
    _memory_repository,
    get_uncover_repository,
)

MODULE = "uncover"

OutputKind = Literal["freeze", "ltkm", "alert", "pack"]
DEFAULT_OUTPUTS: list[OutputKind] = ["freeze", "ltkm", "alert", "pack"]


def get_notification_sink() -> NotificationSink:
    """FastAPI dependency: notification sink under UNCOVER's effective MODE."""
    return get_adapter("notification", MODULE)


def get_chain_adapter() -> ChainDataAdapter:
    return get_adapter("blockchain", MODULE)


def get_fiat_adapter() -> FiatDataAdapter:
    return get_adapter("fiat", MODULE)


SinkDep = Depends(get_notification_sink)
ChainAdapterDep = Depends(get_chain_adapter)
FiatAdapterDep = Depends(get_fiat_adapter)
RepoDep = Depends(get_uncover_repository)


# --------------------------------------------------------------------------- #
# API shapes
# --------------------------------------------------------------------------- #


class ActionEntityIn(BaseModel):
    """One selected entity from the investigation (wallet or bank account)."""

    type: Literal["crypto_wallet", "bank_account"]
    value: str                                # address or account number
    chain: str | None = "tron"                # crypto_wallet only
    bank_name: str | None = None              # bank_account only
    holder_name: str | None = None


class GenerateRequest(BaseModel):
    case_id: str = Field(min_length=1)
    crime_type: str = "investment"
    entities: list[ActionEntityIn] = Field(min_length=1)
    outputs: list[OutputKind] = Field(default_factory=lambda: list(DEFAULT_OUTPUTS))


class DocumentOut(BaseModel):
    """Metadata for one generated document (PDF bytes via download_url)."""

    id: str
    type: str                                  # account_blocking|str_report|summary
    format: str                                # iasc|ppatk_str|generic
    title: str
    filename: str
    sha256: str
    size_bytes: int
    status: str                                # draft|issued|acknowledged
    template_version: str
    generated_at: datetime
    data_mode: str
    download_url: str


class BundleTotals(BaseModel):
    at_risk_usdt: float
    at_risk_idr: float
    idr_per_usdt: float = IDR_PER_USDT


class BundleAuditEntry(BaseModel):
    """One core-trail entry about this bundle, shaped for the bundle view.

    Projected from ``app.core.audit.AuditEntry``. It replaces the per-process
    in-memory custody chain that used to fill this field and did not survive a
    restart (docs/Backlog.md).

    ``seq`` is the entry's position in the **agency's** chain, NOT this bundle's.
    A bundle will show something like 47 then 103, and those are correct: the
    numbers between them are that agency's other actions, not missing entries.
    Do not render this as if the bundle had its own gapless chain — that is the
    same over-claim the /audit banner was corrected for.
    """

    seq: int
    action: str
    actor: str = ""          # snapshotted name, not a uuid
    target_type: str | None = None
    target_id: str | None = None
    detail: dict = Field(default_factory=dict)
    ts: datetime
    sha256: str
    prev_sha256: str


class ActionBundle(BaseModel):
    """The action_bundle the API returns (draft → dispatched)."""

    id: str
    case_id: str
    status: Literal["draft", "dispatched"]
    data_mode: str
    crime_type: str
    outputs: list[OutputKind]
    entities: list[ActionEntityIn]
    documents: list[DocumentOut]
    goaml_draft: dict | None = None            # goAML-shaped STR draft (JSON)
    routing_plan: list[RoutingTarget]
    notifications: list[NotificationOut] = Field(default_factory=list)
    totals: BundleTotals
    created_at: datetime
    dispatched_at: datetime | None = None
    # Fingerprint of the EVIDENCE (the document set), not of an audit position.
    # Derived from the document hashes, so it is identical every time the same
    # bundle is read — see ``evidence_hash``. The Action Panel used to display
    # the audit chain's head here, which changed on every restart.
    evidence_hash: str = ""
    # Filled by the ROUTER from ``core.audit_log`` (agency-scoped, durable), not
    # by the service: reading it needs a session, and see BundleAuditEntry for
    # what ``seq`` means now.
    audit: list[BundleAuditEntry] = Field(default_factory=list)


class AlreadyDispatchedError(Exception):
    pass


def reset_stores() -> None:  # test hook
    """Sync test hook — resets the in-memory singleton directly (NOT through
    ``get_uncover_repository``, which is a FastAPI dependency under P-3 and
    Postgres-aware). Tests only ever run against the memory store, same
    pattern as ``infiltrate.service.reset_stores``."""
    _memory_repository().reset()


async def get_bundle(action_id: str, *, repo: UncoverRepository) -> ActionBundle | None:
    bundle = await repo.get_bundle(action_id)
    if bundle is None:
        return None
    # ``audit`` is filled by the router from the durable core trail — it needs
    # an agency-scoped session, which the service layer has no business holding.
    bundle.evidence_hash = evidence_hash(bundle.documents)
    return bundle


async def get_document(document_id: str, *, repo: UncoverRepository) -> docs.GeneratedDocument | None:
    return await repo.get_document(document_id)


async def all_bundles(*, repo: UncoverRepository) -> list[ActionBundle]:
    return await repo.list_bundles()


def evidence_hash(documents) -> str:
    """A stable fingerprint of a bundle's document set.

    SHA-256 over the documents' own sha256s, sorted so the value does not depend
    on generation order. Deterministic and derived only from the evidence, so it
    is the same on every read and after any restart — which is the whole point:
    the Action Panel previously displayed the in-memory custody chain's head,
    so the SAME bundle showed one "evidence hash" before a restart and another
    after. For a product whose pitch is chain of custody, a hash that silently
    changes is worse than none.

    It changes if and only if the documents change, which is the behaviour a
    reader already assumes a hash has.
    """
    if not documents:
        return ""
    return sha256_hex("".join(sorted(d.sha256 for d in documents)).encode())


# --------------------------------------------------------------------------- #
# Context assembly — pull case data from TAKEDOWN + TRACE (POC in-memory)
# --------------------------------------------------------------------------- #


async def _wallet_target(
    entity: ActionEntityIn, chain_adapter: ChainDataAdapter
) -> tuple[docs.WalletTarget, list[docs.TimelineEvent]]:
    inv = await investigate(entity.value, chain_adapter)
    if inv is None or entity.value not in inv.scores:
        return docs.WalletTarget(address=entity.value, chain=entity.chain or "tron"), []

    score = inv.scores[entity.value]
    own = [t for t in inv.transfers if entity.value in (t.from_addr, t.to_addr)]
    inflow = sum(t.value for t in own if t.to_addr == entity.value)
    timeline = [
        docs.TimelineEvent(
            ts=t.ts,
            description=(
                f"USDT transfer {t.from_addr[:8]}… → {t.to_addr[:8]}…"
                + (" (inbound)" if t.to_addr == entity.value else " (outbound)")
            ),
            amount=t.value,
            currency="USDT",
            ref=t.tx_hash,
        )
        for t in sorted(own, key=lambda t: t.ts)
    ]
    target = docs.WalletTarget(
        address=entity.value,
        chain=entity.chain or "tron",
        risk=score.composite_risk,
        confidence=score.confidence,
        reasoning=score.reasoning,
        patterns=[p.name for p in score.patterns if p.fired],
        inflow_usdt=round(inflow, 2),
        tx_hashes=[t.tx_hash for t in own[:20]],
    )
    return target, timeline


async def _account_target(
    entity: ActionEntityIn,
    fiat_adapter: FiatDataAdapter,
    chain_adapter: ChainDataAdapter,
) -> tuple[docs.AccountTarget, list[docs.TimelineEvent]]:
    bridge = await build_bridge(fiat_adapter, chain_adapter, FiatGenParams())
    ds = bridge.dataset
    account = next(
        (a for a in ds.accounts if a.account_number == entity.value
         and (entity.bank_name is None or a.bank_name == entity.bank_name)),
        None,
    )
    if account is None:
        return docs.AccountTarget(
            account_number=entity.value,
            bank_name=entity.bank_name or "unknown",
            holder_name=entity.holder_name,
        ), []

    incoming = [t for t in ds.transactions if t.to_account_id == account.id]
    outgoing = [t for t in ds.transactions if t.from_account_id == account.id]
    names = ds.accounts_by_id()
    timeline = [
        docs.TimelineEvent(
            ts=t.ts,
            description=(
                f"{t.channel.upper()} {'in from ' + names[t.from_account_id].holder_name if t in incoming else 'out to ' + names[t.to_account_id].holder_name}"
                f" ({t.kind or 'transfer'})"
            ),
            amount=t.amount,
            currency="IDR",
            ref=str(t.id),
        )
        for t in sorted(incoming + outgoing, key=lambda t: t.ts)[:30]
    ]
    target = docs.AccountTarget(
        account_number=account.account_number,
        bank_name=account.bank_name,
        holder_name=entity.holder_name or account.holder_name,
        role=account.role,
        cluster=account.cluster,
        inflow_idr=round(sum(t.amount for t in incoming), 2),
        outflow_idr=round(sum(t.amount for t in outgoing), 2),
        tx_count=len(incoming) + len(outgoing),
    )
    return target, timeline


async def assemble_context(
    req: GenerateRequest,
    chain_adapter: ChainDataAdapter,
    fiat_adapter: FiatDataAdapter,
    generated_at: datetime | None = None,
    *,
    agency: str | None = None,
    agency_type: str = "",
    officer_name: str = "",
    officer_role: str = "",
) -> docs.DocumentContext:
    wallets: list[docs.WalletTarget] = []
    accounts: list[docs.AccountTarget] = []
    timeline: list[docs.TimelineEvent] = []

    for entity in req.entities:
        if entity.type == "crypto_wallet":
            target, events = await _wallet_target(entity, chain_adapter)
            wallets.append(target)
        else:
            target, events = await _account_target(entity, fiat_adapter, chain_adapter)
            accounts.append(target)
        timeline.extend(events)
    timeline.sort(key=lambda e: e.ts)

    at_risk_usdt = sum(w.inflow_usdt for w in wallets)
    at_risk_idr = at_risk_usdt * IDR_PER_USDT + sum(a.outflow_idr for a in accounts)

    fired = sorted({p for w in wallets for p in w.patterns})
    narrative = (
        f"Investigation of case {req.case_id} identified "
        f"{len(wallets)} crypto wallet(s) and {len(accounts)} bank account(s) involved in a "
        f"suspected {docs.CRIME_TYPE_LABELS.get(req.crime_type, req.crime_type)} scheme. "
        + (f"On-chain typology detectors fired: {', '.join(fired)}. " if fired else "")
        + ("Fiat-side analysis links the flagged account(s) to mule aggregation and "
           "crypto on-ramp conversion. " if accounts else "")
        + f"Estimated funds at risk: {at_risk_usdt:,.2f} USDT "
          f"(≈ Rp {at_risk_idr:,.0f}). All findings carry Glass Box reasoning and are "
          f"custody-hashed for evidentiary integrity."
    )

    return docs.DocumentContext(
        case_id=req.case_id,
        crime_type=req.crime_type,
        data_mode="poc" if getattr(chain_adapter, "data_mode", "poc") == "poc" else "live",
        generated_at=generated_at or datetime.now(timezone.utc),
        # requesting_agency keeps its model default unless a real agency is passed.
        **({"requesting_agency": agency} if agency else {}),
        agency_type=agency_type,
        officer_name=officer_name,
        officer_role=officer_role,
        wallets=wallets,
        accounts=accounts,
        timeline=timeline,
        narrative=narrative,
        total_at_risk_usdt=round(at_risk_usdt, 2),
        total_at_risk_idr=round(at_risk_idr, 2),
        idr_per_usdt=IDR_PER_USDT,
    )


# --------------------------------------------------------------------------- #
# Orchestration: generate (draft) / dispatch (human-gated)
# --------------------------------------------------------------------------- #


def _doc_out(d: docs.GeneratedDocument) -> DocumentOut:
    return DocumentOut(
        id=d.id, type=d.type, format=d.format, title=d.title, filename=d.filename,
        sha256=d.sha256, size_bytes=d.size_bytes, status=d.status,
        template_version=d.template_version, generated_at=d.generated_at,
        data_mode=d.data_mode, download_url=f"/api/documents/{d.id}",
    )


async def generate_bundle(
    req: GenerateRequest,
    chain_adapter: ChainDataAdapter,
    fiat_adapter: FiatDataAdapter,
    *,
    repo: UncoverRepository,
    agency: str | None = None,
    agency_type: str = "",
    officer_name: str = "",
    officer_role: str = "",
) -> ActionBundle:
    """One click → many artifacts. Generates + hashes + stores, returns a draft."""
    outputs = list(dict.fromkeys(req.outputs)) or list(DEFAULT_OUTPUTS)
    ctx = await assemble_context(
        req, chain_adapter, fiat_adapter,
        agency=agency, agency_type=agency_type,
        officer_name=officer_name, officer_role=officer_role,
    )

    generated: list[docs.GeneratedDocument] = []
    goaml_draft: dict | None = None
    if "freeze" in outputs:
        generated.append(docs.generate_freeze_request(ctx))
    if "ltkm" in outputs:
        str_doc = docs.generate_str_draft(ctx)
        goaml_draft = str_doc.meta.get("goaml_draft")
        generated.append(str_doc)
    if "pack" in outputs:
        generated.append(docs.generate_evidence_pack(ctx, manifest_docs=generated))

    routing_plan = route_targets(req.crime_type, ctx.accounts, ctx.wallets, outputs)

    bundle = ActionBundle(
        id=f"act_{uuid.uuid4().hex[:12]}",
        case_id=req.case_id,
        status="draft",
        data_mode=ctx.data_mode,
        crime_type=req.crime_type,
        outputs=outputs,
        entities=req.entities,
        documents=[_doc_out(d) for d in generated],
        goaml_draft=goaml_draft,
        routing_plan=routing_plan,
        totals=BundleTotals(
            at_risk_usdt=ctx.total_at_risk_usdt,
            at_risk_idr=ctx.total_at_risk_idr,
            idr_per_usdt=ctx.idr_per_usdt,
        ),
        created_at=ctx.generated_at,
    )

    # Bundle first (its uuid is the FK target for each document row), then
    # the documents (each references the bundle's public_id — repository
    # resolves the FK). No-op ordering distinction for the in-memory impl.
    await repo.save_bundle(bundle)
    for d in generated:
        await repo.save_document(bundle.id, d)

    # The durable record of this generation is written by the ROUTER into
    # core.audit_log (action.bundle.generated, with every document sha256).
    # There used to be a second, in-memory custody entry here; it recorded less,
    # duplicated what the core trail already had, and vanished on restart.
    bundle.evidence_hash = evidence_hash(bundle.documents)
    return bundle


def _queued_notification(
    bundle: ActionBundle, target: RoutingTarget, packet: dict
) -> NotificationOut:
    """A notification persisted as ``queued`` for the durable worker to pick up
    (LIVE worker mode). Carries the idempotency key + the full packet (minus the
    agency fields, which are their own columns) the actor redelivers from."""
    return NotificationOut(
        id=f"ntf_{uuid.uuid4().hex[:12]}",
        action_id=bundle.id,
        case_id=bundle.case_id,
        target_agency=target.agency,
        agency_type=target.agency_type,
        channel=target.channel,
        status="queued",
        data_mode=bundle.data_mode,
        idempotency_key=new_idempotency_key(),
        attempt_count=0,
        payload={k: v for k, v in packet.items() if k not in ("agency", "agency_type")},
    )


async def list_notifications(
    *,
    repo: UncoverRepository,
    status: str | None = None,
    agency_type: str | None = None,
    case_id: str | None = None,
) -> list[NotificationOut]:
    """The Dispatch Log feed: every notification the caller may see (RLS-scoped
    under Postgres), newest first, with optional filters."""
    notes = await repo.list_notifications()
    if status:
        notes = [n for n in notes if n.status == status]
    if agency_type:
        notes = [n for n in notes if n.agency_type == agency_type]
    if case_id:
        notes = [n for n in notes if n.case_id == case_id]
    return notes


class NotificationNotFoundError(Exception):
    pass


async def retry_notification(
    notification_id: str, sink: NotificationSink, *, repo: UncoverRepository
) -> NotificationOut:
    """Re-dispatch a single notification. ``sent`` is a no-op (idempotent).

    LIVE worker mode re-queues the row and re-enqueues the durable actor; the
    sync path (POC mock / LIVE-sync) re-POSTs inline, reusing the SAME
    idempotency key so the recipient can dedupe a redelivery."""
    note = await repo.get_notification(notification_id)
    if note is None:
        raise NotificationNotFoundError(notification_id)
    if note.status == "sent":
        return note

    settings = get_settings()
    if note.data_mode == "live" and settings.notification_delivery == "worker":
        note.status = "queued"
        note.last_error = None
        await repo.update_notification(note)
        dispatch_notifications.send(note.id)
        return note

    packet = {
        **note.payload,
        "agency": note.target_agency,
        "agency_type": note.agency_type,
        "idempotency_key": note.idempotency_key,
    }
    fresh = await sink.dispatch(packet)
    note.status = fresh.status
    note.last_error = fresh.last_error
    note.sent_at = fresh.sent_at
    note.attempt_count = (note.attempt_count or 0) + (fresh.attempt_count or 0)
    await repo.update_notification(note)
    return note


async def dispatch_bundle(
    action_id: str, sink: NotificationSink, *, repo: UncoverRepository
) -> ActionBundle | None:
    """Human-gated dispatch: route the draft bundle to each planned agency.

    POC → mock sink (status='mock', nothing leaves). LIVE → real channels via
    the Dramatiq actor. Documents move draft → issued; the bundle records
    ``dispatched_at`` (feeds the Response Dashboard time-to-freeze).
    """
    bundle = await repo.get_bundle(action_id)
    if bundle is None:
        return None
    if bundle.status == "dispatched":
        raise AlreadyDispatchedError(action_id)

    settings = get_settings()
    # Durable worker delivery: LIVE + explicit opt-in. Persist each notification
    # as `queued` and hand real delivery to the Dramatiq actor (retries/backoff,
    # off-request). Requires Postgres — the actor reads the queued row in another
    # process — so fail loud rather than silently drop into the sync path.
    use_worker = bundle.data_mode == "live" and settings.notification_delivery == "worker"
    if use_worker and settings.persistence != "postgres":
        raise RuntimeError(
            "ITTU_NOTIFICATION_DELIVERY=worker requires ITTU_PERSISTENCE=postgres "
            "(the delivery actor reads the queued notification row cross-process)."
        )

    notifications: list[NotificationOut] = []
    for target in bundle.routing_plan:
        doc_ids = [d.id for d in bundle.documents if d.type == target.document_type]
        packet = {
            "action_id": bundle.id,
            "case_id": bundle.case_id,
            "agency": target.agency,
            "agency_type": target.agency_type,
            "channel": target.channel,
            "document_type": target.document_type,
            "document_ids": doc_ids,
            "document_hashes": [
                d.sha256 for d in bundle.documents if d.id in doc_ids
            ],
            "reason": target.reason,
        }
        if use_worker:
            notifications.append(_queued_notification(bundle, target, packet))
        else:
            notifications.append(await sink.dispatch(packet))

    now = datetime.now(timezone.utc)
    for d in bundle.documents:
        d.status = "issued"
        await repo.update_document_status(d.id, "issued")
    bundle.notifications = notifications
    bundle.status = "dispatched"
    bundle.dispatched_at = now
    await repo.save_bundle(bundle)  # persists the envelope + the notifications above

    if use_worker:
        # Enqueue AFTER persistence. The actor is idempotent and treats a
        # not-yet-visible row as transient (retries), so enqueue-before-commit
        # of the request transaction is tolerated; a production refinement is a
        # transactional outbox. POC/sync paths never reach here.
        for n in notifications:
            dispatch_notifications.send(n.id)

    # Durable record written by the router (dispatch.sent), which now also
    # carries the per-notification {id, agency, status} this in-memory entry
    # used to be the only place holding.
    bundle.evidence_hash = evidence_hash(bundle.documents)
    return bundle
