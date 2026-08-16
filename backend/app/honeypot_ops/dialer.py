"""Outbound dial worker — the ``dial_target`` Dramatiq actor
(docs/Voice-Honeypot-Outbound.md §4, phase 4).

Deliberately the same shape as the C1 notification dispatcher
(``app/uncover/notifications.py``): claim the row, do the work OFF the
transaction, settle the row, and hand a retryable failure back to Dramatiq.
Both are "a queued unit of outbound work an actor retries", so the durable
row-status pattern carries over unchanged.

**Nothing here dials for real.** The POC path SIMULATES an outcome; the LIVE
path fails loud, pointing at phase 5 (``PstnChannelAdapter`` + the media
bridge, ``Live-Voice-Calls.md``). That mirrors every other LIVE boundary in this
codebase — a missing LIVE implementation must never silently degrade into
something that looks like it worked, and here "silently working" would mean
placing real calls to real people.

The gate is the ROW's ``data_mode``, not ambient settings: a campaign created in
POC must stay simulated even if the server is later flipped to LIVE, because its
rows are already stamped as non-evidence.

Call log (§3.4/§3.5) — TWO records, written together, deliberately separate:

* ``honeypot.dial_attempts`` — one row for EVERY attempt, whatever happened.
  This is the CDR: "tried three times, no answer at 14:03 and 16:20, engaged at
  09:12". Requeue (§3.6) re-queues a settled target, so attempts accumulate.
* ``intel.scam_sessions``    — one row per *connected* attempt only, carrying the
  transcript, extracted intel, and custody chain, linked by ``dial_target_id``.

A no-answer gets an attempt row but NO session: it is not a conversation
(``ScamSession`` is "one engaged scammer conversation"), it has no transcript and
no intel, and the triage queue (§5) reads sessions as an analyst work queue —
filling it with silent attempts would make it a chore to work. But the attempt
still has to be recorded, because "never picks up" is itself intel about a
target; before ``dial_attempts`` existed that history collapsed into a bare
``attempt_count``.
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, timezone

import dramatiq
from sqlalchemy import select

# Imported for its side effect and BEFORE the @dramatiq.actor below: it sets the
# Redis broker, so this actor binds to the broker the worker actually reads.
# See app/core/broker.py for why the ordering matters.
from app.core import broker as _broker  # noqa: F401
from app.core.config import get_settings
from app.core.db import get_worker_sessionmaker
from app.honeypot_ops.models import DialAttempt, DialCampaign, DialTarget

_log = logging.getLogger("uvicorn.error")


class DialAttemptError(Exception):
    """Raised to hand a failed attempt back to Dramatiq for retry/backoff."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# POC simulation
# --------------------------------------------------------------------------- #


def simulate_outcome(phone_number: str, attempt: int) -> tuple[str, str | None, int]:
    """Deterministically pick a POC dial outcome → ``(status, error, seconds)``.

    Seeded by ``(phone_number, attempt)`` — a pure function of its inputs, so a
    demo replays identically and tests can assert exact outcomes without
    mocking randomness. Including ``attempt`` is what makes **Requeue**
    meaningful: re-dialing the same number rolls a *different* (but still fixed)
    result, so a no-answer can become an engaged call on the retry — which is
    the whole point of requeueing. Seeding on the number alone would freeze
    every target's fate forever.

    Distribution ≈ 60% engaged / 25% no answer / 15% carrier failure.
    """
    digest = hashlib.sha256(f"{phone_number}:{attempt}".encode()).digest()
    roll = digest[0] % 100
    if roll < 60:
        # 45–285s: long enough to look like a real engagement, varied per seed.
        return "engaged", None, 45 + (digest[1] % 240)
    if roll < 85:
        return "no_answer", None, 0
    return "failed", "simulated: carrier rejected the call", 0


# --------------------------------------------------------------------------- #
# The actor
# --------------------------------------------------------------------------- #


async def _dial_one(dial_target_id: str) -> None:
    """Dial one queued target, record the outcome, and log the call.

    Idempotent on an already-settled target (a redelivery no-ops), so
    at-least-once redelivery is safe. A ``failed`` attempt re-queues and raises
    (→ Dramatiq backoff) until the retry budget is spent, then settles as
    ``failed``; ``no_answer`` settles immediately — nobody picking up is an
    answer, and **Requeue** is the deliberate way to try again rather than the
    worker deciding on its own.
    """
    # Imported here so the module stays importable without the intel package
    # loaded (and to keep the actor's import cost off API startup).
    from app.intel.models import ScamSession

    settings = get_settings()
    sm = get_worker_sessionmaker()

    async with sm() as session:
        # 1) claim: queued → dialing, count the attempt
        async with session.begin():
            try:
                tid = uuid.UUID(dial_target_id)
            except ValueError:
                return  # not a real id — nothing to do
            row = (
                await session.execute(select(DialTarget).where(DialTarget.id == tid))
            ).scalar_one_or_none()
            if row is None or row.status != "queued":
                return  # unknown, already dialing, or already settled
            campaign = (
                await session.execute(
                    select(DialCampaign).where(DialCampaign.id == row.campaign_id)
                )
            ).scalar_one_or_none()
            if campaign is None:  # pragma: no cover - FK guarantees this
                return
            if campaign.status != "running":
                return  # paused/completed between enqueue and pickup — don't dial

            row.status = "dialing"
            row.attempt_count = (row.attempt_count or 0) + 1
            row.updated_at = _now()
            attempt = row.attempt_count
            phone = row.phone_number
            data_mode = row.data_mode
            agency_id = campaign.agency_id
            case_id = campaign.case_id

        # 2) place the call OFF the transaction (I/O must not hold a row lock)
        if data_mode == "live":
            # Fail loud, exactly like every other LIVE stub. Reaching here means
            # a LIVE campaign was started before the telephony bridge exists —
            # the row stays `dialing` and the operator gets a real error rather
            # than a silent no-op that looks like a placed call.
            raise NotImplementedError(
                "LIVE outbound dialing is not wired in this build: it requires the "
                "Twilio PstnChannelAdapter + WebSocket media bridge (phase 5, "
                "docs/Live-Voice-Calls.md), and dialing real reported numbers is "
                "gated on Polri authorization (docs/Voice-Honeypot-Outbound.md §0). "
                "Run the campaign in POC mode, where dialing is simulated."
            )

        outcome, error, duration = simulate_outcome(phone, attempt)

        # 3) settle the target, log the ATTEMPT (always), and the conversation
        #    (only when it connected)
        retry = False
        async with session.begin():
            row = (
                await session.execute(select(DialTarget).where(DialTarget.id == tid))
            ).scalar_one()
            row.last_error = error
            row.updated_at = _now()
            started = _now()
            session_row: ScamSession | None = None

            if outcome == "engaged":
                row.status = "engaged"
                session_row = ScamSession(
                    id=uuid.uuid4(),
                    public_id=f"sess_{uuid.uuid4().hex[:12]}",
                    # §5 step 1: a campaign pinned to a case attaches directly.
                    # Otherwise NULL → the triage queue (phase 6 matches/assigns).
                    case_id=case_id,
                    agency_id=agency_id,
                    channel_type="voice",
                    channel="pstn",
                    channel_ref=phone,
                    status="closed",  # the call is over (active|escalated|closed)
                    data_mode=data_mode,
                    started_at=started,
                    ended_at=started,
                    duration_seconds=duration,
                    # recording_url stays NULL — recording is deferred (§3.7).
                    disposition="engaged",
                    dial_target_id=row.id,
                )
                session.add(session_row)
                # The attempt row's FK needs the session's id to exist.
                await session.flush()
            elif outcome == "no_answer":
                row.status = "no_answer"
            elif attempt >= settings.dial_max_retries:
                row.status = "failed"  # budget spent — settle, don't retry
            else:
                row.status = "queued"
                retry = True

            # The CDR — written for engaged, no_answer AND failed alike, including
            # the failures that will be retried below. A retried attempt is still
            # an attempt: it occupied a line and told us something about the
            # target, so it earns a row. UNIQUE(target_id, attempt_no) keeps a
            # Dramatiq redelivery from double-logging the same one.
            session.add(
                DialAttempt(
                    id=uuid.uuid4(),
                    target_id=row.id,
                    attempt_no=attempt,
                    outcome=outcome,
                    error=error,
                    duration_seconds=duration,
                    session_id=session_row.id if session_row is not None else None,
                    data_mode=data_mode,
                    started_at=started,
                )
            )

    if retry:
        raise DialAttemptError(error or "dial failed")


@dramatiq.actor(
    max_retries=get_settings().dial_max_retries,
    min_backoff=get_settings().dial_retry_backoff_ms,
)
def dial_target(dial_target_id: str) -> None:
    """Place one outbound call for a queued dial target, paced + retried.

    Enqueued by ``POST /api/honeypot/campaigns/{id}/start`` when
    ``ITTU_DIAL_ENQUEUE_ON_START=true`` and persistence is Postgres (the actor
    reads the row cross-process). POC simulates the call; LIVE fails loud until
    phase 5 lands.
    """
    asyncio.run(_dial_one(dial_target_id))


def enqueue_campaign_targets(target_ids: list[str], *, pacing_per_minute: int) -> int:
    """Enqueue one ``dial_target`` message per id, spread out to honor pacing.

    Pacing is applied as a per-message ``delay`` rather than a rate-limited
    consumer: target *i* is scheduled ``i * (60/pacing)`` seconds out, so a
    100-number campaign at 6/min trickles over ~17 minutes instead of bursting
    into Twilio's per-account concurrency cap (which is the hard ceiling
    regardless). No extra infrastructure, and the schedule is visible in the
    queue rather than hidden in worker config.

    Returns the number of messages enqueued.
    """
    if not target_ids:
        return 0
    gap_ms = int(60_000 / max(1, pacing_per_minute))
    for i, tid in enumerate(target_ids):
        dial_target.send_with_options(args=(str(tid),), delay=i * gap_ms)
    _log.info(
        "dialer: enqueued %d target(s) at %d/min (%.1fs apart)",
        len(target_ids), pacing_per_minute, gap_ms / 1000,
    )
    return len(target_ids)
