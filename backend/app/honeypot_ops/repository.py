"""HONEYPOT OPS persistence — memory (POC) + Postgres (RLS) dual, selected by
``settings.persistence``. Same shape/rationale as CASEDATA's repository
(docs/Persistence-Plan.md): MODE picks external adapters, persistence picks
where state lives — orthogonal axes, so this does NOT go through the adapter
registry.

Scope is CRUD only (docs/Voice-Honeypot-Outbound.md phase 3): nothing here
dials. ``start``/``pause`` move a campaign's status; enqueueing the
``dial_target`` actor is phase 4.
"""

import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Protocol, runtime_checkable

from fastapi import Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthContext
from app.core.auth import get_optional_current_user as _get_optional_current_user
from app.core.config import get_settings
from app.core.db import get_optional_tenant_session
from app.honeypot_ops.models import DialCampaign, DialTarget, HoneypotNumber
from app.honeypot_ops.schemas import (
    AddNumberRequest,
    CreateCampaignRequest,
    DialCampaignOut,
    DialTargetOut,
    HoneypotNumberOut,
    RejectedNumber,
    UpdateNumberRequest,
    UploadTargetsResult,
    normalize_e164,
)


@runtime_checkable
class HoneypotOpsRepository(Protocol):
    """Storage surface for the number pool + dial campaigns."""

    async def add_number(self, req: AddNumberRequest) -> HoneypotNumberOut | None: ...
    async def list_numbers(self) -> list[HoneypotNumberOut]: ...
    async def update_number(
        self, number_id: str, req: UpdateNumberRequest
    ) -> HoneypotNumberOut | None: ...

    async def create_campaign(self, req: CreateCampaignRequest) -> DialCampaignOut: ...
    async def list_campaigns(self) -> list[DialCampaignOut]: ...
    async def get_campaign(self, campaign_id: str) -> DialCampaignOut | None: ...
    async def set_campaign_status(
        self, campaign_id: str, status: str
    ) -> DialCampaignOut | None: ...

    async def add_targets(
        self, campaign_id: str, raw_numbers: list[str]
    ) -> UploadTargetsResult | None: ...
    async def list_targets(self, campaign_id: str) -> list[DialTargetOut] | None: ...

    def reset(self) -> None:
        """Clear all state — memory-only test hook (see reset_stores)."""
        ...


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _dedupe_and_validate(
    raw_numbers: list[str], existing: set[str]
) -> tuple[list[str], list[RejectedNumber]]:
    """Split pasted input into (accepted E.164 numbers, per-row rejects).

    Shared by both repository impls so memory and Postgres report identical
    outcomes. Order is preserved so the operator sees results in paste order.
    """
    accepted: list[str] = []
    rejected: list[RejectedNumber] = []
    seen: set[str] = set()
    for raw in raw_numbers:
        norm = normalize_e164(raw)
        if norm is None:
            rejected.append(RejectedNumber(value=raw.strip()[:40], reason="invalid"))
        elif norm in seen:
            rejected.append(RejectedNumber(value=norm, reason="duplicate_in_upload"))
        elif norm in existing:
            rejected.append(RejectedNumber(value=norm, reason="already_in_campaign"))
        else:
            seen.add(norm)
            accepted.append(norm)
    return accepted, rejected


def _counts_of(statuses: list[str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in statuses:
        out[s] = out.get(s, 0) + 1
    return out


# --------------------------------------------------------------------------- #
# In-memory (POC)
# --------------------------------------------------------------------------- #


class InMemoryHoneypotOpsRepository:
    """POC impl — process-wide lists, async to satisfy the Protocol."""

    def __init__(self) -> None:
        self._numbers: list[HoneypotNumberOut] = []
        self._campaigns: list[DialCampaignOut] = []
        self._targets: list[DialTargetOut] = []

    # -- numbers ----------------------------------------------------------- #

    async def add_number(self, req: AddNumberRequest) -> HoneypotNumberOut | None:
        if any(n.phone_number == req.phone_number for n in self._numbers):
            return None  # a physical number can only be registered once
        rec = HoneypotNumberOut(
            id=f"num_{uuid.uuid4().hex[:12]}",
            phone_number=req.phone_number,
            twilio_sid=req.twilio_sid,
            label=req.label,
            status="active",
            data_mode=get_settings().mode,
            created_at=_now(),
            updated_at=_now(),
        )
        self._numbers.append(rec)
        return rec

    async def list_numbers(self) -> list[HoneypotNumberOut]:
        return list(self._numbers)

    async def update_number(
        self, number_id: str, req: UpdateNumberRequest
    ) -> HoneypotNumberOut | None:
        for i, n in enumerate(self._numbers):
            if n.id == number_id:
                data = n.model_dump()
                if req.label is not None:
                    data["label"] = req.label
                if req.status is not None:
                    data["status"] = req.status
                data["updated_at"] = _now()
                updated = HoneypotNumberOut(**data)
                self._numbers[i] = updated
                return updated
        return None

    # -- campaigns --------------------------------------------------------- #

    def _campaign_out(self, camp: DialCampaignOut) -> DialCampaignOut:
        """Re-project with live per-status target counts."""
        statuses = [t.status for t in self._targets if t.campaign_id == camp.id]
        return camp.model_copy(
            update={"counts": _counts_of(statuses), "target_count": len(statuses)}
        )

    async def create_campaign(self, req: CreateCampaignRequest) -> DialCampaignOut:
        rec = DialCampaignOut(
            id=f"camp_{uuid.uuid4().hex[:12]}",
            name=req.name,
            case_id=req.case_id,
            status="draft",
            pacing_per_minute=req.pacing_per_minute,
            data_mode=get_settings().mode,
            created_at=_now(),
        )
        self._campaigns.append(rec)
        return self._campaign_out(rec)

    async def list_campaigns(self) -> list[DialCampaignOut]:
        return [
            self._campaign_out(c)
            for c in sorted(self._campaigns, key=lambda c: c.created_at, reverse=True)
        ]

    async def get_campaign(self, campaign_id: str) -> DialCampaignOut | None:
        for c in self._campaigns:
            if c.id == campaign_id:
                return self._campaign_out(c)
        return None

    async def set_campaign_status(
        self, campaign_id: str, status: str
    ) -> DialCampaignOut | None:
        for i, c in enumerate(self._campaigns):
            if c.id == campaign_id:
                updated = c.model_copy(update={"status": status})
                self._campaigns[i] = updated
                return self._campaign_out(updated)
        return None

    # -- targets ----------------------------------------------------------- #

    async def add_targets(
        self, campaign_id: str, raw_numbers: list[str]
    ) -> UploadTargetsResult | None:
        camp = next((c for c in self._campaigns if c.id == campaign_id), None)
        if camp is None:
            return None
        existing = {t.phone_number for t in self._targets if t.campaign_id == campaign_id}
        accepted, rejected = _dedupe_and_validate(raw_numbers, existing)
        created: list[DialTargetOut] = []
        for num in accepted:
            rec = DialTargetOut(
                id=f"tgt_{uuid.uuid4().hex[:12]}",
                campaign_id=campaign_id,
                phone_number=num,
                status="queued",
                data_mode=camp.data_mode,
                created_at=_now(),
                updated_at=_now(),
            )
            self._targets.append(rec)
            created.append(rec)
        return UploadTargetsResult(
            added=len(created), rejected=rejected, targets=created
        )

    async def list_targets(self, campaign_id: str) -> list[DialTargetOut] | None:
        if not any(c.id == campaign_id for c in self._campaigns):
            return None
        return [t for t in self._targets if t.campaign_id == campaign_id]

    def reset(self) -> None:
        self._numbers.clear()
        self._campaigns.clear()
        self._targets.clear()


@lru_cache
def _memory_repository() -> InMemoryHoneypotOpsRepository:
    """Process-wide singleton (mirrors get_settings() caching)."""
    return InMemoryHoneypotOpsRepository()


# --------------------------------------------------------------------------- #
# Postgres (RLS-scoped)
# --------------------------------------------------------------------------- #


def _number_out(row: HoneypotNumber) -> HoneypotNumberOut:
    return HoneypotNumberOut(
        id=str(row.id),
        phone_number=row.phone_number,
        twilio_sid=row.twilio_sid,
        label=row.label,
        status=row.status,  # type: ignore[arg-type]
        data_mode=row.data_mode,  # type: ignore[arg-type]
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _campaign_out(
    row: DialCampaign, counts: dict[str, int] | None = None
) -> DialCampaignOut:
    counts = counts or {}
    return DialCampaignOut(
        id=row.public_id,
        name=row.name,
        case_id=str(row.case_id) if row.case_id else None,
        status=row.status,  # type: ignore[arg-type]
        pacing_per_minute=row.pacing_per_minute,
        data_mode=row.data_mode,  # type: ignore[arg-type]
        created_at=row.created_at,
        counts=counts,
        target_count=sum(counts.values()),
    )


def _target_out(row: DialTarget, campaign_public_id: str) -> DialTargetOut:
    return DialTargetOut(
        id=str(row.id),
        campaign_id=campaign_public_id,
        phone_number=row.phone_number,
        status=row.status,  # type: ignore[arg-type]
        attempt_count=row.attempt_count,
        last_error=row.last_error,
        session_id=str(row.session_id) if row.session_id else None,
        data_mode=row.data_mode,  # type: ignore[arg-type]
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class PostgresHoneypotOpsRepository:
    """Postgres impl — RLS-scoped by an already-open ``AsyncSession``
    (``app.current_agency`` set by the caller). Every query ALSO filters by
    ``agency_id`` explicitly (defense in depth), matching the casedata/intel
    repos. ``dial_targets`` has no ``agency_id`` of its own — it is always
    reached through its campaign, which IS agency-filtered."""

    def __init__(self, session: AsyncSession, *, agency_id: uuid.UUID, data_mode: str) -> None:
        self._session = session
        self._agency_id = agency_id
        self._data_mode = data_mode

    # -- numbers ----------------------------------------------------------- #

    async def add_number(self, req: AddNumberRequest) -> HoneypotNumberOut | None:
        # phone_number is globally unique — check before insert so a duplicate
        # is a clean 409 rather than an IntegrityError that poisons the tx.
        clash = (
            await self._session.execute(
                select(HoneypotNumber.id).where(
                    HoneypotNumber.phone_number == req.phone_number
                )
            )
        ).first()
        if clash is not None:
            return None
        row = HoneypotNumber(
            id=uuid.uuid4(),
            agency_id=self._agency_id,
            phone_number=req.phone_number,
            twilio_sid=req.twilio_sid,
            label=req.label,
            status="active",
            data_mode=self._data_mode,
            created_at=_now(),
            updated_at=_now(),
        )
        self._session.add(row)
        await self._session.flush()
        return _number_out(row)

    async def list_numbers(self) -> list[HoneypotNumberOut]:
        rows = (
            await self._session.execute(
                select(HoneypotNumber)
                .where(HoneypotNumber.agency_id == self._agency_id)
                .order_by(HoneypotNumber.created_at)
            )
        ).scalars().all()
        return [_number_out(r) for r in rows]

    async def _number_row(self, number_id: str) -> HoneypotNumber | None:
        try:
            nid = uuid.UUID(number_id)
        except ValueError:
            return None
        return (
            await self._session.execute(
                select(HoneypotNumber).where(
                    HoneypotNumber.id == nid,
                    HoneypotNumber.agency_id == self._agency_id,
                )
            )
        ).scalar_one_or_none()

    async def update_number(
        self, number_id: str, req: UpdateNumberRequest
    ) -> HoneypotNumberOut | None:
        row = await self._number_row(number_id)
        if row is None:
            return None
        if req.label is not None:
            row.label = req.label
        if req.status is not None:
            row.status = req.status
        row.updated_at = _now()
        await self._session.flush()
        return _number_out(row)

    # -- campaigns --------------------------------------------------------- #

    async def _campaign_row(self, campaign_id: str) -> DialCampaign | None:
        return (
            await self._session.execute(
                select(DialCampaign).where(
                    DialCampaign.public_id == campaign_id,
                    DialCampaign.agency_id == self._agency_id,
                )
            )
        ).scalar_one_or_none()

    async def _counts(self, campaign_uuid: uuid.UUID) -> dict[str, int]:
        rows = (
            await self._session.execute(
                select(DialTarget.status, func.count())
                .where(DialTarget.campaign_id == campaign_uuid)
                .group_by(DialTarget.status)
            )
        ).all()
        return {status: int(n) for status, n in rows}

    async def create_campaign(self, req: CreateCampaignRequest) -> DialCampaignOut:
        case_uuid: uuid.UUID | None = None
        if req.case_id:
            try:
                case_uuid = uuid.UUID(req.case_id)
            except ValueError:
                case_uuid = None  # advisory link only (no FK) — ignore junk
        row = DialCampaign(
            id=uuid.uuid4(),
            public_id=f"camp_{uuid.uuid4().hex[:12]}",
            agency_id=self._agency_id,
            name=req.name,
            case_id=case_uuid,
            status="draft",
            pacing_per_minute=req.pacing_per_minute,
            data_mode=self._data_mode,
            created_at=_now(),
        )
        self._session.add(row)
        await self._session.flush()
        return _campaign_out(row)

    async def list_campaigns(self) -> list[DialCampaignOut]:
        rows = (
            await self._session.execute(
                select(DialCampaign)
                .where(DialCampaign.agency_id == self._agency_id)
                .order_by(DialCampaign.created_at.desc())
            )
        ).scalars().all()
        return [_campaign_out(r, await self._counts(r.id)) for r in rows]

    async def get_campaign(self, campaign_id: str) -> DialCampaignOut | None:
        row = await self._campaign_row(campaign_id)
        if row is None:
            return None
        return _campaign_out(row, await self._counts(row.id))

    async def set_campaign_status(
        self, campaign_id: str, status: str
    ) -> DialCampaignOut | None:
        row = await self._campaign_row(campaign_id)
        if row is None:
            return None
        row.status = status
        await self._session.flush()
        return _campaign_out(row, await self._counts(row.id))

    # -- targets ----------------------------------------------------------- #

    async def add_targets(
        self, campaign_id: str, raw_numbers: list[str]
    ) -> UploadTargetsResult | None:
        camp = await self._campaign_row(campaign_id)
        if camp is None:
            return None
        existing = set(
            (
                await self._session.execute(
                    select(DialTarget.phone_number).where(
                        DialTarget.campaign_id == camp.id
                    )
                )
            ).scalars().all()
        )
        accepted, rejected = _dedupe_and_validate(raw_numbers, existing)
        created: list[DialTargetOut] = []
        for num in accepted:
            row = DialTarget(
                id=uuid.uuid4(),
                campaign_id=camp.id,
                phone_number=num,
                status="queued",
                attempt_count=0,
                data_mode=camp.data_mode,
                created_at=_now(),
                updated_at=_now(),
            )
            self._session.add(row)
            created.append(row)  # type: ignore[arg-type]
        await self._session.flush()
        return UploadTargetsResult(
            added=len(created),
            rejected=rejected,
            targets=[_target_out(r, camp.public_id) for r in created],  # type: ignore[arg-type]
        )

    async def list_targets(self, campaign_id: str) -> list[DialTargetOut] | None:
        camp = await self._campaign_row(campaign_id)
        if camp is None:
            return None
        rows = (
            await self._session.execute(
                select(DialTarget)
                .where(DialTarget.campaign_id == camp.id)
                .order_by(DialTarget.created_at)
            )
        ).scalars().all()
        return [_target_out(r, camp.public_id) for r in rows]

    def reset(self) -> None:
        raise NotImplementedError("reset() is a memory-only test hook.")


async def get_honeypot_ops_repository(
    session: AsyncSession | None = Depends(get_optional_tenant_session),
    auth: AuthContext | None = Depends(_get_optional_current_user),
) -> HoneypotOpsRepository:
    """FastAPI dependency — memory singleton (POC) or a per-request RLS-scoped
    Postgres repo (``ITTU_PERSISTENCE=postgres``). Mirrors
    ``get_casedata_repository``."""
    settings = get_settings()
    if settings.persistence != "postgres":
        return _memory_repository()
    if session is None or auth is None:  # pragma: no cover - get_optional_tenant_session 401s first
        raise RuntimeError("postgres persistence requires an authenticated, RLS-scoped session")
    return PostgresHoneypotOpsRepository(
        session, agency_id=auth.agency.id, data_mode=settings.mode
    )


def reset_stores() -> None:
    """Sync test hook — resets the in-memory singleton (see casedata.reset_stores)."""
    _memory_repository().reset()
