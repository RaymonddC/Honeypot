"""UNCOVER router — Action Panel + Response Dashboard API (docs/API-Contract.md).

POST /api/actions/generate         → action_bundle (draft; docs generated+hashed)
GET  /api/actions/{id}             → action_bundle (+docs, status, audit)
POST /api/actions/{id}/dispatch    → action_bundle (human-gated; POC mock sink)
GET  /api/documents/{id}           → PDF binary (application/pdf, hashed)
GET  /api/metrics/response?range=  → dashboard metrics (Screen 4)

Endpoints compute in-memory from fixtures/generators (POC pattern, mirrors
P1/P2). Generation is automatic; **dispatch requires an explicit call** —
irreversible outward actions are never auto-fired.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Response, Request

from app.core.adapters import ChainDataAdapter, FiatDataAdapter
from app.core.audit import (
    BUNDLE_GENERATED,
    DISPATCH_SENT,
    EVIDENCE_EXPORTED,
    AuditRepository,
    PostgresAuditRepository,
    _memory_repository,
    record_action,
)
from app.core.auth import DISPATCH_ROLES, AuthContext, get_current_user, require_role
from app.core.db import get_optional_tenant_session
from app.uncover import service
from app.uncover.metrics import RangeKey, ResponseMetrics, compute_metrics
from app.uncover.notifications import NotificationOut, NotificationSink
from app.uncover.repository import UncoverRepository
from app.uncover.service import (
    ActionBundle,
    BundleAuditEntry,
    AlreadyDispatchedError,
    ChainAdapterDep,
    FiatAdapterDep,
    GenerateRequest,
    NotificationNotFoundError,
    RepoDep,
    SinkDep,
)

router = APIRouter(tags=["uncover"])


def _audit_repo(session) -> AuditRepository:
    """Same selection rule as record_action, so reads and writes never disagree
    about which chain they are talking to (mirrors app/cases/router.py)."""
    from app.core.config import get_settings

    if session is not None and get_settings().persistence == "postgres":
        return PostgresAuditRepository(session)
    return _memory_repository()


async def _attach_audit(bundle: ActionBundle, session, auth: AuthContext) -> ActionBundle:
    """Fill ``bundle.audit`` from the DURABLE core trail, agency-scoped.

    This is the seam the custody collapse turned on. ``uncover.custody`` used to
    supply this list from a per-process, in-memory chain: it recorded less than
    the core trail already did, and it was empty after every restart — which is
    how the Action Panel's "evidence hash" came to change on its own.

    Done in the router, not in ``service.get_bundle``: reading the trail needs an
    agency-scoped session, and threading one through the service layer would put
    tenancy into functions that currently know nothing about it. The router
    already holds both the session and the identity.

    Agency scoping is not decoration — a bundle's custody view must never show
    another tenant's entries, and under Postgres the RLS policy on
    core.audit_log enforces it underneath this query as well.

    Never raises: a bundle that cannot show its history is still a bundle, and
    the documents and their hashes are the evidence. Same reasoning as
    record_action's contract.
    """
    try:
        entries = await _audit_repo(session).list_for_target(
            agency_id=str(auth.agency.id), target_id=bundle.id, limit=200
        )
        bundle.audit = [
            BundleAuditEntry(
                seq=e.seq, action=e.action, actor=(e.detail or {}).get("_actor", ""),
                target_type=e.target_type, target_id=bundle.id, detail=e.detail or {},
                ts=e.ts, sha256=e.sha256, prev_sha256=e.prev_sha256,
            )
            for e in entries
        ]
    except Exception as exc:  # noqa: BLE001 - the bundle must still be returned
        import logging

        logging.getLogger("uvicorn.error").warning(
            "uncover: could not load the audit view for %s: %s: %s",
            bundle.id, type(exc).__name__, exc,
        )
    return bundle


def _not_found(kind: str, item_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": f"{kind}_not_found", "message": f"No {kind} with id {item_id}"},
    )


@router.post("/actions/generate", response_model=ActionBundle, status_code=201)
async def post_generate(
    body: GenerateRequest,
    chain: ChainDataAdapter = ChainAdapterDep,
    fiat: FiatDataAdapter = FiatAdapterDep,
    repo: UncoverRepository = RepoDep,
    auth: AuthContext = Depends(get_current_user),  # any authenticated role
    audit_session=Depends(get_optional_tenant_session),
    request: Request = None,  # audit origin (ip/user-agent)
) -> ActionBundle:
    """One click → many artifacts: freeze PDF + LTKM/STR draft + evidence pack.

    Documents are generated, SHA-256 hashed, audit-chained, and returned as a
    **draft** bundle with the routing plan. Nothing is dispatched. The signing
    agency/officer on the letters is the authenticated identity.
    """
    bundle = await service.generate_bundle(
        body, chain, fiat, repo=repo,
        agency=auth.agency.name,
        agency_type=auth.agency.type,
        officer_name=auth.user.name,
        officer_role=auth.role,  # slug → title mapped in the document generator
    )
    # Records the produced evidence and its hashes durably. Document sha256s are
    # already stored on action_documents; keeping them here too means the audit
    # trail alone answers "what was produced, by whom, and what did it hash to"
    # without having to trust a second table to still agree.
    await record_action(
        audit_session,
        agency_id=str(auth.agency.id),
        action=BUNDLE_GENERATED,
        actor_user_id=str(auth.user.id),
        actor_name=auth.user.name,
        request=request,
        target_type="action_bundle",
        target_id=bundle.id,
        target_label=f"{bundle.crime_type} bundle for case {bundle.case_id}",
        detail={
            "case_id": bundle.case_id,
            "crime_type": bundle.crime_type,
            "outputs": list(bundle.outputs),
            # format + template_version were previously only on the per-document
            # custody entries, which are gone with the in-memory chain. Carried
            # here so the collapse loses nothing: the sha256 proves WHICH bytes,
            # template_version explains what produced them, and a court asking
            # "what did this document look like" needs both.
            "documents": [
                {
                    "id": d.id, "type": d.type, "sha256": d.sha256,
                    "format": d.format, "template_version": d.template_version,
                }
                for d in bundle.documents
            ],
        },
    )
    return await _attach_audit(bundle, audit_session, auth)


@router.get("/actions/{action_id}", response_model=ActionBundle)
async def get_action(
    action_id: str,
    repo: UncoverRepository = RepoDep,
    auth: AuthContext = Depends(get_current_user),  # P-3: read routes need identity
    audit_session=Depends(get_optional_tenant_session),
) -> ActionBundle:
    """The bundle: documents (+hashes), status, routing plan, notifications, audit."""
    bundle = await service.get_bundle(action_id, repo=repo)
    if bundle is None:
        raise _not_found("action", action_id)
    return await _attach_audit(bundle, audit_session, auth)


@router.post("/actions/{action_id}/dispatch", response_model=ActionBundle)
async def post_dispatch(
    action_id: str,
    sink: NotificationSink = SinkDep,
    repo: UncoverRepository = RepoDep,
    auth: AuthContext = Depends(require_role(DISPATCH_ROLES)),
    audit_session=Depends(get_optional_tenant_session),
    request: Request = None,  # audit origin (ip/user-agent)
) -> ActionBundle:
    """Human-gated dispatch. POC: mock sink — notifications record
    status='mock' ("would dispatch to …"); nothing leaves the system.

    Role-gated: irreversible outward action → investigator/analyst/admin only
    (bank/exchange compliance can generate but not dispatch)."""
    try:
        bundle = await service.dispatch_bundle(action_id, sink, repo=repo)
    except AlreadyDispatchedError:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "already_dispatched",
                "message": f"Action {action_id} has already been dispatched",
            },
        )
    if bundle is None:
        raise _not_found("action", action_id)
    # The most consequential action in the product: irreversible, outward, and
    # role-gated for that reason. Records WHO authorised it and WHERE it went —
    # recipients by name, since "which agencies were told" is the question asked
    # afterwards. Never the payload or the signing secret.
    await record_action(
        audit_session,
        agency_id=str(auth.agency.id),
        action=DISPATCH_SENT,
        actor_user_id=str(auth.user.id),
        actor_name=auth.user.name,
        request=request,
        target_type="action_bundle",
        target_id=action_id,
        target_label=f"{bundle.crime_type} bundle for case {bundle.case_id}",
        detail={
            "recipients": [n.target_agency for n in bundle.notifications],
            "channels": sorted({n.channel for n in bundle.notifications if n.channel}),
            "crime_type": bundle.crime_type,
            "documents": len(bundle.documents),
            # Per-notification detail, previously held ONLY by the in-memory
            # custody chain. Kept rather than dropped in the collapse: "which
            # notification went where, and did it land" is the question asked
            # after a dispatch, and `recipients` alone cannot answer it.
            # `recipients`/`channels` stay as the at-a-glance summary.
            "notifications": [
                {"id": n.id, "agency": n.target_agency, "status": n.status}
                for n in bundle.notifications
            ],
        },
    )
    return await _attach_audit(bundle, audit_session, auth)


@router.get("/notifications", response_model=list[NotificationOut])
async def get_notifications(
    repo: UncoverRepository = RepoDep,
    status: str | None = Query(default=None, description="mock|queued|sending|sent|failed"),
    agency_type: str | None = Query(default=None, description="bank|exchange|regulator|police"),
    case_id: str | None = Query(default=None),
    _auth: AuthContext = Depends(get_current_user),  # read route needs identity
) -> list[NotificationOut]:
    """The Dispatch Log / agency outbox: every notification ITTU has fired
    (RLS-scoped to the caller's agency under Postgres), newest first, with
    optional status/agency-type/case filters."""
    return await service.list_notifications(
        repo=repo, status=status, agency_type=agency_type, case_id=case_id
    )


@router.post("/notifications/{notification_id}/retry", response_model=NotificationOut)
async def post_notification_retry(
    notification_id: str,
    sink: NotificationSink = SinkDep,
    repo: UncoverRepository = RepoDep,
    _auth: AuthContext = Depends(require_role(DISPATCH_ROLES)),
) -> NotificationOut:
    """Re-dispatch a failed notification (idempotent — the recipient dedupes on
    the reused key; an already-``sent`` one no-ops). Role-gated like dispatch:
    it's an outward action."""
    try:
        return await service.retry_notification(notification_id, sink, repo=repo)
    except NotificationNotFoundError:
        raise _not_found("notification", notification_id)


@router.get("/documents/{document_id}")
async def get_document(
    document_id: str,
    repo: UncoverRepository = RepoDep,
    auth: AuthContext = Depends(get_current_user),  # P-5: read route needs identity
    audit_session=Depends(get_optional_tenant_session),
    request: Request = None,
) -> Response:
    """Download the generated PDF (bytes verified against its custody hash).

    P-5: the frontend now fetches this with JS (``apiFetch`` attaches the
    Bearer), builds a blob from the response, and triggers the save from
    that blob — the old plain ``<a href>`` link (which couldn't carry a
    header) is gone, so this route is protected like every other read route
    that touches the repo (mirrors P-4a's INFILTRATE routes / P-3's
    ``GET /api/actions/{id}``). Under ``settings.persistence == "postgres"``
    this identity is what scopes the RLS-backed tenant session."""
    doc = await service.get_document(document_id, repo=repo)
    if doc is None:
        raise _not_found("document", document_id)
    # Evidence leaving the system. Records the document's custody hash so the
    # trail says exactly WHICH bytes were taken, not merely that a download
    # happened — the hash is what makes the exported copy comparable later.
    await record_action(
        audit_session,
        agency_id=str(auth.agency.id),
        action=EVIDENCE_EXPORTED,
        actor_user_id=str(auth.user.id),
        actor_name=auth.user.name,
        target_type="action_document",
        target_id=document_id,
        target_label=doc.filename,
        request=request,
        detail={"sha256": doc.sha256, "type": doc.type, "status": doc.status},
    )
    return Response(
        content=doc.pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{doc.filename}"',
            "X-Document-SHA256": doc.sha256,
            "X-Document-Status": doc.status,
            "X-Data-Mode": doc.data_mode,
        },
    )


@router.get("/metrics/response", response_model=ResponseMetrics)
async def get_response_metrics(
    range: RangeKey = Query(default="30d", description="7d | 30d | all"),
    repo: UncoverRepository = RepoDep,
) -> ResponseMetrics:
    """Response Dashboard read-model: cases, time-to-freeze vs the >12h manual
    baseline, funds at risk/frozen, recovery rate vs the 4.76% IASC baseline.

    Deliberately left OPEN (no ``Depends(get_current_user)``) — it's a
    cross-agency demo/ops view today (``all_bundles()`` was never
    agency-scoped even in memory mode), and ``test_auth_rbac.py`` pins it as
    a "stays open" endpoint alongside personas/sankey/config. It still goes
    through ``RepoDep``, so under postgres persistence a request with no
    Bearer 401s the same way ``get_document`` above does — this route
    degrades, rather than silently exposing another agency's action data
    without RLS."""
    return await compute_metrics(range, repo=repo)


@router.get("/uncover/ping")
async def ping() -> dict[str, str]:
    return {"module": "uncover"}
