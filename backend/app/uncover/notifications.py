"""UNCOVER Notification Hub — routing table + POC mock sink + Dramatiq stub.

Routing: crime_type + entity types → target agencies + document types
(docs/UNCOVER-Design.md §4). A flagged mule *bank account* routes a freeze
request to the holding **bank**; a flagged *deposit wallet* routes a
freeze/flag to the **exchange**; **PPATK** receives the STR (goAML);
**OJK/Polri** receive case alerts.

POC/LIVE via the adapter registry (``("notification", mode)``):
- POC ``MockNotificationSink`` — records the packet, ``status="mock"``,
  nothing leaves the system ("would dispatch to …").
- LIVE ``LiveNotificationSink`` — Phase-5 stub; fails loudly, never silently.

Delivery in LIVE runs through the ``dispatch_notifications`` Dramatiq actor
(retries, status tracking); POC dispatch is synchronous + in-memory.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Literal, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, Field

import dramatiq

# Sets the Dramatiq Redis broker before the @actor below binds to it. This used
# to import app.workers for the same side effect, but that package now imports
# the actor modules (so `dramatiq app.workers` registers them all) — importing
# it from here would be a cycle. app.core.broker is a leaf with no such risk.
from app.core import broker as _broker  # noqa: F401
from app.core.adapters import register
from app.core.config import Mode, Settings, get_settings

_log = logging.getLogger("uvicorn.error")

AgencyType = Literal["bank", "exchange", "regulator", "police"]

# Agencies alerted per crime type (in addition to entity-driven bank/exchange
# freeze targets and the always-on PPATK STR route).
CRIME_ALERT_ROUTES: dict[str, list[str]] = {
    "investment": ["ojk", "polri"],       # securities/investment fraud → OJK + police
    "judol_deposit": ["polri"],           # online gambling → police (+ Kominfo later)
    "crypto_phishing": ["polri"],
    "romance": ["polri"],
}

AGENCY_DIRECTORY: dict[str, dict] = {
    "ppatk": {"agency": "PPATK", "agency_type": "regulator", "channel": "goaml"},
    "ojk": {"agency": "OJK", "agency_type": "regulator", "channel": "webhook"},
    "polri": {"agency": "Polri — Dittipideksus", "agency_type": "police", "channel": "webhook"},
}

# POC: the fixture cash-out exchange (chain fixtures tag the Indodax hot wallet).
DEFAULT_EXCHANGE = "Indodax"


class RoutingTarget(BaseModel):
    """One planned dispatch: which agency gets which document, and why."""

    agency: str
    agency_type: AgencyType
    channel: str                       # iasc | goaml | webhook | email
    document_type: str                 # account_blocking | str_report | summary | alert
    reason: str


class NotificationOut(BaseModel):
    """One dispatch record (action.notifications row shape)."""

    id: str
    action_id: str
    case_id: str
    target_agency: str
    agency_type: AgencyType
    channel: str
    status: Literal["mock", "queued", "sending", "sent", "failed"]
    data_mode: Mode = "poc"
    sent_at: datetime | None = None
    payload: dict = Field(default_factory=dict)
    # --- Delivery lifecycle (C1) ------------------------------------------- #
    # Stable token echoed to the recipient so an at-least-once retry never
    # double-actions a freeze/STR at the agency (survives across attempts).
    idempotency_key: str | None = None
    attempt_count: int = 0             # delivery attempts made (0 = mock/untried)
    last_error: str | None = None      # last failure reason (http_5xx / transport)


def new_idempotency_key() -> str:
    """A stable per-notification idempotency token (issued once, reused on retry)."""
    return f"idem_{uuid.uuid4().hex}"


def route_targets(
    crime_type: str,
    accounts: list,               # AccountTarget-like (bank_name, account_number, role)
    wallets: list,                # WalletTarget-like (address)
    outputs: list[str],
) -> list[RoutingTarget]:
    """The routing table: crime/entity types → agencies + document types.

    ``outputs`` gates the plan — a bundle without ``freeze`` plans no bank/
    exchange freeze targets; without ``ltkm`` no PPATK STR; without ``alert``
    no OJK/Polri alert.
    """
    plan: list[RoutingTarget] = []

    if "freeze" in outputs:
        # Every distinct holding bank gets the freeze request for its accounts.
        by_bank: dict[str, list[str]] = {}
        for a in accounts:
            by_bank.setdefault(a.bank_name, []).append(a.account_number)
        for bank, numbers in by_bank.items():
            plan.append(RoutingTarget(
                agency=f"Bank {bank}", agency_type="bank", channel="iasc",
                document_type="account_blocking",
                reason=f"holds flagged account(s): {', '.join(numbers)}",
            ))
        if wallets:
            plan.append(RoutingTarget(
                agency=f"Exchange ({DEFAULT_EXCHANGE})", agency_type="exchange",
                channel="webhook", document_type="account_blocking",
                reason=f"freeze/flag {len(wallets)} deposit wallet(s) at the exchange",
            ))

    if "ltkm" in outputs:
        d = AGENCY_DIRECTORY["ppatk"]
        plan.append(RoutingTarget(
            **d, document_type="str_report",
            reason="LTKM/STR draft (goAML) — suspicious-transaction report",
        ))

    if "alert" in outputs:
        for key in CRIME_ALERT_ROUTES.get(crime_type, ["polri"]):
            d = AGENCY_DIRECTORY[key]
            plan.append(RoutingTarget(
                **d, document_type="alert",
                reason=f"multi-agency case alert ({crime_type})",
            ))

    return plan


_WEBHOOK_TIMEOUT_SECONDS = 15.0


# --------------------------------------------------------------------------- #
# Webhook authenticity — HMAC-SHA256 signing (docs/Security-Evidence.md)
# --------------------------------------------------------------------------- #


def sign_payload(body: bytes, secret: str, timestamp: str) -> str:
    """HMAC-SHA256 over ``"{timestamp}.{body}"`` — the value the recipient
    recomputes to prove the packet is genuinely ITTU's (and, via the signed
    timestamp, isn't a replay). Stripe-style scheme; hex digest."""
    signed = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()


def signature_headers(body: bytes, secret: str, *, timestamp: str | None = None) -> dict[str, str]:
    """The auth headers for a signed dispatch: a versioned signature line plus
    the standalone timestamp the recipient uses for its replay window."""
    ts = timestamp or str(int(datetime.now(timezone.utc).timestamp()))
    return {
        "X-ITTU-Signature": f"t={ts},v1={sign_payload(body, secret, ts)}",
        "X-ITTU-Timestamp": ts,
    }


async def deliver_webhook(
    url: str,
    packet: dict,
    *,
    secret: str = "",
    idempotency_key: str | None = None,
    timeout: float = _WEBHOOK_TIMEOUT_SECONDS,
) -> tuple[Literal["sent", "failed"], str | None]:
    """POST ``packet`` to ``url`` and classify the outcome. Shared by the sync
    LIVE sink and the Dramatiq delivery actor so signing/idempotency behave
    identically on either path.

    - ``idempotency_key`` → ``X-ITTU-Idempotency-Key`` header (never the body,
      so the signed/verified bytes stay exactly the packet).
    - ``secret`` set → the body is serialized deterministically and HMAC-signed
      (``X-ITTU-Signature``); unset → a plain JSON POST (trusted internal
      endpoint only).

    Returns ``(status, error)``: ``("sent", None)`` on 2xx, else
    ``("failed", "http_<code>" | "transport_error:<Type>")`` — never raises, so
    callers own the retry decision.
    """
    headers: dict[str, str] = {}
    if idempotency_key:
        headers["X-ITTU-Idempotency-Key"] = idempotency_key
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            if secret:
                body = json.dumps(
                    packet, separators=(",", ":"), sort_keys=True, default=str
                ).encode()
                headers["Content-Type"] = "application/json"
                headers.update(signature_headers(body, secret))
                resp = await client.post(url, content=body, headers=headers)
            else:
                resp = await client.post(url, json=packet, headers=headers or None)
        if resp.is_success:
            return "sent", None
        return "failed", f"http_{resp.status_code}"
    except httpx.HTTPError as exc:
        return "failed", f"transport_error:{type(exc).__name__}"


# --------------------------------------------------------------------------- #
# Notification sink adapters (POC mock / LIVE stub)
# --------------------------------------------------------------------------- #


@runtime_checkable
class NotificationSink(Protocol):
    """Notification boundary (docs/Adapter-MODE-Framework.md)."""

    data_mode: Mode

    async def dispatch(self, packet: dict) -> NotificationOut: ...


@register("notification", "poc")
class MockNotificationSink:
    """POC mock sink: records the packet, status='mock', nothing leaves."""

    data_mode: Mode = "poc"

    # Class-level record of everything "sent" (inspectable in demos + tests).
    sent: list[NotificationOut] = []

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings

    async def dispatch(self, packet: dict) -> NotificationOut:
        note = NotificationOut(
            id=f"ntf_{uuid.uuid4().hex[:12]}",
            action_id=packet.get("action_id", ""),
            case_id=packet.get("case_id", ""),
            target_agency=packet.get("agency", "unknown"),
            agency_type=packet.get("agency_type", "regulator"),
            channel=packet.get("channel", "mock"),
            status="mock",
            data_mode=self.data_mode,
            sent_at=datetime.now(timezone.utc),
            idempotency_key=packet.get("idempotency_key") or new_idempotency_key(),
            attempt_count=0,  # mock never leaves the system — no real delivery attempt
            payload={
                **{k: v for k, v in packet.items() if k not in ("agency", "agency_type")},
                "note": f"POC mock sink — would dispatch to {packet.get('agency')} "
                        f"via {packet.get('channel')}",
            },
        )
        MockNotificationSink.sent.append(note)
        return note

    @classmethod
    def reset(cls) -> None:  # test hook
        cls.sent.clear()


@register("notification", "live")
class LiveNotificationSink:
    """LIVE: operator-owned webhook dispatch (+ goAML/IASC integrations, Phase-5).

    Today's wired channel is a generic webhook: ``ITTU_NOTIFICATION_WEBHOOK_URL``
    receives every dispatch packet as a JSON POST — no third-party account
    needed, the operator points it at their own endpoint (their own goAML
    bridge, a Slack/Teams incoming webhook, an internal case-management
    ingest, etc.). Without a configured URL this fails loudly — a LIVE
    deployment must never silently degrade to a mock (Adapter-MODE
    principle #3).
    """

    data_mode: Mode = "live"
    channel = "webhook"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def dispatch(self, packet: dict) -> NotificationOut:
        url = self._settings.notification_webhook_url
        if not url:
            raise NotImplementedError(
                "LIVE notification dispatch has no channel configured: set "
                "ITTU_NOTIFICATION_WEBHOOK_URL to the operator's webhook endpoint "
                "(goAML bridge / Slack / case-management ingest), or run UNCOVER "
                "in POC mode (ITTU_MODE=poc)."
            )

        idem = packet.get("idempotency_key") or new_idempotency_key()
        sent_at = datetime.now(timezone.utc)
        status, error = await deliver_webhook(
            url, packet,
            secret=self._settings.notification_webhook_secret,
            idempotency_key=idem,
            timeout=self._settings.notification_webhook_timeout_seconds,
        )

        return NotificationOut(
            id=f"ntf_{uuid.uuid4().hex[:12]}",
            action_id=packet.get("action_id", ""),
            case_id=packet.get("case_id", ""),
            target_agency=packet.get("agency", "unknown"),
            agency_type=packet.get("agency_type", "regulator"),
            channel=self.channel,
            status=status,
            data_mode=self.data_mode,
            sent_at=sent_at if status == "sent" else None,
            idempotency_key=idem,
            attempt_count=1,
            last_error=error,
            payload={k: v for k, v in packet.items() if k not in ("agency", "agency_type")},
        )


# --------------------------------------------------------------------------- #
# Dramatiq dispatch actor — durable LIVE delivery (retries + status tracking)
# --------------------------------------------------------------------------- #


class NotificationDeliveryError(Exception):
    """Raised to hand a failed attempt back to Dramatiq for retry/backoff."""


# The worker-side sessionmaker (privileged/owning role, no RLS scope) lives in
# app.core.db so the notification dispatcher and the outbound dialer resolve it
# identically — see worker_session() for why a system actor connects
# that way.
from app.core.db import worker_session as _worker_session  # noqa: E402


async def _deliver_one(notification_public_id: str) -> None:
    """Load one queued notification, POST it (signed), and record the outcome.

    Idempotent on ``sent`` (a re-run no-ops), so at-least-once redelivery is
    safe. On failure it records ``last_error``/``attempt_count`` and either
    re-queues + raises (→ Dramatiq backoff) or, once the retry budget is spent,
    settles the row as ``failed`` and returns without raising."""
    from sqlalchemy import select

    from app.action.models import Notification as NotificationModel

    settings = get_settings()
    async with _worker_session() as session:
        # 1) claim: queued → sending, count the attempt
        async with session.begin():
            row = (
                await session.execute(
                    select(NotificationModel).where(
                        NotificationModel.public_id == notification_public_id
                    )
                )
            ).scalar_one_or_none()
            if row is None or row.status == "sent":
                return  # unknown or already delivered — nothing to do
            # Mode guard. This actor runs as the OWNING role (see worker_session),
            # which bypasses the mode RLS predicate from migration 20260823_18 as
            # surely as it bypasses the agency one — so nothing but this line
            # stops a POC row being dispatched to a real agency's webhook, or a
            # LIVE row being handled by a deployment that has since flipped to
            # POC. Claimed by public_id alone, so the row is NOT guaranteed to
            # belong to this deployment's evidentiary universe; check, don't
            # assume. Settled `failed` rather than left queued: a row that can
            # never legitimately be sent here must not be retried forever.
            if row.data_mode != settings.mode:
                row.status = "failed"
                row.last_error = (
                    f"mode mismatch: notification is data_mode={row.data_mode!r} but "
                    f"this deployment runs ITTU_MODE={settings.mode!r} — refusing to "
                    "dispatch across the POC/LIVE boundary"
                )
                _log.error(
                    "notification %s: REFUSED, data_mode=%s but deployment mode=%s",
                    notification_public_id, row.data_mode, settings.mode,
                )
                return
            row.status = "sending"
            row.attempt_count = (row.attempt_count or 0) + 1
            attempt = row.attempt_count
            packet = {
                **(row.payload or {}),
                "agency": row.target_agency,
                "agency_type": row.agency_type,
            }
            idem = row.idempotency_key

        # 2) deliver OFF the transaction (network I/O must not hold a row lock)
        status, error = await deliver_webhook(
            settings.notification_webhook_url, packet,
            secret=settings.notification_webhook_secret,
            idempotency_key=idem,
            timeout=settings.notification_webhook_timeout_seconds,
        )

        # 3) settle
        retry = False
        async with session.begin():
            row = (
                await session.execute(
                    select(NotificationModel).where(
                        NotificationModel.public_id == notification_public_id
                    )
                )
            ).scalar_one()
            row.last_error = error
            if status == "sent":
                row.status = "sent"
                row.sent_at = datetime.now(timezone.utc)
            elif attempt >= settings.notification_max_retries:
                row.status = "failed"  # budget spent — settle, don't retry
            else:
                row.status = "queued"
                retry = True

    if retry:
        raise NotificationDeliveryError(error or "delivery failed")


@dramatiq.actor(
    max_retries=get_settings().notification_max_retries,
    min_backoff=get_settings().notification_retry_backoff_ms,
)
def dispatch_notifications(notification_public_id: str) -> None:
    """LIVE-mode delivery worker (one notification per message): POST the
    queued packet through the real webhook channel, signed + idempotent, with
    Dramatiq retries + backoff and durable status tracking on the row.

    Enqueued by ``service.dispatch_bundle`` only when
    ``ITTU_NOTIFICATION_DELIVERY=worker`` (LIVE + Postgres). POC never enqueues
    this — dispatch is synchronous via the mock sink; the sync LIVE path POSTs
    inline in the request.
    """
    asyncio.run(_deliver_one(notification_public_id))
