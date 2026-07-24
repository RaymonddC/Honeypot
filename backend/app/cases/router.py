"""CASES router — the case file CRUD (the spine of the case-centric flow).

POST  /api/cases            → create a case
GET   /api/cases            → list the agency's cases (newest first)
GET   /api/cases/{id}       → one case
PATCH /api/cases/{id}       → update stage/status/title/summary/crime_type
GET   /api/cases/{id}/rollup→ the case + its attached case-data counts

All routes require an authenticated identity (cases are agency-owned).
"""

from fastapi import APIRouter, Depends, HTTPException
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
from app.core.auth import AuthContext, get_current_user
from app.infiltrate import service as infiltrate_service
from app.infiltrate.repository import InfiltrateRepository, get_infiltrate_repository
from app.uncover import service as uncover_service
from app.uncover.repository import UncoverRepository, get_uncover_repository

router = APIRouter(tags=["cases"])

RepoDep = Depends(get_case_repository)
CaseDataDep = Depends(get_casedata_repository)
InfiltrateDep = Depends(get_infiltrate_repository)
UncoverDep = Depends(get_uncover_repository)


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


@router.post("/cases", response_model=CaseOut, status_code=201)
async def create_case(
    body: CreateCaseRequest,
    repo: CaseRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> CaseOut:
    """Open a new investigation case."""
    return await repo.create_case(body)


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
    _auth: AuthContext = Depends(get_current_user),
) -> CaseOut:
    """Advance the stage, change status, or edit case fields."""
    case = await repo.update_case(case_id, body)
    if case is None:
        raise _not_found(case_id)
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
            id=s.id, channel=s.channel, channel_ref=s.channel_ref,
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
