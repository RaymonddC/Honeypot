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
# A settled attempt's result. No "queued"/"dialing" — an attempt row is only
# written once the attempt has an outcome.
AttemptOutcome = Literal["engaged", "no_answer", "failed"]

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
    """One input row that did not become a target, and why.

    ``already_in_campaign`` is not a dead end: the number IS in this campaign
    already, and calling it again is what **Requeue** (§3.6) is for. A duplicate
    target row is never created — two rows for one number would make the
    per-status counts meaningless ("2 no_answer" = two numbers, or one twice?)
    and break the "was this number called?" question the counts exist to answer.
    """

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
    # Dial attempts made so far. Requeue never resets this — it IS the retry
    # count ("tried 3 times"). The attempt-by-attempt log is DialAttemptOut
    # below; `status`/`last_error` here are only the LATEST outcome.
    attempt_count: int = 0
    last_error: str | None = None
    data_mode: Mode = "poc"
    created_at: datetime
    updated_at: datetime


class DialAttemptOut(BaseModel):
    """One row of the call log — a single dial attempt and what came of it.

    Written for EVERY outcome, including the ones nobody answered, so an
    investigator can reconstruct "tried three times: no answer at 14:03 and
    16:20, engaged at 09:12". ``session_id`` is set only when the call actually
    connected — that is the conversation (transcript + extracted intel) this
    attempt produced.
    """

    id: str
    target_id: str
    attempt_no: int
    outcome: AttemptOutcome
    error: str | None = None
    duration_seconds: int | None = None
    session_id: str | None = None
    data_mode: Mode = "poc"
    started_at: datetime


# Statuses a target can be requeued FROM. Deliberately excludes:
#   queued  — already waiting; requeueing is a no-op
#   dialing — a call is IN FLIGHT; requeueing would double-dial a real person
REQUEUEABLE: tuple[str, ...] = ("no_answer", "failed", "engaged")


class RequeueRequest(BaseModel):
    """Send finished targets back to ``queued`` so they are dialed again (§3.6).

    Either name specific ``target_ids``, or leave them empty to requeue every
    target in the campaign currently in one of ``statuses`` (the bulk
    "requeue all no-answers" case). ``engaged`` is requeueable but not a
    default: re-calling someone you already spoke to is a deliberate act.
    """

    target_ids: list[str] = Field(default_factory=list)
    statuses: list[Literal["no_answer", "failed", "engaged"]] = Field(
        default_factory=lambda: ["no_answer", "failed"]
    )


class RequeueResult(BaseModel):
    requeued: int
    # Targets skipped because they were queued/dialing — reported rather than
    # silently ignored, so "requeue all" never looks like it lost rows.
    skipped: int = 0
    targets: list["DialTargetOut"] = Field(default_factory=list)


UploadTargetsResult.model_rebuild()
RequeueResult.model_rebuild()


# --------------------------------------------------------------------------- #
# Triage (calls that landed without a case — §5)
# --------------------------------------------------------------------------- #


class TriageSessionOut(BaseModel):
    """One connected call waiting for an investigator to place it.

    A call reaches triage only when auto-linking found nothing (§5): the campaign
    wasn't pinned to a case, the dialed number is new, and nothing it produced
    matched a case already on file. That is deliberately a *frequent* outcome —
    linking is exact-match only, because a wrong auto-link silently contaminates
    a case file that may end up in court, while a wrong triage costs ten seconds.
    """

    id: str
    channel: str | None = None
    # The scammer's number — itself intel, and the thing an investigator
    # recognizes a call by.
    channel_ref: str | None = None
    crime_type: str | None = None
    status: str = "closed"
    disposition: str | None = None
    duration_seconds: int | None = None
    entity_count: int = 0
    # First thing the other side said, truncated — enough to tell a real
    # engagement from a wrong number without opening the transcript.
    preview: str | None = None
    data_mode: Mode = "poc"
    started_at: datetime


class AttachSessionRequest(BaseModel):
    """Attach a triaged call to a case that already exists."""

    case_id: str = Field(min_length=1)


class PromoteSessionRequest(BaseModel):
    """Open a NEW case for a triaged call.

    Every field is optional: omitted ones are prefilled from what the call
    already produced (crime type from the classifier, a title naming the number
    and date, a summary of the engagement). The investigator is confirming a
    judgement, not re-typing data the system already has.
    """

    title: str | None = Field(default=None, min_length=1, max_length=160)
    crime_type: str | None = Field(default=None, max_length=64)
    summary: str | None = Field(default=None, max_length=2000)


class PromoteSessionResult(BaseModel):
    """The case that was opened, plus the call now attached to it."""

    case: "CaseOut"
    session: TriageSessionOut


# Imported at the bottom: app.cases.schemas is a peer module and this is the one
# place honeypot_ops needs it (promote returns the case it opened).
from app.cases.schemas import CaseOut  # noqa: E402

PromoteSessionResult.model_rebuild()
