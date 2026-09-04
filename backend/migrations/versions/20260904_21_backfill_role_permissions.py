"""core.roles: actually fill in `permissions` — migration 19 never could.

Migration 19 inserts each default role "if absent". It is absent from no
database: **migration 05 already seeds all six names** (``INSERT INTO core.roles
(id, name, agency_type) ... ON CONFLICT DO NOTHING``), with no ``permissions``
at all. So 19's guard skipped every row and the column stayed NULL everywhere.

That was harmless while nothing read the column. It stopped being harmless the
moment capabilities became the authorisation mechanism: a role with NULL
permissions resolves to NO capabilities, so on the first deploy carrying the
guards, every protected endpoint would 403 for everyone — honeypot, dispatch,
case writes and user administration at once, with the audit trail dutifully
recording each refusal. Confirmed present on both the local database and Neon
before writing this.

**Fills only what is empty.** The condition is "no ``capabilities`` key", not
"is a default role", so:

* a row seeded by 05 with NULL permissions gets the starting policy, and
* a role an administrator has already configured is left completely alone —
  including one deliberately set to ``{"capabilities": []}``, which is a real
  decision ("this role may do nothing") and must not be silently repopulated.

That distinction is why this is not `ON CONFLICT DO UPDATE`: overwriting would
reset an administrator's policy on every deploy, which is a worse failure than
the one being fixed here.

Revision ID: 20260904_21
Revises: 20260903_20
Create Date: 2026-09-04
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "20260904_21"
down_revision = "20260903_20"
branch_labels = None
depends_on = None

# Duplicated from app/core/capabilities.DEFAULT_ROLE_CAPABILITIES on purpose — a
# migration must describe its own point in history rather than import a constant
# a later release will change. `test_capabilities.py` asserts the two agree while
# both are current.
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
        conn.execute(
            sa.text(
                """
                UPDATE core.roles
                   SET permissions = CAST(:perms AS jsonb)
                 WHERE name = :name
                   AND (permissions IS NULL OR NOT permissions ? 'capabilities')
                """
            ),
            {"name": name, "perms": json.dumps({"capabilities": capabilities})},
        )
        # The role may be missing entirely on a database that never ran 05's
        # seed (none today, but this migration should not depend on that).
        conn.execute(
            sa.text(
                """
                INSERT INTO core.roles (id, name, agency_type, permissions)
                SELECT gen_random_uuid(), :name, NULL, CAST(:perms AS jsonb)
                 WHERE NOT EXISTS (SELECT 1 FROM core.roles WHERE name = :name)
                """
            ),
            {"name": name, "perms": json.dumps({"capabilities": capabilities})},
        )


def downgrade() -> None:
    # Clear ONLY rows that still hold exactly what this migration wrote. A role
    # edited since is left alone: undoing a backfill must not delete somebody's
    # policy.
    conn = op.get_bind()
    for name, capabilities in SEED.items():
        conn.execute(
            sa.text(
                """
                UPDATE core.roles
                   SET permissions = NULL
                 WHERE name = :name
                   AND permissions = CAST(:perms AS jsonb)
                """
            ),
            {"name": name, "perms": json.dumps({"capabilities": capabilities})},
        )
