"""HONEYPOT OPS API models — the number pool + dial campaigns
(docs/Voice-Honeypot-Outbound.md §3/§6).

Two operator-facing record types:
``HoneypotNumberOut`` (a Twilio number we dial FROM — *registered*, never
provisioned by us: design decision §9) and ``DialCampaignOut`` (one uploaded
batch of numbers to work through, with per-status target counts).

Phone numbers are E.164-validated at the edge (``normalize_e164``) so a bad
paste never reaches the dialer — a malformed number would fail at Twilio, mid
campaign, with no operator feedback.
"""

import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.core.config import Mode

NumberStatus = Literal["active", "retired", "rate_limited"]
CampaignStatus = Literal["draft", "running", "paused", "completed"]
TargetStatus = Literal["queued", "dialing", "no_answer", "engaged", "failed"]

# E.164: a leading '+', a non-zero country code, then up to 14 more digits.
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_e164(raw: str) -> str | None:
    """Normalize a pasted phone number to E.164, or ``None`` if unusable.

    Tolerates the separators humans actually paste (spaces, dashes, dots,
    parens) and the ``00`` international prefix, because a dial list is
    copy-pasted from spreadsheets and victim reports — not typed carefully.
    A bare Indonesian ``08...`` is deliberately NOT auto-prefixed: guessing the
    country would silently dial the wrong number.
    """
    cleaned = re.sub(r"[\s\-().]", "", (raw or "").strip())
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
    if not cleaned.startswith("+"):
        return None
    return cleaned if _E164.match(cleaned) else None


# --------------------------------------------------------------------------- #
# Numbers (the pool we dial FROM)
# --------------------------------------------------------------------------- #


class AddNumberRequest(BaseModel):
    """Register a Twilio number already bought/configured in the console."""

    phone_number: str = Field(min_length=8, max_length=20)
    twilio_sid: str | None = Field(default=None, max_length=64)
    label: str = Field(default="", max_length=120)

    @field_validator("phone_number")
    @classmethod
    def _e164(cls, v: str) -> str:
        norm = normalize_e164(v)
        if norm is None:
            raise ValueError("phone_number must be E.164, e.g. +6281234567890")
        return norm


class UpdateNumberRequest(BaseModel):
    """Retire / re-label a pool number. Omitted fields are left unchanged."""

    label: str | None = Field(default=None, max_length=120)
    status: NumberStatus | None = None


class HoneypotNumberOut(BaseModel):
    id: str
    phone_number: str
    twilio_sid: str | None = None
    label: str = ""
    status: NumberStatus = "active"
    data_mode: Mode = "poc"
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Campaigns (a batch of numbers to dial)
# --------------------------------------------------------------------------- #


class CreateCampaignRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    # Optional: pre-attach every call in this batch to one case (spec §5 step 1).
    case_id: str | None = None
    # Self-imposed dial pacing; Twilio's per-account concurrency is the hard cap.
    pacing_per_minute: int = Field(default=6, ge=1, le=60)


class DialCampaignOut(BaseModel):
    id: str
    name: str
    case_id: str | None = None
    status: CampaignStatus = "draft"
    pacing_per_minute: int = 6
    data_mode: Mode = "poc"
    created_at: datetime
    # Per-status target counts (queued/dialing/engaged/no_answer/failed) —
    # only the statuses actually present are included.
    counts: dict[str, int] = Field(default_factory=dict)
    target_count: int = 0


class UploadTargetsRequest(BaseModel):
    """Bulk-add numbers to a campaign — JSON array, pasted text, or both.

    ``text`` accepts whatever an operator pastes: one number per line, or CSV
    where the number is the FIRST field (the common shape of an exported
    report). Both inputs are merged, normalized, and deduped together.
    """

    numbers: list[str] = Field(default_factory=list)
    text: str = Field(default="", max_length=200_000)


class RejectedNumber(BaseModel):
    """One input row that did not become a target, and why."""

    value: str
    reason: Literal["invalid", "duplicate_in_upload", "already_in_campaign"]


class UploadTargetsResult(BaseModel):
    """Per-row outcome — a bad paste never fails the whole upload (spec §6)."""

    added: int
    rejected: list[RejectedNumber] = Field(default_factory=list)
    targets: list["DialTargetOut"] = Field(default_factory=list)


class DialTargetOut(BaseModel):
    id: str
    campaign_id: str
    phone_number: str
    status: TargetStatus = "queued"
    attempt_count: int = 0
    last_error: str | None = None
    session_id: str | None = None
    data_mode: Mode = "poc"
    created_at: datetime
    updated_at: datetime


UploadTargetsResult.model_rebuild()
