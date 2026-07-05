"""UNCOVER Action Orchestrator — {case, entities, outputs} → draft bundle.

Flow (docs/UNCOVER-Design.md): gather case data (TAKEDOWN scores for wallets,
TRACE bridge data for bank accounts) → fan out to the document generators →
SHA-256 hash + store (in-memory object store, POC) + audit-log → return a
draft bundle. **Dispatch is separate and human-gated** — generation never
auto-fires an outward action.

Endpoints compute in-memory from fixtures/generators (POC pattern, mirrors
P1/P2); ``action.*`` tables are the persistence target for later phases.
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
from app.uncover.custody import AuditEntry, audit_log
from app.uncover.notifications import (
    NotificationOut,
    NotificationSink,
    RoutingTarget,
    route_targets,
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
    audit: list[AuditEntry] = Field(default_factory=list)


class AlreadyDispatchedError(Exception):
    pass


# In-memory stores (POC object store — action.* tables are the LIVE target).
_ACTIONS: dict[str, ActionBundle] = {}
_DOCUMENTS: dict[str, docs.GeneratedDocument] = {}


def reset_stores() -> None:  # test hook
    _ACTIONS.clear()
    _DOCUMENTS.clear()


def get_bundle(action_id: str) -> ActionBundle | None:
    bundle = _ACTIONS.get(action_id)
    if bundle is None:
        return None
    # Refresh the audit view (dispatch appends entries after generation).
    bundle.audit = _bundle_audit(bundle)
    return bundle


def get_document(document_id: str) -> docs.GeneratedDocument | None:
    return _DOCUMENTS.get(document_id)


def all_bundles() -> list[ActionBundle]:
    return list(_ACTIONS.values())


def _bundle_audit(bundle: ActionBundle) -> list[AuditEntry]:
    ids = {bundle.id} | {d.id for d in bundle.documents}
    return [e for e in audit_log.entries() if e.target_id in ids]


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
) -> ActionBundle:
    """One click → many artifacts. Generates + hashes + stores, returns a draft."""
    outputs = list(dict.fromkeys(req.outputs)) or list(DEFAULT_OUTPUTS)
    ctx = await assemble_context(req, chain_adapter, fiat_adapter)

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

    for d in generated:
        _DOCUMENTS[d.id] = d
    _ACTIONS[bundle.id] = bundle

    audit_log.record(
        action="action.bundle.generated",
        target_type="action_bundle",
        target_id=bundle.id,
        detail={
            "case_id": bundle.case_id,
            "outputs": outputs,
            "documents": {d.id: d.sha256 for d in generated},
            "routing_targets": len(routing_plan),
            "data_mode": bundle.data_mode,
        },
    )
    bundle.audit = _bundle_audit(bundle)
    return bundle


async def dispatch_bundle(action_id: str, sink: NotificationSink) -> ActionBundle | None:
    """Human-gated dispatch: route the draft bundle to each planned agency.

    POC → mock sink (status='mock', nothing leaves). LIVE → real channels via
    the Dramatiq actor. Documents move draft → issued; the bundle records
    ``dispatched_at`` (feeds the Response Dashboard time-to-freeze).
    """
    bundle = _ACTIONS.get(action_id)
    if bundle is None:
        return None
    if bundle.status == "dispatched":
        raise AlreadyDispatchedError(action_id)

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
        notifications.append(await sink.dispatch(packet))

    now = datetime.now(timezone.utc)
    for d in bundle.documents:
        d.status = "issued"
        if d.id in _DOCUMENTS:
            _DOCUMENTS[d.id].status = "issued"
    bundle.notifications = notifications
    bundle.status = "dispatched"
    bundle.dispatched_at = now

    audit_log.record(
        action="action.bundle.dispatched",
        target_type="action_bundle",
        target_id=bundle.id,
        detail={
            "case_id": bundle.case_id,
            "notifications": [
                {"id": n.id, "agency": n.target_agency, "status": n.status}
                for n in notifications
            ],
            "data_mode": bundle.data_mode,
        },
    )
    bundle.audit = _bundle_audit(bundle)
    return bundle
