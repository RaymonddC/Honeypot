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

import uuid
from datetime import datetime, timezone
from typing import Literal, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, Field

# Importing app.workers sets the Dramatiq Redis broker before @actor binds.
import dramatiq

from app import workers  # noqa: F401  (broker side-effect)
from app.core.adapters import register
from app.core.config import Mode, Settings

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
    status: Literal["mock", "queued", "sent", "failed"]
    data_mode: Mode = "poc"
    sent_at: datetime | None = None
    payload: dict = Field(default_factory=dict)


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

        sent_at = datetime.now(timezone.utc)
        try:
            async with httpx.AsyncClient(timeout=_WEBHOOK_TIMEOUT_SECONDS) as client:
                resp = await client.post(url, json=packet)
            status: Literal["sent", "failed"] = "sent" if resp.is_success else "failed"
        except httpx.HTTPError:
            status = "failed"

        return NotificationOut(
            id=f"ntf_{uuid.uuid4().hex[:12]}",
            action_id=packet.get("action_id", ""),
            case_id=packet.get("case_id", ""),
            target_agency=packet.get("agency", "unknown"),
            agency_type=packet.get("agency_type", "regulator"),
            channel=self.channel,
            status=status,
            data_mode=self.data_mode,
            sent_at=sent_at,
            payload={k: v for k, v in packet.items() if k not in ("agency", "agency_type")},
        )


# --------------------------------------------------------------------------- #
# Dramatiq dispatch actor (stub — LIVE delivery with retries goes here)
# --------------------------------------------------------------------------- #


@dramatiq.actor(max_retries=3)
def dispatch_notifications(action_id: str) -> None:
    """LIVE-mode delivery worker: pick up an action bundle and dispatch each
    routing target through the real channels, with retries + status tracking.

    POC never enqueues this actor — dispatch is synchronous via the mock sink.
    """
