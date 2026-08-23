"""POC/LIVE evidentiary isolation, enforced by RLS (go-live hardening).

``data_mode`` has existed on 24 tables since migration 01, with a CHECK
constraint and a NOT NULL default — and **nothing ever read it back**. All 18
uses across the five Postgres repositories were the INSERT side; not one
appeared in a WHERE clause, and no RLS policy mentioned it. It was a label, not
a boundary: a POC row and a LIVE row in ``core.cases`` came back from the same
``list_cases()`` with nothing separating them but a string the caller might
forget to check. For a forensics tool, "could this row have been fabricated by a
demo?" has to be answerable structurally.

This makes mode a per-transaction RLS predicate, exactly as agency already is.
``_tenant_scoped_session`` sets ``app.data_mode`` alongside ``app.current_agency``;
``core.current_mode()`` reads it; the policies below compare it to each row's
``data_mode``. A query that forgets to filter now CANNOT leak, because the
database refuses — rather than every future query having to remember.

**Fail-closed, same as agency.** ``current_setting(..., true)`` returns NULL when
unset, and ``data_mode = NULL`` is never true, so a session that never sets the
variable sees nothing. Verified against a real Postgres, not assumed: an unset
variable AND a garbage value both yield zero rows.

**The write side is guarded for free, and that is load-bearing.** Postgres uses
``USING`` as the implicit ``WITH CHECK`` for INSERT, so a mode-mismatched insert
raises ``InsufficientPrivilegeError`` rather than writing a row that is
invisible to its own writer. Every policy below therefore states ``WITH CHECK``
explicitly and identically — an explicit *permissive* WITH CHECK would silently
remove that protection. ``test_mode_isolation_pg.py`` pins it.

## Why ``core.audit_log`` is deliberately NOT here

Adding a mode predicate to the audit trail makes it report itself as TAMPERED.
``verify_chain`` selects every row for the agency ordered by ``seq`` and walks
``prev_sha256``; hiding any entry breaks the linkage. Measured with the real
``entry_hash``/``_verify`` over a chain of poc,poc,live,live:

    unfiltered (owner):                 (True, None)
    LIVE session, poc hidden:           (False, 3)    <- false tamper alarm
    POC session, live hidden:           (True, None)  <- SILENT TRUNCATION

The second is the dangerous one: hiding entries at the TAIL of a hash chain is
undetectable — it verifies green while records are missing, which is exactly the
blind spot ``ittu_audit_entries_dropped_total`` exists to cover.

It is also arguably wrong on the merits. The trail answers "everything that
happened in this tenant", and an investigator asking "was this case built from
demo data" needs the POC and LIVE actions in ONE ordered sequence — the moment
of transition is the most interesting entry in the log, and a partitioned trail
is precisely where it would be invisible. Provenance belongs IN the record; it
must not decide who may read it. Mode is recorded in the hashed ``detail`` blob
instead (``detail->>'_data_mode'``, see app/core/audit.py) — tamper-evident,
queryable, and asserting nothing about entries written before mode tracking.

## Why ``core.users`` / ``agencies`` / ``roles`` / ``case_shares`` are not here

Identity and reference data. An operator does not belong to a mode.

## Why ``chain.*`` / ``fiat.*`` raw ledger tables are not here

They have no RLS at all (deliberately not agency-scoped — public-ledger
reference facts shared across agencies, see 20260715_06) and, as of this
migration, **zero read sites and zero write sites**: chain/fiat data flows
through adapters reading fixtures and live APIs, never through Postgres. A
policy on a table nothing touches cannot be tested — only asserted to exist.
Whoever first persists chain/fiat data must add a MODE-ONLY policy at that
point; recorded in docs/Data-Model.md so it is an obligation, not an oversight.

Revision ID: 20260823_18
Revises: 20260822_17
Create Date: 2026-08-23
"""

from alembic import op

revision = "20260823_18"
down_revision = "20260822_17"
branch_labels = None
depends_on = None

# The plain shape: agency-owned table carrying its own data_mode column.
# (schema, table)
SIMPLE_TABLES = [
    ("intel", "scam_sessions"),
    ("intel", "messages"),
    ("intel", "entities"),
    ("intel", "syndicates"),
    ("intel", "crime_classifications"),
    ("action", "action_documents"),
    ("action", "notifications"),
    ("action", "action_bundles"),
    ("core", "evidence_manifest"),
    ("chain", "graph_snapshots"),
    ("casedata", "bank_accounts"),
    ("casedata", "crypto_transfers"),
    ("honeypot", "numbers"),
    ("honeypot", "dial_campaigns"),
]

# fiat.correlations is NOT in the list above: it has no agency_id of its own and
# is policed through its case (migration 16). It does carry data_mode, so mode
# is checked directly on the row while ownership stays a subquery.
_CORRELATIONS_OWNER = (
    "case_id IN (SELECT c.id FROM core.cases c WHERE c.agency_id = core.current_agency())"
)

_MODE = "data_mode = core.current_mode()"


def _repolicy(schema: str, table: str, using: str, check: str) -> None:
    """Replace a table's access policy in place.

    DROP+CREATE rather than ALTER POLICY: ALTER cannot change a policy's
    expression in every Postgres version we might meet, and the DROP is
    IF EXISTS so re-running after a partial failure is safe.
    """
    op.execute(f'DROP POLICY IF EXISTS {table}_access ON "{schema}".{table}')
    op.execute(
        f"""
        CREATE POLICY {table}_access ON "{schema}".{table}
        USING ({using})
        WITH CHECK ({check})
        """
    )


def upgrade() -> None:
    # The mode twin of core.current_agency() (migration 05). No uuid cast — mode
    # is text — but the same nullif(..., true) shape, so an unset variable is
    # NULL and every predicate below denies rather than admits.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION core.current_mode() RETURNS text
        LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.data_mode', true), '') $$
        """
    )

    for schema, table in SIMPLE_TABLES:
        _repolicy(
            schema,
            table,
            using=f"agency_id = core.current_agency() AND {_MODE}",
            check=f"agency_id = core.current_agency() AND {_MODE}",
        )

    # core.cases — the baseline policy also admits explicitly SHARED cases. Mode
    # is ANDed OUTSIDE that OR on purpose: a case shared with you by another
    # agency is still subject to your mode. Sharing crosses tenants, never modes.
    _repolicy(
        "core",
        "cases",
        using=(
            "(agency_id = core.current_agency() OR id IN (SELECT core.shared_case_ids())) "
            f"AND {_MODE}"
        ),
        check=f"agency_id = core.current_agency() AND {_MODE}",
    )

    # honeypot.dial_targets — ownership lives on the campaign (migration 13).
    # The row carries its own data_mode, so mode is checked directly rather than
    # through the join: a target whose mode drifted from its campaign's should
    # disappear, not be rescued by its parent.
    _repolicy(
        "honeypot",
        "dial_targets",
        using=(
            'campaign_id IN (SELECT id FROM "honeypot".dial_campaigns '
            f"WHERE agency_id = core.current_agency()) AND {_MODE}"
        ),
        check=(
            'campaign_id IN (SELECT id FROM "honeypot".dial_campaigns '
            f"WHERE agency_id = core.current_agency()) AND {_MODE}"
        ),
    )

    # honeypot.dial_attempts — ownership is two hops away (migration 15). Same
    # reasoning: its own data_mode, checked directly.
    _attempts_owner = (
        'target_id IN (SELECT t.id FROM "honeypot".dial_targets t '
        'JOIN "honeypot".dial_campaigns c ON c.id = t.campaign_id '
        "WHERE c.agency_id = core.current_agency())"
    )
    _repolicy(
        "honeypot",
        "dial_attempts",
        using=f"{_attempts_owner} AND {_MODE}",
        check=f"{_attempts_owner} AND {_MODE}",
    )

    _repolicy(
        "fiat",
        "correlations",
        using=f"{_CORRELATIONS_OWNER} AND {_MODE}",
        check=f"{_CORRELATIONS_OWNER} AND {_MODE}",
    )

    # intel.syndicate_members — the ONE table here with no data_mode of its own.
    # It inherits the parent syndicate's, by extending the subquery migration 16
    # already uses for agency. Deliberately NOT given its own column: a join
    # table has no independent mode, and a column would be a second source of
    # truth that could drift from the parent (and, with no write path in the app
    # today, would sit at its 'poc' default forever — invisible in LIVE even
    # when its syndicate is live). The subquery is safe here because the
    # dependency is one-directional; the SECURITY DEFINER helpers in migration 05
    # exist for the MUTUAL cases <-> case_shares recursion, which this is not.
    _members_parent = (
        "syndicate_id IN (SELECT s.id FROM intel.syndicates s "
        "WHERE s.agency_id = core.current_agency() "
        "AND s.data_mode = core.current_mode())"
    )
    _repolicy("intel", "syndicate_members", using=_members_parent, check=_members_parent)


def downgrade() -> None:
    for schema, table in SIMPLE_TABLES:
        _repolicy(
            schema,
            table,
            using="agency_id = core.current_agency()",
            check="agency_id = core.current_agency()",
        )

    _repolicy(
        "core",
        "cases",
        using="agency_id = core.current_agency() OR id IN (SELECT core.shared_case_ids())",
        check="agency_id = core.current_agency()",
    )

    _targets_owner = (
        'campaign_id IN (SELECT id FROM "honeypot".dial_campaigns '
        "WHERE agency_id = core.current_agency())"
    )
    _repolicy("honeypot", "dial_targets", using=_targets_owner, check=_targets_owner)

    _attempts_owner = (
        'target_id IN (SELECT t.id FROM "honeypot".dial_targets t '
        'JOIN "honeypot".dial_campaigns c ON c.id = t.campaign_id '
        "WHERE c.agency_id = core.current_agency())"
    )
    _repolicy("honeypot", "dial_attempts", using=_attempts_owner, check=_attempts_owner)

    # migration 16 created both of these with USING only (no WITH CHECK).
    op.execute("DROP POLICY IF EXISTS correlations_access ON fiat.correlations")
    op.execute(
        f"""
        CREATE POLICY correlations_access ON fiat.correlations
        USING ({_CORRELATIONS_OWNER})
        """
    )
    op.execute("DROP POLICY IF EXISTS syndicate_members_access ON intel.syndicate_members")
    op.execute(
        """
        CREATE POLICY syndicate_members_access ON intel.syndicate_members
        USING (syndicate_id IN (
            SELECT s.id FROM intel.syndicates s
            WHERE s.agency_id = core.current_agency()
        ))
        """
    )

    op.execute("DROP FUNCTION IF EXISTS core.current_mode()")
