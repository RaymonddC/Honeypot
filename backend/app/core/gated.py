"""Capabilities that are switched off — and what it would take to switch each on.

Several parts of ITTU are built but not available: some because a product
decision withheld them, some because they need an authorisation nobody has yet.
Those are different reasons and they were previously recorded in different
places — a config comment here, an exception message there, a backlog line
somewhere else. A reader could not answer "what is off, and why" without
grepping.

This is that answer in one place. It is a **decision aid, not an enforcement
mechanism**: the guards live where they can actually refuse a request
(``require_crypto_enabled``, the dialer's LIVE branch). What this adds is the
reason, the blocker, and who can lift it — so "can we turn this on?" has an
answer that does not depend on who is in the room.

**The distinction that matters most here** is INBOUND versus OUTBOUND honeypot,
because they are not the same permission problem:

* **Inbound** — a scammer calls a number we published, and the agent answers. We
  are a *party to our own conversation*. No authority grants permission to
  answer your own phone.
* **Outbound** — we dial a reported number. That is contacting someone who has
  not contacted us: an operational act against a citizen, and the thing Polri
  authorisation is actually about.

A honeypot is passive by definition — something attractive is left out and the
attacker comes to it. The outbound dialer is the part that is not really a
honeypot, and it is where nearly all of the permission burden sits.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Blocker(str, Enum):
    """Why a capability is off. The label an operator needs, not a status code."""

    #: Someone decided not to ship it yet. Reversible by us, today.
    PRODUCT = "product_decision"
    #: Needs authorisation from a law-enforcement body.
    POLRI = "polri_authorization"
    #: Needs a data-sharing agreement with an institution.
    PARTNERSHIP = "institutional_partnership"
    #: Needs a regulator to accept our writes into their system.
    REGULATOR = "regulator_governance"
    #: Needs an account or credential we have not bought yet.
    CREDENTIAL = "credential"
    #: Built, but not proven against the real thing.
    UNVERIFIED = "unverified"


@dataclass(frozen=True)
class GatedFeature:
    key: str
    label: str
    #: What is actually withheld, in the words of someone deciding about it.
    what: str
    blocker: Blocker
    #: Who can lift it. "us" where no external party is involved — which is the
    #: most useful thing this registry surfaces, because it separates what we
    #: are waiting on from what we simply have not done.
    lifted_by: str
    #: The environment variable, where one exists.
    flag: str | None = None


GATED: tuple[GatedFeature, ...] = (
    GatedFeature(
        key="crypto",
        label="Crypto tracing (TAKEDOWN, and the crypto half of TRACE)",
        what=(
            "Wallet risk scoring, the transaction graph, and fiat→crypto bridge "
            "views. The underlying data is a PUBLIC ledger, so nothing external "
            "gates it — this is off by product decision only, and is one of the "
            "few capabilities that needs nobody's permission at all."
        ),
        blocker=Blocker.PRODUCT,
        lifted_by="us — set ITTU_CRYPTO_ENABLED=true",
        flag="ITTU_CRYPTO_ENABLED",
    ),
    GatedFeature(
        key="honeypot_inbound",
        label="Inbound honeypot — the agent answers a call it did not place",
        what=(
            "A scammer calls a number we published and the agent engages, "
            "extracting accounts, wallets and syndicate structure. Available: we "
            "are a party to our own conversation, and no authority grants "
            "permission to answer your own phone. Needs a Twilio number and the "
            "media bridge, NOT an authorisation."
        ),
        blocker=Blocker.CREDENTIAL,
        lifted_by="us — a Twilio account and the phase-5 media bridge",
        flag="ITTU_TWILIO_ACCOUNT_SID",
    ),
    GatedFeature(
        key="honeypot_outbound",
        label="Outbound dialing — the agent calls a reported number",
        what=(
            "Dial campaigns against reported scam numbers. This is contact with "
            "someone who has not contacted us, which is an operational act "
            "against a citizen — the permission burden of the whole product sits "
            "almost entirely here. The dialer already refuses in LIVE and says so."
        ),
        blocker=Blocker.POLRI,
        lifted_by="Polri — written authorisation for live suspect engagement",
        flag="ITTU_DIAL_ENQUEUE_ON_START",
    ),
    GatedFeature(
        key="telegram_channel",
        label="Telegram / WhatsApp text channel (A2)",
        what=(
            "Engaging a scammer over a text channel. Same distinction as voice: "
            "replying to someone who messaged us differs from initiating."
        ),
        blocker=Blocker.POLRI,
        lifted_by="Polri — for anything the agent initiates",
        flag=None,
    ),
    GatedFeature(
        key="institutional_feeds",
        label="Live fiat feed (C2) and address tags (A3)",
        what=(
            "Real bank/QRIS transaction data and sanctions/abuse tag feeds. The "
            "fiat side runs on synthetic data until a partner supplies real."
        ),
        blocker=Blocker.PARTNERSHIP,
        lifted_by="PPATK / a bank / a tag provider",
        flag=None,
    ),
    GatedFeature(
        key="iasc_export",
        label="Automated export into OJK's IASC pipeline",
        what=(
            "Pushing a completed action bundle into IASC. Not an integration "
            "task: accepting third-party writes is a governance decision inside "
            "OJK, with an MoU and a security review."
        ),
        blocker=Blocker.REGULATOR,
        lifted_by="OJK — MoU and security review",
        flag=None,
    ),
)

GATED_BY_KEY: dict[str, GatedFeature] = {f.key: f for f in GATED}


def blocked_on_others() -> tuple[GatedFeature, ...]:
    """Capabilities waiting on someone outside this team.

    The useful cut. Everything NOT in here is off because of a decision or a
    purchase we control — and that distinction is what stops "we need
    permission" becoming a reason nothing moves.
    """
    ours = {Blocker.PRODUCT, Blocker.CREDENTIAL, Blocker.UNVERIFIED}
    return tuple(f for f in GATED if f.blocker not in ours)
