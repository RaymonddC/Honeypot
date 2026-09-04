"""core.roles: seed the default role → capability policy.

``core.roles`` has existed since migration 05 with a ``permissions`` JSONB column
and **nothing has ever written to it** — the same shape as ``core.users.is_active``,
which was migrated, documented, and then read by nothing until UAM.

That matters now, because roles becoming DATA means an empty table is not a
neutral starting state: it is a system where every role holds no capabilities and
nobody can do anything. Seeding is what makes the feature usable at all.

**Seeded, not enforced.** This inserts each default role only if it is absent, so
re-running never overwrites an administrator's edits. The database is the source
of truth from the first boot onward; ``DEFAULT_ROLE_CAPABILITIES`` in
``app/core/capabilities.py`` is a starting policy, not a spec the code re-asserts.

**The values are duplicated here on purpose.** A migration must describe the
schema at ITS point in history, so it cannot import a constant that a later
release will change — the migration would then apply different data depending on
which version ran it, and two databases migrated months apart would disagree
about what a role means. `test_role_seed.py` asserts this literal matches
``DEFAULT_ROLE_CAPABILITIES`` today, so drift is caught while both are current.

Revision ID: 20260823_19
Revises: 20260823_18
Create Date: 2026-08-23
"""

import json
import uuid

import sqlalchemy as sa
from alembic import op

revision = "20260823_19"
down_revision = "20260823_18"
branch_labels = None
depends_on = None

# name -> capabilities. Mirrors DEFAULT_ROLE_CAPABILITIES at this revision.
SEED: dict[str, list[str]] = {
    "police-investigator": [
        "action.generate",
        "case.write",
        "dispatch.send",
        "honeypot.dial",
        "honeypot.engage",
        "honeypot.read"
    ],
    "regulator-analyst": [
        "action.generate",
        "case.write",
        "dispatch.send"
    ],
    "bank-compliance": [
        "action.generate"
    ],
    "exchange-compliance": [
        "action.generate"
    ],
    "agency-admin": [
        "action.generate",
        "case.write",
        "dispatch.send",
        "honeypot.dial",
        "honeypot.engage",
        "honeypot.read",
        "users.admin"
    ],
    "platform-admin": [
        "action.generate",
        "case.write",
        "dispatch.send",
        "honeypot.dial",
        "honeypot.engage",
        "honeypot.read",
        "roles.admin",
        "users.admin",
        "users.admin.cross_agency"
    ]
}


def upgrade() -> None:
    conn = op.get_bind()
    for name, capabilities in SEED.items():
        # ON CONFLICT is not usable as a guard here: `name` is UNIQUE, but an
        # administrator may legitimately have edited a seeded role, and DO
        # NOTHING would still be correct while DO UPDATE would silently revert
        # their change. Explicit existence check states the intent.
        conn.execute(
            sa.text(
                """
                INSERT INTO core.roles (id, name, agency_type, permissions)
                SELECT :id, :name, NULL, CAST(:perms AS jsonb)
                WHERE NOT EXISTS (SELECT 1 FROM core.roles WHERE name = :name)
                """
            ),
            {
                "id": str(uuid.uuid4()),
                "name": name,
                "perms": json.dumps({"capabilities": capabilities}),
            },
        )


def downgrade() -> None:
    # Only the rows this migration could have created, and only if they still
    # look untouched — deleting a role an administrator has since edited would
    # destroy their policy to undo a seed.
    conn = op.get_bind()
    for name, capabilities in SEED.items():
        conn.execute(
            sa.text(
                """
                DELETE FROM core.roles
                WHERE name = :name
                  AND permissions = CAST(:perms AS jsonb)
                """
            ),
            {"name": name, "perms": json.dumps({"capabilities": capabilities})},
        )
