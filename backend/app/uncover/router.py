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

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.core.adapters import ChainDataAdapter, FiatDataAdapter
from app.core.auth import DISPATCH_ROLES, AuthContext, get_current_user, require_role
from app.uncover import service
from app.uncover.metrics import RangeKey, ResponseMetrics, compute_metrics
from app.uncover.notifications import NotificationSink
from app.uncover.service import (
    ActionBundle,
    AlreadyDispatchedError,
    ChainAdapterDep,
    FiatAdapterDep,
    GenerateRequest,
    SinkDep,
)

router = APIRouter(tags=["uncover"])


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
    _auth: AuthContext = Depends(get_current_user),  # any authenticated role
) -> ActionBundle:
    """One click → many artifacts: freeze PDF + LTKM/STR draft + evidence pack.

    Documents are generated, SHA-256 hashed, audit-chained, and returned as a
    **draft** bundle with the routing plan. Nothing is dispatched.
    """
    return await service.generate_bundle(body, chain, fiat)


@router.get("/actions/{action_id}", response_model=ActionBundle)
async def get_action(action_id: str) -> ActionBundle:
    """The bundle: documents (+hashes), status, routing plan, notifications, audit."""
    bundle = service.get_bundle(action_id)
    if bundle is None:
        raise _not_found("action", action_id)
    return bundle


@router.post("/actions/{action_id}/dispatch", response_model=ActionBundle)
async def post_dispatch(
    action_id: str,
    sink: NotificationSink = SinkDep,
    _auth: AuthContext = Depends(require_role(DISPATCH_ROLES)),
) -> ActionBundle:
    """Human-gated dispatch. POC: mock sink — notifications record
    status='mock' ("would dispatch to …"); nothing leaves the system.

    Role-gated: irreversible outward action → investigator/analyst/admin only
    (bank/exchange compliance can generate but not dispatch)."""
    try:
        bundle = await service.dispatch_bundle(action_id, sink)
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
    return bundle


@router.get("/documents/{document_id}")
async def get_document(document_id: str) -> Response:
    """Download the generated PDF (bytes verified against its custody hash).

    Deliberately unauthenticated in POC: the frontend uses plain <a href>
    links, which cannot carry a Bearer header. LIVE hardening: short-lived
    signed URLs (or frontend blob-fetch) before real evidence is served."""
    doc = service.get_document(document_id)
    if doc is None:
        raise _not_found("document", document_id)
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
) -> ResponseMetrics:
    """Response Dashboard read-model: cases, time-to-freeze vs the >12h manual
    baseline, funds at risk/frozen, recovery rate vs the 4.76% IASC baseline."""
    return compute_metrics(range)


@router.get("/uncover/ping")
async def ping() -> dict[str, str]:
    return {"module": "uncover"}
