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
GET       /api/honeypot/targets/{id}/attempts → the call log for one target
GET       /api/honeypot/triage                → connected calls with no case yet
POST      /api/honeypot/triage/{id}/attach    → attach to an existing case
POST      /api/honeypot/triage/{id}/promote   → open a new case + attach (§5)

``start`` moves the status and, when ``ITTU_DIAL_ENQUEUE_ON_START`` is on under
Postgres, hands the queued targets to the ``dial_target`` actor. That actor
**simulates** in POC and fails loud in LIVE: real Twilio calls are phase 5, and
dialing real reported numbers stays behind the Polri gate (design spec §0).

Triage is where a connected call goes when auto-linking found nothing. Linking
is exact-match only (§9): a wrong auto-link quietly merges two investigations
inside a court-bound file, while a wrong triage costs ten seconds — so anything
short of certainty is handed to a human.

All routes require an authenticated identity: numbers and campaigns are
agency-owned under Postgres RLS.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.cases.repository import CaseRepository, get_case_repository
from app.cases.schemas import CreateCaseRequest
from app.core.audit import TRIAGE_ATTACHED, TRIAGE_PROMOTED, record_action
from app.core.auth import AuthContext, get_current_user
from app.core.db import get_optional_tenant_session
from app.core.config import get_settings
from app.honeypot_ops.repository import (
    HoneypotOpsRepository,
    get_honeypot_ops_repository,
)
from app.honeypot_ops.schemas import (
    AddNumberRequest,
    AttachSessionRequest,
    CreateCampaignRequest,
    DialAttemptOut,
    DialCampaignOut,
    DialTargetOut,
    HoneypotNumberOut,
    PromoteSessionRequest,
    PromoteSessionResult,
    RequeueRequest,
    RequeueResult,
    TriageSessionOut,
    UpdateNumberRequest,
    UploadTargetsRequest,
    UploadTargetsResult,
)
from app.honeypot_ops.triage import TriageRepository, get_triage_repository

logger = logging.getLogger("uvicorn.error")

router = APIRouter(tags=["honeypot-ops"])

RepoDep = Depends(get_honeypot_ops_repository)
TriageDep = Depends(get_triage_repository)
CaseDep = Depends(get_case_repository)


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


@router.get(
    "/honeypot/targets/{target_id}/attempts", response_model=list[DialAttemptOut]
)
async def list_attempts(
    target_id: str,
    repo: HoneypotOpsRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> list[DialAttemptOut]:
    """The call log for one target — every attempt, oldest first.

    Includes the attempts nobody answered, which is the point: `attempt_count`
    on the target says "tried 3 times", this says when each one happened and
    what came of it. An attempt that connected carries `session_id`, the
    conversation (transcript + intel) it produced.
    """
    attempts = await repo.list_attempts(target_id)
    if attempts is None:
        raise _not_found("target", target_id)
    return attempts


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


# ── triage ───────────────────────────────────────────────────────────────── #


def _prefill(sess: TriageSessionOut) -> CreateCaseRequest:
    """Draft a case from what the call already produced (§5).

    The classifier has already decided a crime type and the call knows its own
    number and date, so an investigator confirming a judgement shouldn't retype
    any of it. Every field is overridable in the request body.
    """
    when = sess.started_at.strftime("%d %b %Y")
    number = sess.channel_ref or "unknown number"
    bits = [f"Honeypot voice call with {number} on {when}."]
    if sess.duration_seconds:
        bits.append(f"Duration {sess.duration_seconds}s.")
    if sess.entity_count:
        bits.append(
            f"{sess.entity_count} entit{'y' if sess.entity_count == 1 else 'ies'} extracted."
        )
    bits.append(f"Promoted from triage (session {sess.id}).")
    return CreateCaseRequest(
        title=f"Voice call {number} · {when}"[:160],
        crime_type=sess.crime_type,
        summary=" ".join(bits)[:2000],
    )


@router.get("/honeypot/triage", response_model=list[TriageSessionOut])
async def list_triage(
    repo: TriageRepository = TriageDep,
    _auth: AuthContext = Depends(get_current_user),
) -> list[TriageSessionOut]:
    """Connected calls with no case yet — newest first.

    Every unmatched call is listed, including ones that extracted nothing: an
    engaged call with zero entities still proves the number is live and answered,
    which is itself worth an investigator's judgement. ``entity_count`` is on
    each row so a busy queue can be worked richest-first.
    """
    return await repo.list_triage()


@router.post(
    "/honeypot/triage/{session_id}/attach", response_model=TriageSessionOut
)
async def attach_triage_session(
    session_id: str,
    body: AttachSessionRequest,
    repo: TriageRepository = TriageDep,
    case_repo: CaseRepository = CaseDep,
    auth: AuthContext = Depends(get_current_user),
    audit_session=Depends(get_optional_tenant_session),
) -> TriageSessionOut:
    """Attach a triaged call to an existing case."""
    if await case_repo.get_case(body.case_id) is None:
        raise _not_found("case", body.case_id)
    attached = await repo.attach(session_id, body.case_id)
    if attached is None:
        raise _not_found("session", session_id)
    # Filing a call into a case is an evidentiary decision — auto-linking is
    # exact-match only precisely so a human owns the ambiguous ones (§5/§9).
    await record_action(
        audit_session,
        agency_id=str(auth.agency.id),
        action=TRIAGE_ATTACHED,
        actor_user_id=str(auth.user.id),
        target_type="session",
        target_id=session_id,
        detail={"case_id": body.case_id, "session_id": session_id},
    )
    return attached


@router.post(
    "/honeypot/triage/{session_id}/promote",
    response_model=PromoteSessionResult,
    status_code=201,
)
async def promote_triage_session(
    session_id: str,
    body: PromoteSessionRequest | None = None,
    repo: TriageRepository = TriageDep,
    case_repo: CaseRepository = CaseDep,
    auth: AuthContext = Depends(get_current_user),
    audit_session=Depends(get_optional_tenant_session),
) -> PromoteSessionResult:
    """Open a NEW case for a triaged call and attach it, in one step.

    Case creation goes through the same ``CaseRepository`` the Cases API uses,
    so a promoted case is indistinguishable from a hand-made one.
    """
    sess = await repo.get_triage(session_id)
    if sess is None:
        raise _not_found("session", session_id)
    body = body or PromoteSessionRequest()

    draft = _prefill(sess)
    if body.title is not None:
        draft.title = body.title
    if body.crime_type is not None:
        draft.crime_type = body.crime_type
    if body.summary is not None:
        draft.summary = body.summary

    created = await case_repo.create_case(draft)
    attached = await repo.attach(session_id, created.id)
    if attached is None:  # pragma: no cover - existence checked above
        raise _not_found("session", session_id)
    # One entry, not two: this opened a case AND filed a call into it as a
    # single operator decision, and `overrides` records where the human
    # disagreed with the prefill — which is the interesting part on review.
    await record_action(
        audit_session,
        agency_id=str(auth.agency.id),
        action=TRIAGE_PROMOTED,
        actor_user_id=str(auth.user.id),
        target_type="case",
        target_id=created.id,
        detail={
            "session_id": session_id,
            "title": created.title,
            "crime_type": created.crime_type,
            "overrides": sorted(
                k for k in ("title", "crime_type", "summary")
                if getattr(body, k, None) is not None
            ),
        },
    )
    return PromoteSessionResult(case=created, session=attached)


@router.get("/honeypot/ping")
async def ping() -> dict[str, str]:
    return {"module": "honeypot-ops"}
