"""Capabilities — what the system can permit, and which roles hold each one.

**The split that makes configurable roles safe.**

* A CAPABILITY is defined here, in code, because each one corresponds to a guard
  on a real endpoint. The set is closed: an administrator cannot invent
  ``honeypot.launch_missiles`` in the UI and have it mean anything, because
  nothing checks it. Every capability in ``CAPABILITIES`` below is enforced
  somewhere, and ``test_capabilities.py`` fails if one stops being.
* A ROLE is DATA — a named bundle of capabilities in ``core.roles.permissions``.
  Adding a role, renaming one, or changing what it may do is a row edit, not a
  deploy.

Getting this backwards is the usual way permission systems rot: if roles carry
free-form permission strings, the UI accumulates entries nobody enforces, and
the list stops describing the system. Here the UI can only ever offer switches
that are wired to something.

**Why capabilities rather than role checks at each endpoint.** ``require_role``
hardcodes WHICH roles may act, so every new role means editing and redeploying
every guard. A capability names WHAT is being done and lets the role↔capability
mapping move to data — which is the whole point of letting an agency define its
own roles.

**The seeded defaults are a starting point, not a policy.** They encode one
judgement — that operating the honeypot is a law-enforcement act while its
INTELLIGENCE OUTPUT is shared — because a bank's compliance officer must not
run a tool that engages a live suspect, but does need the wallets and accounts
it surfaced. An agency that disagrees can change it without touching code, which
is exactly what this module exists to allow.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------- #
# The closed set of capabilities
# --------------------------------------------------------------------------- #

HONEYPOT_OPERATE = "honeypot.operate"
CASE_WRITE = "case.write"
DISPATCH_SEND = "dispatch.send"
USERS_ADMIN = "users.admin"
USERS_ADMIN_CROSS_AGENCY = "users.admin.cross_agency"


@dataclass(frozen=True)
class Capability:
    """One thing the system can permit. ``description`` is shown in the admin UI,
    so it is written for the person deciding whether to grant it — not for us."""

    key: str
    label: str
    description: str


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        HONEYPOT_OPERATE,
        "Operate the honeypot",
        "Run deception sessions and outbound calling: read scam transcripts, "
        "manage the number pool, and start dial campaigns. This is contact with "
        "a live suspect — grant it only to roles authorised to conduct one. The "
        "intelligence it produces (entities, syndicates) stays readable without "
        "this.",
    ),
    Capability(
        CASE_WRITE,
        "Create and edit cases",
        "Open a case and change its details or stage. Reading cases does not "
        "need this — everyone in the agency shares the same case picture.",
    ),
    Capability(
        DISPATCH_SEND,
        "Send freeze requests and alerts",
        "Generate an action bundle and dispatch it to another agency. "
        "Irreversible and outward-facing: what leaves cannot be recalled.",
    ),
    Capability(
        USERS_ADMIN,
        "Manage users",
        "Invite people, change their role, and deactivate them — within this "
        "agency only.",
    ),
    Capability(
        USERS_ADMIN_CROSS_AGENCY,
        "Manage users in any agency",
        "Administer accounts belonging to OTHER agencies. Platform operators "
        "only; an agency administrator must never hold this.",
    ),
)

CAPABILITY_KEYS: frozenset[str] = frozenset(c.key for c in CAPABILITIES)


def is_capability(key: str) -> bool:
    """Whether ``key`` is a capability this system actually enforces.

    The admin API rejects anything else rather than storing it: a permission
    nobody checks is worse than an absent one, because the UI then reports a
    protection that does not exist.
    """
    return key in CAPABILITY_KEYS


# --------------------------------------------------------------------------- #
# Seeded defaults — the starting policy, changeable as data
# --------------------------------------------------------------------------- #

#: Role name → capabilities, used ONLY to seed an empty ``core.roles`` and as
#: the fallback when persistence is in memory. Once seeded, the database is the
#: source of truth and edits there are never overwritten from here.
DEFAULT_ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    # Law enforcement: runs the honeypot, owns cases, dispatches.
    "police-investigator": frozenset({HONEYPOT_OPERATE, CASE_WRITE, DISPATCH_SEND}),
    # Financial intelligence (PPATK): owns cases and dispatches, but does not
    # run deception operations — that is not a regulator's function.
    "regulator-analyst": frozenset({CASE_WRITE, DISPATCH_SEND}),
    # Institutions contribute data and read the shared picture. They do not run
    # the honeypot and do not dispatch on another agency's behalf.
    "bank-compliance": frozenset(),
    "exchange-compliance": frozenset(),
    # Administers its own agency, and can do everything an investigator can.
    "agency-admin": frozenset(
        {HONEYPOT_OPERATE, CASE_WRITE, DISPATCH_SEND, USERS_ADMIN}
    ),
    # Platform operator: the only role that crosses agency boundaries.
    "platform-admin": frozenset(
        {
            HONEYPOT_OPERATE,
            CASE_WRITE,
            DISPATCH_SEND,
            USERS_ADMIN,
            USERS_ADMIN_CROSS_AGENCY,
        }
    ),
}

#: Capabilities without which nobody could administer anything ever again. The
#: role admin API refuses any edit that would leave zero roles holding one of
#: these — the role-level twin of UAM's `last_admin` guard, and the reason a
#: configurable permission system cannot lock everyone out of itself.
UNREMOVABLE_CAPABILITIES: frozenset[str] = frozenset({USERS_ADMIN})
