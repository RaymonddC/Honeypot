"""CASES API models — the investigation case file.

Stages mirror how a financial-crime case is actually handled (docs: proposal
Solution-Approach): intake → freeze → trace → takedown → report → recovery →
closed. ``id`` is the case's UUID string; ``case_id`` on other records points
here.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import Mode

CaseStage = Literal[
    "intake",      # 1. report / proactive intel in
    "freeze",      # 2. race to freeze receiving accounts
    "trace",       # 3. follow the money (fiat ↔ crypto)
    "takedown",    # 4. attribute + score the wallet network
    "report",      # 5. package evidence + file STR/LTKM
    "recovery",    # 6. recover funds
    "closed",      # 7. done
]
CASE_STAGES: list[str] = list(CaseStage.__args__)  # type: ignore[attr-defined]

CaseStatus = Literal["open", "active", "closed", "archived"]


class CreateCaseRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    crime_type: str | None = Field(default=None, max_length=64)
    summary: str | None = Field(default=None, max_length=2000)
    stage: CaseStage = "intake"


class UpdateCaseRequest(BaseModel):
    """Partial update — any omitted field is left unchanged."""

    title: str | None = Field(default=None, min_length=1, max_length=160)
    crime_type: str | None = Field(default=None, max_length=64)
    summary: str | None = Field(default=None, max_length=2000)
    stage: CaseStage | None = None
    status: CaseStatus | None = None


class CaseOut(BaseModel):
    id: str
    title: str
    status: CaseStatus = "open"
    stage: CaseStage = "intake"
    crime_type: str | None = None
    summary: str | None = None
    data_mode: Mode = "poc"
    created_at: datetime
    updated_at: datetime


class CaseSessionSummary(BaseModel):
    """A honeypot session attached to the case (rollup view)."""

    id: str
    channel: str
    # text|voice — lets the case view tell a phone call apart from a chat
    # without guessing from `channel` (pstn/wa_call vs telegram/whatsapp).
    channel_type: str = "text"
    channel_ref: str
    crime_type: str | None = None
    status: str
    entity_count: int
    started_at: datetime


class CaseDocumentSummary(BaseModel):
    """An UNCOVER action bundle attached to the case (rollup view)."""

    id: str
    status: str
    crime_type: str
    document_count: int
    created_at: datetime
