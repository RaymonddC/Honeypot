"""CASEDATA router — add + list analyst-entered records that feed the engines.

POST /api/casedata/bank-accounts     → add a tracked bank account (→ TRACE)
GET  /api/casedata/bank-accounts     → list tracked bank accounts
POST /api/casedata/crypto-transfers  → add a transfer (→ TAKEDOWN graph)
GET  /api/casedata/crypto-transfers  → list added transfers

Writes require an authenticated identity (the record is agency-owned under
Postgres RLS). In POC/memory the store is a process-wide singleton.
"""

from fastapi import APIRouter, Depends, Query

from app.casedata.repository import CaseDataRepository, get_casedata_repository
from app.casedata.schemas import (
    AddBankAccountRequest,
    AddCryptoTxRequest,
    BankAccountOut,
    CryptoTxOut,
)
from app.core.auth import AuthContext, get_current_user

router = APIRouter(tags=["casedata"])

RepoDep = Depends(get_casedata_repository)
CaseQuery = Query(default=None, alias="case", description="Filter by case id")


@router.post("/casedata/bank-accounts", response_model=BankAccountOut, status_code=201)
async def add_bank_account(
    body: AddBankAccountRequest,
    repo: CaseDataRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> BankAccountOut:
    """Track a bank account — surfaced on the TRACE Bridge watchlist."""
    return await repo.add_bank_account(body)


@router.get("/casedata/bank-accounts", response_model=list[BankAccountOut])
async def list_bank_accounts(
    case: str | None = CaseQuery,
    repo: CaseDataRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> list[BankAccountOut]:
    return await repo.list_bank_accounts(case_id=case)


@router.post("/casedata/crypto-transfers", response_model=CryptoTxOut, status_code=201)
async def add_crypto_transfer(
    body: AddCryptoTxRequest,
    repo: CaseDataRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> CryptoTxOut:
    """Add a crypto transfer — merged into the TAKEDOWN Investigation graph
    (both endpoints of the edge become investigable wallets)."""
    return await repo.add_crypto_tx(body)


@router.get("/casedata/crypto-transfers", response_model=list[CryptoTxOut])
async def list_crypto_transfers(
    case: str | None = CaseQuery,
    repo: CaseDataRepository = RepoDep,
    _auth: AuthContext = Depends(get_current_user),
) -> list[CryptoTxOut]:
    return await repo.list_crypto_transfers(case_id=case)


@router.get("/casedata/ping")
async def ping() -> dict[str, str]:
    return {"module": "casedata"}
