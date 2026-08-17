"""RLS for the two join tables that carry tenant links but had no policy.

Found by an RLS isolation review (docs/Backlog.md → go-live hardening), and
confirmed empirically before writing this: with agency A's tenant context, the
non-owner ``ittu_app`` role was correctly blocked from agency B's
``intel.syndicates`` row AND its ``intel.entities`` row — but could still read
the ``intel.syndicate_members`` row linking the two.

Neither table has an ``agency_id`` of its own, which is why they were missed:
the pattern that protects them is a join through their parent, exactly as
migration 20260816_13/15 does for ``honeypot.dial_targets`` and
``dial_attempts``. This applies that same pattern consistently.

What was leaking, concretely:

* ``intel.syndicate_members`` — the shape of another agency's investigation
  graph: which opaque ids cluster together, the link type, the confidence, and
  how many links exist. The ids are unreadable on their own, but the structure
  and volume are still intelligence about another agency's case.
* ``fiat.correlations`` — the crypto↔fiat links behind another agency's case
  (``case_id`` is a uuid into the agency-scoped ``core.cases``). Empty today,
  which is precisely why it should be fixed now rather than after it fills up.

No ``SECURITY DEFINER`` helper is needed: the references run one way
(members → syndicates, correlations → cases), so consulting the parent cannot
re-trigger the child's policy.

Revision ID: 20260818_16
Revises: 20260816_15
Create Date: 2026-08-18
"""

from alembic import op

revision = "20260818_16"
down_revision = "20260816_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # intel.syndicate_members -> policed through its syndicate's agency.
    op.execute("ALTER TABLE intel.syndicate_members ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY syndicate_members_access ON intel.syndicate_members
        USING (syndicate_id IN (
            SELECT s.id FROM intel.syndicates s
            WHERE s.agency_id = core.current_agency()
        ))
        """
    )

    # fiat.correlations -> policed through its case's agency.
    op.execute("ALTER TABLE fiat.correlations ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY correlations_access ON fiat.correlations
        USING (case_id IN (
            SELECT c.id FROM core.cases c
            WHERE c.agency_id = core.current_agency()
        ))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS correlations_access ON fiat.correlations")
    op.execute("ALTER TABLE fiat.correlations DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS syndicate_members_access ON intel.syndicate_members")
    op.execute("ALTER TABLE intel.syndicate_members DISABLE ROW LEVEL SECURITY")
