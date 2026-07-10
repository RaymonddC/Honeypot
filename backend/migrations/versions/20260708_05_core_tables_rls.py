"""core schema: agencies, users, roles, cases, case_shares, audit_log — WITH
Row-Level Security policies (docs/Data-Model.md §RLS, docs/Security-Evidence.md §2).

Baseline policy: owning agency OR explicitly shared via core.case_shares (never
implicit). The request middleware sets per-transaction vars after verifying the
JWT (see app.core.db.get_tenant_session)::

    SELECT set_config('app.current_agency', '<uuid>', true);  -- SET LOCAL
    SELECT set_config('app.current_user',   '<uuid>', true);
    SELECT set_config('app.current_role',   '<role>', true);

Unset vars resolve to NULL (missing_ok=true) → predicates are false → **fail
closed** (no rows) rather than error.

DEPLOYMENT INVARIANT: the app must connect as a NON-superuser, non-table-owner
role — superusers and table owners bypass RLS. The SECURITY DEFINER helper
functions below run as the migration/owner role precisely to break the
cases ⇄ case_shares policy recursion without weakening either policy.

Seed: the five demo agencies + role templates (ids match app/core/auth.py).
Demo *users* stay in-memory (POC login mints them); LIVE provisioning inserts
real core.users rows.

Revision ID: 20260708_05
Revises: 20260707_04
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import BYTEA, JSONB

revision = "20260708_05"
down_revision = "20260707_04"
branch_labels = None
depends_on = None

# Deterministic seed ids — uuid5(NAMESPACE_URL, "ittu:agency:<slug>"), matching
# app/core/auth.py so demo JWTs line up with seeded rows.
AGENCIES = [
    ("a190a9ca-d827-5c3a-a625-b788d9ab03c9", "Bareskrim Polri", "police"),
    ("84cb96f6-6dfb-5e5f-9fbd-d06ce68e7772", "PPATK", "regulator"),
    ("f9c7eca7-d56c-5317-8b94-b4cdea4d371c", "OJK", "regulator"),
    ("2f619ed4-47f0-5e4f-8c4d-47e37081b582", "Bank BCA", "bank"),
    ("62645fb4-48bd-5b49-8aa7-d1123371838a", "Indodax", "exchange"),
]

ROLES = [
    ("regulator-analyst", "regulator"),
    ("police-investigator", "police"),
    ("bank-compliance", "bank"),
    ("exchange-compliance", "exchange"),
    ("agency-admin", None),
    ("platform-admin", None),
]


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS "core"')

    op.create_table(
        "agencies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("onprem", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "type in ('regulator','police','bank','exchange','other')",
            name="ck_agencies_type"),
        schema="core",
    )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agency_id", sa.Uuid(), sa.ForeignKey("core.agencies.id"),
                  nullable=False, index=True),
        sa.Column("oauth_sub", sa.Text(), unique=True),
        sa.Column("email", sa.Text(), nullable=False, unique=True),  # citext in prod
        sa.Column("name", sa.Text()),
        sa.Column("role", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "role in ('regulator-analyst','police-investigator','bank-compliance',"
            "'exchange-compliance','agency-admin','platform-admin')",
            name="ck_users_role"),
        schema="core",
    )

    op.create_table(
        "roles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False, unique=True),
        sa.Column("agency_type", sa.Text()),
        sa.Column("permissions", JSONB()),
        schema="core",
    )

    op.create_table(
        "cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agency_id", sa.Uuid(), sa.ForeignKey("core.agencies.id"),
                  nullable=False, index=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="open"),
        sa.Column("crime_type", sa.Text()),
        sa.Column("summary", sa.Text()),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("core.users.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status in ('open','active','closed','archived')",
                           name="ck_cases_status"),
        sa.CheckConstraint("data_mode in ('poc','live')", name="ck_cases_data_mode"),
        schema="core",
    )

    op.create_table(
        "case_shares",
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("core.cases.id"), primary_key=True),
        sa.Column("agency_id", sa.Uuid(), sa.ForeignKey("core.agencies.id"),
                  primary_key=True),  # grantee
        sa.Column("access", sa.Text(), nullable=False, server_default="read"),
        sa.Column("granted_by", sa.Uuid(), sa.ForeignKey("core.users.id")),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("access in ('read','contribute')", name="ck_case_shares_access"),
        schema="core",
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agency_id", sa.Uuid(), nullable=False, index=True),
        sa.Column("actor_user_id", sa.Uuid()),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("target_type", sa.Text()),
        sa.Column("target_id", sa.Uuid()),
        sa.Column("detail", JSONB()),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("seq", sa.BigInteger()),
        sa.Column("sha256", BYTEA()),
        sa.Column("prev_sha256", BYTEA()),
        schema="core",
    )

    # ------------------------------------------------------------------ RLS --
    # Helper: the request's agency, NULL when unset (missing_ok) → fail closed.
    op.execute("""
        CREATE OR REPLACE FUNCTION core.current_agency() RETURNS uuid
        LANGUAGE sql STABLE AS
        $$ SELECT nullif(current_setting('app.current_agency', true), '')::uuid $$
    """)
    # SECURITY DEFINER helpers break the cases ⇄ case_shares policy recursion:
    # they run as the table OWNER (RLS-exempt without FORCE), so each policy can
    # consult the other table without re-triggering its policy.
    op.execute("""
        CREATE OR REPLACE FUNCTION core.shared_case_ids() RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = core, pg_temp AS
        $$ SELECT case_id FROM core.case_shares
           WHERE agency_id = core.current_agency() $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION core.owned_case_ids() RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = core, pg_temp AS
        $$ SELECT id FROM core.cases
           WHERE agency_id = core.current_agency() $$
    """)

    # agencies / roles — global directories: readable by all authenticated
    # tenants (names are needed for share pickers), writable only by the
    # owner/migration role (RLS enabled + no write policy = deny).
    op.execute("ALTER TABLE core.agencies ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY agencies_read ON core.agencies FOR SELECT USING (true)")
    op.execute("ALTER TABLE core.roles ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY roles_read ON core.roles FOR SELECT USING (true)")

    # users — own agency's users, plus always yourself.
    op.execute("ALTER TABLE core.users ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY users_access ON core.users
        USING (
            agency_id = core.current_agency()
            OR id = nullif(current_setting('app.current_user', true), '')::uuid
        )
        WITH CHECK (agency_id = core.current_agency())
    """)

    # cases — THE baseline policy: owning agency OR explicitly shared.
    op.execute("ALTER TABLE core.cases ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY cases_access ON core.cases
        USING (
            agency_id = core.current_agency()
            OR id IN (SELECT core.shared_case_ids())
        )
        WITH CHECK (agency_id = core.current_agency())
    """)

    # case_shares — grantee sees their grants; the case OWNER manages grants.
    op.execute("ALTER TABLE core.case_shares ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY case_shares_access ON core.case_shares
        USING (
            agency_id = core.current_agency()
            OR case_id IN (SELECT core.owned_case_ids())
        )
        WITH CHECK (case_id IN (SELECT core.owned_case_ids()))
    """)

    # audit_log — append-only per agency: SELECT + INSERT only (no UPDATE/DELETE
    # policy → denied). Hash chain makes any owner-side tampering detectable.
    op.execute("ALTER TABLE core.audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY audit_read ON core.audit_log
        FOR SELECT USING (agency_id = core.current_agency())
    """)
    op.execute("""
        CREATE POLICY audit_insert ON core.audit_log
        FOR INSERT WITH CHECK (agency_id = core.current_agency())
    """)

    # ----------------------------------------------------------------- Seed --
    # Static, trusted constants — inlined so `alembic upgrade head --sql`
    # (offline verification, no Postgres) renders cleanly.
    for agency_id, name, agency_type in AGENCIES:
        op.execute(
            f"INSERT INTO core.agencies (id, name, type) "
            f"VALUES ('{agency_id}', '{name}', '{agency_type}') "
            f"ON CONFLICT (id) DO NOTHING"
        )
    for role_name, agency_type in ROLES:
        atype = f"'{agency_type}'" if agency_type is not None else "NULL"
        op.execute(
            f"INSERT INTO core.roles (id, name, agency_type) "
            f"VALUES (gen_random_uuid(), '{role_name}', {atype}) "
            f"ON CONFLICT (name) DO NOTHING"
        )


def downgrade() -> None:
    op.drop_table("audit_log", schema="core")
    op.drop_table("case_shares", schema="core")
    op.drop_table("cases", schema="core")
    op.drop_table("roles", schema="core")
    op.drop_table("users", schema="core")
    op.drop_table("agencies", schema="core")
    op.execute("DROP FUNCTION IF EXISTS core.owned_case_ids()")
    op.execute("DROP FUNCTION IF EXISTS core.shared_case_ids()")
    op.execute("DROP FUNCTION IF EXISTS core.current_agency()")
    op.execute('DROP SCHEMA IF EXISTS "core"')
