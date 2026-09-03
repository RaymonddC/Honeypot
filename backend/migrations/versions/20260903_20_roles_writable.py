"""core.roles: let the app WRITE it, now that roles are administered in-product.

Migration 05 enabled RLS on ``core.roles`` and gave it exactly one policy —
``roles_read ... FOR SELECT USING (true)``. Under RLS a command with no
permissive policy is DENIED, so ``ittu_app`` could read roles and could not
insert, update or delete one. That was correct while roles were a static
directory nobody edited; it stops being correct the moment there is an admin API,
and the symptom would have been every save failing with a bare permission error.

**RLS is NOT the barrier for this table, and that is deliberate — read this
before "tightening" it.** ``core.roles`` is GLOBAL: it has no ``agency_id``
(migration 05), because a role is a platform-wide definition rather than a
tenant's data. RLS's vocabulary here is the per-transaction settings, so the only
expressible check would be against ``app.current_role`` — pinning a role NAME
into SQL, in the very table that exists to stop role names being hardcoded. That
is circular, and it would break the instant an operator renamed a role.

So the barrier is the ``roles.admin`` capability, enforced in
``app/roles/router.py``. This is the same shape as the worker's owner-role
connection: a place where RLS deliberately does not apply and the application
check is the real one. It is written down rather than left implicit, because a
reader who assumes RLS covers this table would be wrong in a way that matters.

Two things keep that honest: ``roles.admin`` is seeded ONLY to ``platform-admin``,
and every mutation is audited (``role.created`` / ``role.updated`` /
``role.deleted``) with the before-and-after capability sets.

Revision ID: 20260903_20
Revises: 20260823_19
Create Date: 2026-09-03
"""

from alembic import op

revision = "20260903_20"
down_revision = "20260823_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Separate policies per command rather than one FOR ALL: a future decision to
    # forbid deletion (or to scope updates) then edits one policy instead of
    # rewriting a combined one and risking the others as collateral.
    op.execute(
        "CREATE POLICY roles_insert ON core.roles FOR INSERT WITH CHECK (true)"
    )
    op.execute(
        "CREATE POLICY roles_update ON core.roles FOR UPDATE USING (true) WITH CHECK (true)"
    )
    op.execute("CREATE POLICY roles_delete ON core.roles FOR DELETE USING (true)")


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS roles_delete ON core.roles")
    op.execute("DROP POLICY IF EXISTS roles_update ON core.roles")
    op.execute("DROP POLICY IF EXISTS roles_insert ON core.roles")
