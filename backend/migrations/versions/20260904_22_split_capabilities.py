"""core.roles: expand the coarse capabilities into the split ones.

``honeypot.operate`` became ``honeypot.read`` / ``honeypot.engage`` /
``honeypot.dial``, and ``action.generate`` was separated out from
``dispatch.send``. Without this migration every role holding the old keys would
resolve to NOTHING for them: the resolver drops capabilities this build does not
enforce (``app/core/roles.py``), so a stored ``honeypot.operate`` becomes a
warning in the log and an investigator who can no longer open the honeypot.

**Expands, never narrows.** A role that could do all three honeypot things keeps
being able to do all three — the split is about what can be granted SEPARATELY
from now on, not about taking anything away in flight. Deciding on someone's
behalf that they should lose dialling would be a policy change smuggled inside a
refactor.

``action.generate`` is added wherever ``dispatch.send`` was held, for the same
reason: generating a bundle was previously ungated (any authenticated role), so
everyone who could dispatch could already generate. They keep that. The
tightening this release DOES make — that generating now requires a capability at
all — falls on roles that never had ``dispatch.send``, and that is the point.

**Only touches roles still holding an old key.** A role edited since is left
alone; there is nothing to expand.

Revision ID: 20260904_22
Revises: 20260904_21
Create Date: 2026-09-04
"""

import json

import sqlalchemy as sa
from alembic import op

revision = "20260904_22"
down_revision = "20260904_21"
branch_labels = None
depends_on = None

OLD_HONEYPOT = "honeypot.operate"
NEW_HONEYPOT = ["honeypot.read", "honeypot.engage", "honeypot.dial"]
DISPATCH = "dispatch.send"
GENERATE = "action.generate"

#: Built-ins that could generate a bundle before this release and must keep
#: doing so. Generating was UNGATED (any authenticated role), and these two are
#: the roles for which that was a deliberate product decision rather than an
#: oversight — a bank or exchange compliance officer drafts the filing about
#: their own customer, and law enforcement decides whether to send it. Pinned by
#: `test_compliance_can_generate_but_not_dispatch`, which predates capabilities.
#:
#: Named explicitly rather than granting it to everyone: the tightening this
#: release makes is real, and should fall on every OTHER role that only ever had
#: it by accident of the endpoint being unguarded.
KEEP_GENERATE = ("bank-compliance", "exchange-compliance")


def _rewrite(conn, forward: bool) -> None:
    rows = conn.execute(
        sa.text("SELECT name, permissions FROM core.roles WHERE permissions IS NOT NULL")
    ).fetchall()
    for name, permissions in rows:
        caps = list((permissions or {}).get("capabilities") or [])
        # NOT skipped when empty: bank-compliance legitimately holds nothing yet
        # and still needs action.generate added.
        before = set(caps)
        out = set(caps)

        if forward:
            if OLD_HONEYPOT in out:
                out.discard(OLD_HONEYPOT)
                out.update(NEW_HONEYPOT)
            if DISPATCH in out or name in KEEP_GENERATE:
                out.add(GENERATE)
        else:
            if out & set(NEW_HONEYPOT):
                out -= set(NEW_HONEYPOT)
                out.add(OLD_HONEYPOT)
            out.discard(GENERATE)

        if out == before:
            continue
        conn.execute(
            sa.text(
                "UPDATE core.roles SET permissions = "
                "jsonb_set(COALESCE(permissions, '{}'::jsonb), '{capabilities}', "
                "CAST(:caps AS jsonb)) WHERE name = :name"
            ),
            {"name": name, "caps": json.dumps(sorted(out))},
        )


def upgrade() -> None:
    _rewrite(op.get_bind(), forward=True)


def downgrade() -> None:
    # Collapses the three honeypot keys back to one and drops action.generate,
    # so a rollback of the CODE does not leave roles holding keys the older
    # build cannot enforce — which would silently remove honeypot access.
    _rewrite(op.get_bind(), forward=False)
