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

# Honeypot, split by CONSEQUENCE rather than by screen. Reviewing a transcript,
# talking to a suspect, and cold-calling a list of numbers are three different
# acts, and one permission covering all three meant the least dangerous one
# carried the authority of the most dangerous.
HONEYPOT_READ = "honeypot.read"
HONEYPOT_ENGAGE = "honeypot.engage"
HONEYPOT_DIAL = "honeypot.dial"

CASE_WRITE = "case.write"

# Producing the documents is reversible and internal; sending them is neither.
ACTION_GENERATE = "action.generate"
DISPATCH_SEND = "dispatch.send"
USERS_ADMIN = "users.admin"
USERS_ADMIN_CROSS_AGENCY = "users.admin.cross_agency"
ROLES_ADMIN = "roles.admin"


#: Presentation grouping for the admin screen, in display order. Deliberately
#: NOT part of the permission model: a capability is defined by the consequence
#: it authorises, not by the screen it happens to appear on. Screens move — Users
#: and Audit Trail changed menus in one afternoon — and a model keyed on where
#: something appears turns every nav tidy-up into a permission migration.
#:
#: It lives here rather than in the frontend so the grouping cannot drift from
#: the capabilities it groups: adding a capability without placing it is caught
#: by a test, not discovered as an empty section in the UI.
GROUPS: tuple[tuple[str, str], ...] = (
    ("honeypot", "Honeypot"),
    ("cases", "Cases"),
    ("actions", "Freeze requests & filings"),
    ("admin", "Administration"),
)

GROUP_KEYS: frozenset[str] = frozenset(k for k, _ in GROUPS)


@dataclass(frozen=True)
class Capability:
    """One thing the system can permit. ``description`` is shown in the admin UI,
    so it is written for the person deciding whether to grant it — not for us.

    ``group`` affects only where it is drawn."""

    key: str
    label: str
    description: str
    group: str


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        HONEYPOT_READ,
        "Read honeypot transcripts",
        "See deception sessions and what was said in them, including call "
        "audio. Reviewing the record without conducting an operation — a "
        "supervisor or an analyst writing up a case needs this and usually "
        "nothing more. The intelligence it produced (entities, syndicates) "
        "stays readable without even this.",
        group="honeypot",
    ),
    Capability(
        HONEYPOT_ENGAGE,
        "Talk to a suspect",
        "Start a deception session and send turns in it, and set the voice the "
        "persona speaks with. This is live contact with a person under "
        "investigation — grant it only to roles authorised to conduct one.",
        group="honeypot",
    ),
    Capability(
        HONEYPOT_DIAL,
        "Place outbound calls",
        "Manage the pool of numbers we call FROM and run dial campaigns against "
        "a list of numbers. The most consequential honeypot permission: it "
        "initiates contact with people who have not contacted us, which is a "
        "decision with legal weight and should sit with whoever carries it.",
        group="honeypot",
    ),
    Capability(
        CASE_WRITE,
        "Create and edit cases",
        "Open a case and change its details or stage. Reading cases does not "
        "need this — everyone in the agency shares the same case picture.",
        group="cases",
    ),
    Capability(
        ACTION_GENERATE,
        "Generate freeze requests and filings",
        "Produce the documents for a case — freeze request, STR/LTKM draft, "
        "agency alert — hashed as evidence. Nothing leaves the building yet, so "
        "this is reversible, but the documents carry the agency's name.",
        group="actions",
    ),
    Capability(
        DISPATCH_SEND,
        "Send them to another agency",
        "Dispatch a generated bundle outward, and retry a failed delivery. "
        "Irreversible and outward-facing: what leaves cannot be recalled. "
        "Separate from generating, so drafting and sending can be different "
        "people.",
        group="actions",
    ),
    Capability(
        USERS_ADMIN,
        "Manage users",
        "Invite people, change their role, and deactivate them — within this "
        "agency only.",
        group="admin",
    ),
    Capability(
        ROLES_ADMIN,
        "Define roles and what they can do",
        "Create roles, and choose which capabilities each one grants. This is "
        "the most powerful permission in the system: it edits the permission "
        "system itself, and roles are GLOBAL — a change here applies to every "
        "agency, not just yours. Platform operators only.",
        group="admin",
    ),
    Capability(
        USERS_ADMIN_CROSS_AGENCY,
        "Manage users in any agency",
        "Administer accounts belonging to OTHER agencies. Platform operators "
        "only; an agency administrator must never hold this.",
        group="admin",
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
    "police-investigator": frozenset(
        {
            HONEYPOT_READ,
            HONEYPOT_ENGAGE,
            HONEYPOT_DIAL,
            CASE_WRITE,
            ACTION_GENERATE,
            DISPATCH_SEND,
        }
    ),
    # Financial intelligence (PPATK): owns cases and dispatches, but does not
    # run deception operations — that is not a regulator's function.
    "regulator-analyst": frozenset({CASE_WRITE, ACTION_GENERATE, DISPATCH_SEND}),
    # Institutions contribute data, read the shared picture, and DRAFT filings —
    # a bank's compliance officer preparing an STR about their own customer is
    # the normal path. They do not run the honeypot, and they do not dispatch:
    # deciding to send a freeze request outward is law enforcement's call.
    # This separation predates capabilities (see
    # `test_compliance_can_generate_but_not_dispatch`) and is exactly what
    # splitting action.generate from dispatch.send exists to express.
    "bank-compliance": frozenset({ACTION_GENERATE}),
    "exchange-compliance": frozenset({ACTION_GENERATE}),
    # Administers its own agency, and can do everything an investigator can.
    "agency-admin": frozenset(
        {
            HONEYPOT_READ,
            HONEYPOT_ENGAGE,
            HONEYPOT_DIAL,
            CASE_WRITE,
            ACTION_GENERATE,
            DISPATCH_SEND,
            USERS_ADMIN,
        }
    ),
    # Platform operator: the only role that crosses agency boundaries.
    "platform-admin": frozenset(
        {
            HONEYPOT_READ,
            HONEYPOT_ENGAGE,
            HONEYPOT_DIAL,
            CASE_WRITE,
            ACTION_GENERATE,
            DISPATCH_SEND,
            USERS_ADMIN,
            USERS_ADMIN_CROSS_AGENCY,
            ROLES_ADMIN,
        }
    ),
}

#: Capabilities without which nobody could administer anything ever again. The
#: role admin API refuses any edit that would leave zero roles holding one of
#: these — the role-level twin of UAM's `last_admin` guard, and the reason a
#: configurable permission system cannot lock everyone out of itself.
UNREMOVABLE_CAPABILITIES: frozenset[str] = frozenset({USERS_ADMIN, ROLES_ADMIN})
