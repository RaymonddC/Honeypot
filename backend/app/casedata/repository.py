"""CASEDATA persistence — memory (POC) + Postgres (RLS) dual, selected by
``settings.persistence``. Same shape/rationale as INFILTRATE's repository
(docs/Persistence-Plan.md): MODE picks external adapters, persistence picks
where state lives — orthogonal axes, so this does NOT go through the adapter
registry.
"""

import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol, runtime_checkable

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.casedata.models import BankAccountRecord, CryptoTransferRecord
from app.casedata.schemas import (
    AddBankAccountRequest,
    AddCryptoTxRequest,
    BankAccountOut,
    CryptoTxOut,
)
from app.core.auth import AuthContext
from app.core.auth import get_optional_current_user as _get_optional_current_user
from app.core.config import get_settings
from app.core.db import get_optional_tenant_session


@runtime_checkable
class CaseDataRepository(Protocol):
    """Storage surface for analyst-entered bank accounts + crypto transfers."""

    async def add_bank_account(self, req: AddBankAccountRequest) -> BankAccountOut: ...
    async def list_bank_accounts(self, case_id: str | None = None) -> list[BankAccountOut]: ...
    async def add_crypto_tx(self, req: AddCryptoTxRequest) -> CryptoTxOut: ...
    async def list_crypto_transfers(self, case_id: str | None = None) -> list[CryptoTxOut]: ...

    def reset(self) -> None:
        """Clear all state — memory-only test hook (see reset_stores)."""
        ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mint_tx_hash(req: AddCryptoTxRequest) -> str:
    """A stable-ish synthetic tx hash when the analyst didn't supply one."""
    return req.tx_hash or f"manual-{uuid.uuid4().hex}"


# --------------------------------------------------------------------------- #
# In-memory (POC)
# --------------------------------------------------------------------------- #


class InMemoryCaseDataRepository:
    """POC impl — process-wide lists, async to satisfy the Protocol."""

    def __init__(self) -> None:
        self._banks: list[BankAccountOut] = []
        self._txs: list[CryptoTxOut] = []

    async def add_bank_account(self, req: AddBankAccountRequest) -> BankAccountOut:
        rec = BankAccountOut(
            id=f"bank_{uuid.uuid4().hex[:12]}",
            bank_name=req.bank_name,
            account_number=req.account_number,
            holder_name=req.holder_name,
            category=req.category,
            note=req.note,
            case_id=req.case_id,
            data_mode=get_settings().mode,
            created_at=_now(),
        )
        self._banks.append(rec)
        return rec

    async def list_bank_accounts(self, case_id: str | None = None) -> list[BankAccountOut]:
        items = self._banks
        if case_id is not None:
            items = [b for b in items if b.case_id == case_id]
        return list(items)

    async def add_crypto_tx(self, req: AddCryptoTxRequest) -> CryptoTxOut:
        rec = CryptoTxOut(
            id=f"ctx_{uuid.uuid4().hex[:12]}",
            tx_hash=_mint_tx_hash(req),
            from_addr=req.from_addr,
            to_addr=req.to_addr,
            value=req.value,
            chain=req.chain,
            ts=req.ts,
            category=req.category,
            note=req.note,
            case_id=req.case_id,
            data_mode=get_settings().mode,
            created_at=_now(),
        )
        self._txs.append(rec)
        return rec

    async def list_crypto_transfers(self, case_id: str | None = None) -> list[CryptoTxOut]:
        items = self._txs
        if case_id is not None:
            items = [t for t in items if t.case_id == case_id]
        return list(items)

    def reset(self) -> None:
        self._banks.clear()
        self._txs.clear()


@lru_cache
def _memory_repository() -> InMemoryCaseDataRepository:
    """Process-wide singleton (mirrors get_settings() caching)."""
    return InMemoryCaseDataRepository()


# --------------------------------------------------------------------------- #
# Postgres (RLS-scoped)
# --------------------------------------------------------------------------- #


def _bank_out(row: BankAccountRecord) -> BankAccountOut:
    return BankAccountOut(
        id=str(row.id),
        bank_name=row.bank_name,
        account_number=row.account_number,
        holder_name=row.holder_name,
        category=row.category,  # type: ignore[arg-type]
        note=row.note,
        case_id=row.case_id,
        data_mode=row.data_mode,  # type: ignore[arg-type]
        created_at=row.created_at,
    )


def _tx_out(row: CryptoTransferRecord) -> CryptoTxOut:
    return CryptoTxOut(
        id=str(row.id),
        tx_hash=row.tx_hash,
        from_addr=row.from_addr,
        to_addr=row.to_addr,
        value=float(row.value),
        chain=row.chain,
        ts=row.ts,
        category=row.category,  # type: ignore[arg-type]
        note=row.note,
        case_id=row.case_id,
        data_mode=row.data_mode,  # type: ignore[arg-type]
        created_at=row.created_at,
    )


class PostgresCaseDataRepository:
    """Postgres impl — RLS-scoped by an already-open ``AsyncSession``
    (``app.current_agency`` set by the caller). Every query ALSO filters by
    ``agency_id`` explicitly (defense in depth), matching the intel repos."""

    def __init__(self, session: AsyncSession, *, agency_id: uuid.UUID, data_mode: str) -> None:
        self._session = session
        self._agency_id = agency_id
        self._data_mode = data_mode

    async def add_bank_account(self, req: AddBankAccountRequest) -> BankAccountOut:
        row = BankAccountRecord(
            id=uuid.uuid4(),
            agency_id=self._agency_id,
            bank_name=req.bank_name,
            account_number=req.account_number,
            holder_name=req.holder_name,
            category=req.category,
            note=req.note,
            case_id=req.case_id,
            data_mode=self._data_mode,
            created_at=_now(),
        )
        self._session.add(row)
        await self._session.flush()
        return _bank_out(row)

    async def list_bank_accounts(self, case_id: str | None = None) -> list[BankAccountOut]:
        stmt = select(BankAccountRecord).where(BankAccountRecord.agency_id == self._agency_id)
        if case_id is not None:
            stmt = stmt.where(BankAccountRecord.case_id == case_id)
        stmt = stmt.order_by(BankAccountRecord.created_at)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_bank_out(r) for r in rows]

    async def add_crypto_tx(self, req: AddCryptoTxRequest) -> CryptoTxOut:
        row = CryptoTransferRecord(
            id=uuid.uuid4(),
            agency_id=self._agency_id,
            tx_hash=_mint_tx_hash(req),
            from_addr=req.from_addr,
            to_addr=req.to_addr,
            value=req.value,
            chain=req.chain,
            ts=req.ts,
            category=req.category,
            note=req.note,
            case_id=req.case_id,
            data_mode=self._data_mode,
            created_at=_now(),
        )
        self._session.add(row)
        await self._session.flush()
        return _tx_out(row)

    async def list_crypto_transfers(self, case_id: str | None = None) -> list[CryptoTxOut]:
        stmt = select(CryptoTransferRecord).where(
            CryptoTransferRecord.agency_id == self._agency_id
        )
        if case_id is not None:
            stmt = stmt.where(CryptoTransferRecord.case_id == case_id)
        stmt = stmt.order_by(CryptoTransferRecord.ts)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_tx_out(r) for r in rows]

    def reset(self) -> None:
        raise NotImplementedError("reset() is a memory-only test hook.")


async def get_casedata_repository(
    session: AsyncSession | None = Depends(get_optional_tenant_session),
    auth: AuthContext | None = Depends(_get_optional_current_user),
) -> CaseDataRepository:
    """FastAPI dependency — memory singleton (POC) or a per-request
    RLS-scoped Postgres repo (``ITTU_PERSISTENCE=postgres``). Mirrors
    ``get_infiltrate_repository``: memory needs no auth, so read routes that
    add this dependency keep working unauthenticated in POC."""
    settings = get_settings()
    if settings.persistence != "postgres":
        return _memory_repository()
    if session is None or auth is None:  # pragma: no cover - get_optional_tenant_session 401s first
        raise RuntimeError("postgres persistence requires an authenticated, RLS-scoped session")
    return PostgresCaseDataRepository(session, agency_id=auth.agency.id, data_mode=settings.mode)


def reset_stores() -> None:
    """Sync test hook — resets the in-memory singleton (see infiltrate.reset_stores)."""
    _memory_repository().reset()
