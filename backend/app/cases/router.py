"""CASES router — the case file CRUD (the spine of the case-centric flow).

POST  /api/cases            → create a case
GET   /api/cases            → list the agency's cases (newest first)
GET   /api/cases/{id}       → one case
PATCH /api/cases/{id}       → update stage/status/title/summary/crime_type
GET   /api/cases/{id}/rollup→ the case + its attached case-data counts

All routes require an authenticated identity (cases are agency-owned).
"""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.cases.repository import CaseRepository, get_case_repository
from app.cases.schemas import (
    CaseDocumentSummary,
    CaseOut,
    CaseSessionSummary,
    CreateCaseRequest,
    UpdateCaseRequest,
)
from app.casedata.repository import CaseDataRepository, get_casedata_repository
from app.casedata.schemas import BankAccountOut, CryptoTxOut
from app.core.audit import (
    CASE_CREATED,
    CASE_UPDATED,
    AuditRepository,
    InMemoryAuditRepository,
    PostgresAuditRepository,
    _memory_repository,
    record_action,
)
from app.core.auth import AuthContext, get_current_user
from app.core.db import get_optional_tenant_session
from app.infiltrate import service as infiltrate_service
from app.infiltrate.repository import InfiltrateRepository, get_infiltrate_repository
from app.uncover import service as uncover_service
from app.uncover.repository import UncoverRepository, get_uncover_repository

router = APIRouter(tags=["cases"])

RepoDep = Depends(get_case_repository)
CaseDataDep = Depends(get_casedata_repository)
InfiltrateDep = Depends(get_infiltrate_repository)
UncoverDep = Depends(get_uncover_repository)


def _audit_repo(session) -> AuditRepository:
    """Same selection rule as record_action, so reads and writes never disagree
    about which chain they are talking to."""
    from app.core.config import get_settings

    if session is not None and get_settings().persistence == "postgres":
        return PostgresAuditRepository(session)
    return _memory_repository()


def _not_found(case_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "case_not_found", "message": f"No case with id {case_id}"},
    )


class CaseRollup(BaseModel):
    case: CaseOut
    bank_accounts: list[BankAccountOut]
    crypto_transfers: list[CryptoTxOut]
    sessions: list[CaseSessionSummary]
    documents: list[CaseDocumentSummary]
    counts: dict[str, int]


class AuditEntryOut(BaseModel):
    """One audit row. Hashes are hex so a reviewer can compare them by eye."""

    seq: int
    action: str
    actor_user_id: str | None = None
    target_type: str | None = None
    target_id: str | None = None
    detail: dict = {}
    ts: datetime
    sha256: str
    prev_sha256: str


class AuditFeedOut(BaseModel):
    entries: list[AuditEntryOut]
    chain_ok: bool           # every hash links to its predecessor
    broken_at_seq: int | None = None   # first entry that fails, if any


@router.get("/audit", response_model=AuditFeedOut)
async def get_audit_feed(
    limit: int = 100,
    auth: AuthContext = Depends(get_current_user),
    session=Depends(get_optional_tenant_session),
    request: Request = None,  # audit origin (ip/user-agent)
) -> AuditFeedOut:
    """This agency's audit trail, newest first, with the chain verified.

    Agency-scoped deliberately: one tenant must never read another's actions,
    and the chain is per-agency for the same reason (see app/core/audit.py).

    ``chain_ok`` is computed on read rather than trusted: an audit log that is
    never verified proves nothing — the point of chaining is that tampering
    becomes *detectable*, which requires someone to actually check.

    **What ``chain_ok: true`` does and does not mean.** It means no entry here
    was **altered or removed** — every hash still links to the one before it. It
    does NOT mean every action reached this log. An entry that failed to be
    written leaves nothing behind: the entries around it link normally, so there
    is no gap for verification to find. That is a property of any append-only
    log, not a defect in this one, and it is why write failures are counted and
    alerted on separately (``ittu_audit_entries_dropped_total``, docs/Deploy.md
    §8) rather than being inferred from the chain. Stated here because "verified"
    invites the stronger reading, and an auditor is entitled to know which claim
    they are being handed.
    """
    repo = _audit_repo(session)
    agency = str(auth.agency.id)
    entries = await repo.list_entries(agency_id=agency, limit=limit)
    ok, broken = await repo.verify_chain(agency_id=agency)
    return AuditFeedOut(
        entries=[
            AuditEntryOut(
                seq=e.seq, action=e.action, actor_user_id=e.actor_user_id,
                target_type=e.target_type, target_id=e.target_id, detail=e.detail,
                ts=e.ts, sha256=e.sha256, prev_sha256=e.prev_sha256,
            )
            for e in entries
        ],
        chain_ok=ok,
        broken_at_seq=broken,
    )


@router.post("/cases", response_model=CaseOut, status_code=201)
async def create_case(
    body: CreateCaseRequest,
    repo: CaseRepository = RepoDep,
    auth: AuthContext = Depends(get_current_user),
    session=Depends(get_optional_tenant_session),
    request: Request = None,  # audit origin (ip/user-agent)
) -> CaseOut:
    """Open a new investigation case."""
    case = await repo.create_case(body)
    # Same session as the write above, so the audit entry commits with the case
    # rather than describing one that might still roll back.
    await record_action(
        session,
        agency_id=str(auth.agency.id),
        action=CASE_CREATED,
        actor_user_id=str(auth.user.id),
        actor_name=auth.user.name,
        request=request,
        target_type="case",
        target_id=case.id,
        target_label=case.title,
        detail={"title": case.title, "stage": case.stage, "crime_type": case.crime_type},
    )
    return case


@router.get("/cases", response_model=list[CaseOut])
async def list_cases(
    repo: CaseRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> list[CaseOut]:
    return await repo.list_cases()


@router.get("/cases/{case_id}", response_model=CaseOut)
async def get_case(
    case_id: str,
    repo: CaseRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> CaseOut:
    case = await repo.get_case(case_id)
    if case is None:
        raise _not_found(case_id)
    return case


@router.patch("/cases/{case_id}", response_model=CaseOut)
async def update_case(
    case_id: str,
    body: UpdateCaseRequest,
    repo: CaseRepository = RepoDep,
    auth: AuthContext = Depends(get_current_user),
    session=Depends(get_optional_tenant_session),
    request: Request = None,  # audit origin (ip/user-agent)
) -> CaseOut:
    """Advance the stage, change status, or edit case fields."""
    case = await repo.update_case(case_id, body)
    if case is None:
        raise _not_found(case_id)
    # Only what the caller actually asked to change — logging the whole object
    # would bury the one field that moved, and "stage: trace -> takedown" is the
    # line an investigator (or a court) needs to read.
    changed = body.model_dump(exclude_none=True)
    await record_action(
        session,
        agency_id=str(auth.agency.id),
        action=CASE_UPDATED,
        actor_user_id=str(auth.user.id),
        actor_name=auth.user.name,
        request=request,
        target_type="case",
        target_id=case.id,
        target_label=case.title,
        detail={"changed": changed},
    )
    return case


@router.get("/cases/{case_id}/rollup", response_model=CaseRollup)
async def get_case_rollup(
    case_id: str,
    repo: CaseRepository = RepoDep,
    casedata: CaseDataRepository = CaseDataDep,
    infiltrate: InfiltrateRepository = InfiltrateDep,
    uncover: UncoverRepository = UncoverDep,
    _auth: AuthContext = Depends(get_current_user),
) -> CaseRollup:
    """The case file: the case + everything attached to it across all modules —
    tracked bank accounts + crypto transfers (case-data), honeypot sessions
    (INFILTRATE) and action documents (UNCOVER)."""
    case = await repo.get_case(case_id)
    if case is None:
        raise _not_found(case_id)

    banks = await casedata.list_bank_accounts(case_id=case_id)
    txs = await casedata.list_crypto_transfers(case_id=case_id)

    sessions = [
        CaseSessionSummary(
            id=s.id, channel=s.channel, channel_type=s.channel_type,
            channel_ref=s.channel_ref,
            crime_type=s.crime_type, status=s.status,
            entity_count=s.entity_count, started_at=s.started_at,
        )
        for s in await infiltrate_service.list_sessions(repo=infiltrate)
        if s.case_id == case_id
    ]

    documents = [
        CaseDocumentSummary(
            id=b.id, status=b.status, crime_type=b.crime_type,
            document_count=len(b.documents), created_at=b.created_at,
        )
        for b in await uncover_service.all_bundles(repo=uncover)
        if b.case_id == case_id
    ]

    return CaseRollup(
        case=case,
        bank_accounts=banks,
        crypto_transfers=txs,
        sessions=sessions,
        documents=documents,
        counts={
            "bank_accounts": len(banks),
            "crypto_transfers": len(txs),
            "sessions": len(sessions),
            "documents": len(documents),
        },
    )


@router.get("/cases-ping")
async def ping() -> dict[str, str]:
    return {"module": "cases"}
