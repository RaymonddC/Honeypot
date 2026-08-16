"""HONEYPOT OPS router — the number pool + dial campaigns
(docs/Voice-Honeypot-Outbound.md §6).

GET/POST  /api/honeypot/numbers               → list / register a pool number
PATCH     /api/honeypot/numbers/{id}          → retire / relabel
GET/POST  /api/honeypot/campaigns             → list / create a campaign
GET       /api/honeypot/campaigns/{id}        → one campaign + per-status counts
GET       /api/honeypot/campaigns/{id}/targets→ its dial targets
POST      /api/honeypot/campaigns/{id}/targets→ bulk-upload numbers (JSON/CSV paste)
POST      /api/honeypot/campaigns/{id}/start  → draft|paused → running (+ enqueue)
POST      /api/honeypot/campaigns/{id}/pause  → running → paused
POST      /api/honeypot/campaigns/{id}/requeue→ finished targets → queued (§3.6)

``start`` moves the status and, when ``ITTU_DIAL_ENQUEUE_ON_START`` is on under
Postgres, hands the queued targets to the ``dial_target`` actor. That actor
**simulates** in POC and fails loud in LIVE: real Twilio calls are phase 5, and
dialing real reported numbers stays behind the Polri gate (design spec §0).

All routes require an authenticated identity: numbers and campaigns are
agency-owned under Postgres RLS.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.core.auth import AuthContext, get_current_user
from app.core.config import get_settings
from app.honeypot_ops.repository import (
    HoneypotOpsRepository,
    get_honeypot_ops_repository,
)
from app.honeypot_ops.schemas import (
    AddNumberRequest,
    CreateCampaignRequest,
    DialCampaignOut,
    DialTargetOut,
    HoneypotNumberOut,
    RequeueRequest,
    RequeueResult,
    UpdateNumberRequest,
    UploadTargetsRequest,
    UploadTargetsResult,
)

logger = logging.getLogger("uvicorn.error")

router = APIRouter(tags=["honeypot-ops"])

RepoDep = Depends(get_honeypot_ops_repository)


def _not_found(kind: str, item_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": f"{kind}_not_found", "message": f"No {kind} with id {item_id}"},
    )


def _split_pasted(text: str) -> list[str]:
    """Pull one candidate number per line out of pasted text.

    CSV exports put the number first on the row, so take field 0; a plain
    newline-separated list is the degenerate case of the same rule.
    """
    out: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(line.split(",")[0].strip().strip('"'))
    return out


# ── numbers ──────────────────────────────────────────────────────────────── #


@router.post("/honeypot/numbers", response_model=HoneypotNumberOut, status_code=201)
async def add_number(
    body: AddNumberRequest,
    repo: HoneypotOpsRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> HoneypotNumberOut:
    """Register a Twilio number bought/configured in the Twilio console.

    We deliberately do NOT provision numbers via the Twilio API (design
    decision §9) — buying a number spends real money and stays a human action.
    """
    created = await repo.add_number(body)
    if created is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "number_already_registered",
                "message": f"{body.phone_number} is already in the pool",
            },
        )
    return created


@router.get("/honeypot/numbers", response_model=list[HoneypotNumberOut])
async def list_numbers(
    repo: HoneypotOpsRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> list[HoneypotNumberOut]:
    return await repo.list_numbers()


@router.patch("/honeypot/numbers/{number_id}", response_model=HoneypotNumberOut)
async def update_number(
    number_id: str,
    body: UpdateNumberRequest,
    repo: HoneypotOpsRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> HoneypotNumberOut:
    """Retire or relabel a pool number. Retired numbers are kept for provenance
    (past calls reference them) but are never dialed from again."""
    updated = await repo.update_number(number_id, body)
    if updated is None:
        raise _not_found("number", number_id)
    return updated


# ── campaigns ────────────────────────────────────────────────────────────── #


@router.post("/honeypot/campaigns", response_model=DialCampaignOut, status_code=201)
async def create_campaign(
    body: CreateCampaignRequest,
    repo: HoneypotOpsRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> DialCampaignOut:
    """Open a new dial campaign (draft — upload targets, then start it)."""
    return await repo.create_campaign(body)


@router.get("/honeypot/campaigns", response_model=list[DialCampaignOut])
async def list_campaigns(
    repo: HoneypotOpsRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> list[DialCampaignOut]:
    return await repo.list_campaigns()


@router.get("/honeypot/campaigns/{campaign_id}", response_model=DialCampaignOut)
async def get_campaign(
    campaign_id: str,
    repo: HoneypotOpsRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> DialCampaignOut:
    """One campaign + its per-status target counts (the progress rollup)."""
    camp = await repo.get_campaign(campaign_id)
    if camp is None:
        raise _not_found("campaign", campaign_id)
    return camp


@router.post(
    "/honeypot/campaigns/{campaign_id}/targets", response_model=UploadTargetsResult
)
async def upload_targets(
    campaign_id: str,
    body: UploadTargetsRequest,
    repo: HoneypotOpsRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> UploadTargetsResult:
    """Bulk-add numbers to a campaign from a JSON array and/or pasted CSV text.

    Per-row outcome: valid numbers are added, bad ones come back in
    ``rejected`` with a reason (invalid / duplicate_in_upload /
    already_in_campaign). One bad row never fails the whole upload — a dial
    list is pasted from spreadsheets and victim reports, so partial junk is
    the norm, not an exception.
    """
    raw = [*body.numbers, *_split_pasted(body.text)]
    result = await repo.add_targets(campaign_id, raw)
    if result is None:
        raise _not_found("campaign", campaign_id)
    return result


@router.get(
    "/honeypot/campaigns/{campaign_id}/targets", response_model=list[DialTargetOut]
)
async def list_targets(
    campaign_id: str,
    repo: HoneypotOpsRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> list[DialTargetOut]:
    targets = await repo.list_targets(campaign_id)
    if targets is None:
        raise _not_found("campaign", campaign_id)
    return targets


@router.post("/honeypot/campaigns/{campaign_id}/start", response_model=DialCampaignOut)
async def start_campaign(
    campaign_id: str,
    repo: HoneypotOpsRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> DialCampaignOut:
    """Mark a campaign running. **Does not dial yet** — the ``dial_target``
    actor lands in phase 4; this is the status transition + its guards."""
    camp = await repo.get_campaign(campaign_id)
    if camp is None:
        raise _not_found("campaign", campaign_id)
    if camp.status == "completed":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "campaign_completed",
                "message": "A completed campaign cannot be restarted",
            },
        )
    if camp.target_count == 0:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "campaign_empty",
                "message": "Upload at least one target before starting",
            },
        )
    updated = await repo.set_campaign_status(campaign_id, "running")
    if updated is None:  # pragma: no cover - existence checked above
        raise _not_found("campaign", campaign_id)

    await _maybe_enqueue(repo, updated)
    return updated


async def _maybe_enqueue(repo: HoneypotOpsRepository, camp: DialCampaignOut) -> None:
    """Hand this campaign's queued targets to the ``dial_target`` actor.

    Opt-in and doubly gated, because enqueueing is the step that makes a
    campaign *do* something:

    * ``ITTU_DIAL_ENQUEUE_ON_START`` (default **off**) — without it, ``start``
      stays the pure status transition phase 3 shipped, so the UI is demoable
      with no Redis and no worker running.
    * Postgres persistence — the actor runs in another process and loads the
      target by id, which the in-memory repo cannot serve.

    Failure to enqueue is logged, not raised: the campaign IS running and its
    targets are durably ``queued``, so a later start (or a worker catching up)
    still dials them. Turning a broker hiccup into a 500 would falsely suggest
    the campaign didn't start.
    """
    settings = get_settings()
    if not settings.dial_enqueue_on_start or settings.persistence != "postgres":
        return
    targets = await repo.list_targets(camp.id) or []
    queued = [t.id for t in targets if t.status == "queued"]
    if not queued:
        return
    try:
        from app.honeypot_ops.dialer import enqueue_campaign_targets

        enqueue_campaign_targets(queued, pacing_per_minute=camp.pacing_per_minute)
    except Exception as exc:  # noqa: BLE001 - a broker outage must not fail the start
        logger.warning(
            "dial enqueue failed for campaign %s (%d target(s) stay queued): %s: %s",
            camp.id, len(queued), type(exc).__name__, exc,
        )


@router.post("/honeypot/campaigns/{campaign_id}/requeue", response_model=RequeueResult)
async def requeue_targets(
    campaign_id: str,
    body: RequeueRequest | None = None,
    repo: HoneypotOpsRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> RequeueResult:
    """Send finished targets back to ``queued`` so they are dialed again (§3.6).

    This is how you call a number a second time. A campaign never holds two rows
    for the same number — duplicate rows would make the per-status counts
    meaningless — so re-calling is a state change on the existing target, and
    ``attempt_count`` is preserved as the retry history.

    Body: ``{target_ids: [...]}`` for specific targets, or ``{statuses: [...]}``
    to sweep (default: every ``no_answer`` and ``failed``). Targets that are
    ``queued`` or ``dialing`` are skipped and counted — never requeued, since a
    ``dialing`` target has a call in flight and requeueing it would place a
    second call to the same person.
    """
    result = await repo.requeue_targets(campaign_id, body or RequeueRequest())
    if result is None:
        raise _not_found("campaign", campaign_id)
    return result


@router.post("/honeypot/campaigns/{campaign_id}/pause", response_model=DialCampaignOut)
async def pause_campaign(
    campaign_id: str,
    repo: HoneypotOpsRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> DialCampaignOut:
    """Pause a running campaign (resume with /start)."""
    camp = await repo.get_campaign(campaign_id)
    if camp is None:
        raise _not_found("campaign", campaign_id)
    if camp.status != "running":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "campaign_not_running",
                "message": f"Only a running campaign can be paused (is {camp.status})",
            },
        )
    updated = await repo.set_campaign_status(campaign_id, "paused")
    if updated is None:  # pragma: no cover - existence checked above
        raise _not_found("campaign", campaign_id)
    return updated


@router.get("/honeypot/ping")
async def ping() -> dict[str, str]:
    return {"module": "honeypot-ops"}
