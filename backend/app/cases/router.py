"""CASES router — the case file CRUD (the spine of the case-centric flow).

POST  /api/cases            → create a case
GET   /api/cases            → list the agency's cases (newest first)
GET   /api/cases/{id}       → one case
PATCH /api/cases/{id}       → update stage/status/title/summary/crime_type
GET   /api/cases/{id}/rollup→ the case + its attached case-data counts

All routes require an authenticated identity (cases are agency-owned).
"""

from fastapi import APIRouter, Depends, HTTPException

from app.cases.repository import CaseRepository, get_case_repository
from app.cases.schemas import CaseOut, CreateCaseRequest, UpdateCaseRequest
from app.casedata.repository import CaseDataRepository, get_casedata_repository
from app.casedata.schemas import BankAccountOut, CryptoTxOut
from app.core.auth import AuthContext, get_current_user
from pydantic import BaseModel

router = APIRouter(tags=["cases"])

RepoDep = Depends(get_case_repository)
CaseDataDep = Depends(get_casedata_repository)


def _not_found(case_id: str) -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={"code": "case_not_found", "message": f"No case with id {case_id}"},
    )


class CaseRollup(BaseModel):
    case: CaseOut
    bank_accounts: list[BankAccountOut]
    crypto_transfers: list[CryptoTxOut]
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
    _auth: AuthContext = Depends(get_current_user),
) -> CaseRollup:
    """The case file: the case + all case-data records attached to it."""
    case = await repo.get_case(case_id)
    if case is None:
        raise _not_found(case_id)
    banks = await casedata.list_bank_accounts(case_id=case_id)
    txs = await casedata.list_crypto_transfers(case_id=case_id)
    return CaseRollup(
        case=case,
        bank_accounts=banks,
        crypto_transfers=txs,
        counts={"bank_accounts": len(banks), "crypto_transfers": len(txs)},
    )


@router.get("/cases-ping")
async def ping() -> dict[str, str]:
    return {"module": "cases"}
