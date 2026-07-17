"""core.users login helpers (P-4b, docs/Persistence-Plan.md P-4) — SECURITY
DEFINER functions + the same 6 demo users app/core/auth.py seeds in-memory.

**The gap this closes:** login happens BEFORE there's a verified identity, but
``core.users`` carries RLS (migration 20260708_05's ``users_access`` — own
agency OR self). A normal ``app.core.db.get_tenant_session`` query at login
would see NOTHING: both ``app.current_agency``/``app.current_user`` are NULL
pre-auth, and the policy fails closed on NULL, not open. Worse,
``get_tenant_session`` itself depends on ``get_current_user`` — it cannot be
used at login at all, RLS aside (chicken-and-egg).

Same fix migration 05 already used for the ``cases``/``case_shares`` policy
recursion: three narrow ``SECURITY DEFINER`` functions, owned by the
migration/owner role, that read/write ``core.users`` WITHOUT the tenant RLS
context. They run as the table owner (RLS-exempt without ``FORCE ROW LEVEL
SECURITY``, which isn't set) regardless of which role calls them — including
``ittu_app``, the non-superuser role the app actually connects as. This is a
narrow, pre-auth boundary confined to these three functions; it is never a
general-purpose RLS bypass, and every OTHER read/write of ``core.users`` still
goes through the normal RLS-scoped session.

- ``core.login_find_user_by_email(p_email)`` — the LIVE Google path's
  "is this email provisioned?" check.
- ``core.login_find_user_by_agency_role(p_agency_id, p_role)`` — the POC demo
  path's "does a user already exist for this (agency, role)?" check, so demo
  login resolves to the canonical seeded person (e.g. Budi) rather than
  minting a duplicate placeholder.
- ``core.login_upsert_user(...)`` — insert-or-update by id, stamping
  ``last_login_at = now()`` (a column migration 05 added but nothing has
  written until now).

No ALTER TABLE: ``core.users`` (migration 05) already has every column
``app.core.auth.SeedUser``/``AuthContext`` need (id, agency_id, email, name,
role) plus ones this migration is the first to actually use
(``last_login_at``). ``is_active``/``oauth_sub`` stay unused — out of scope
for this pass.

**Seed the 6 demo users.** ``app.core.auth.upsert_demo_user`` finds an
existing user by (agency_id, role) FIRST, only synthesizing+minting a new one
on a miss — that's how demo login resolves to the real seeded people (Budi,
Sari, Dewi, Andi, Rina, the platform admin) instead of a
"<role>@<agency>.demo.ittu.id" placeholder. If ``core.users`` started empty,
the first postgres-mode login for any seeded (agency, role) pair would MISS
and mint a different user than the memory path gives for the identical
request — breaking the "same JWT" invariant the whole persistence effort
depends on (deterministic uuid5 ids already line up; see
app/core/auth.py:SEED_USERS). So this migration seeds the same 6 rows
migration 05's AGENCIES/ROLES seed mirrors — static, trusted constants,
inlined (ids computed offline via ``uuid.uuid5(NAMESPACE_URL, "ittu:user:<email>")``,
matching ``app.core.auth._user_id``) so ``alembic upgrade head --sql`` still
renders cleanly with no Postgres running.

Revision ID: 20260717_09
Revises: 20260717_08
Create Date: 2026-07-17
"""

from alembic import op

revision = "20260717_09"
down_revision = "20260717_08"
branch_labels = None
depends_on = None

# (user_id, agency_id, email, name, role) — ids match app/core/auth.py
# SEED_USERS exactly (uuid5(NAMESPACE_URL, f"ittu:user:{email}")).
SEED_USERS = [
    ("9f79eb96-3e3a-57b1-a617-311a785553a1", "a190a9ca-d827-5c3a-a625-b788d9ab03c9",
     "budi@bareskrim.polri.go.id", "Budi Santoso", "police-investigator"),
    ("ae74ef08-7784-5fce-a775-5c5ec3b16c40", "84cb96f6-6dfb-5e5f-9fbd-d06ce68e7772",
     "sari@ppatk.go.id", "Sari Wulandari", "regulator-analyst"),
    ("05e217d2-fc60-5c78-8387-c9291a44f00e", "f9c7eca7-d56c-5317-8b94-b4cdea4d371c",
     "dewi@ojk.go.id", "Dewi Lestari", "regulator-analyst"),
    ("6ef9ea9a-5d76-5e7b-89ec-bf86ac0416f6", "2f619ed4-47f0-5e4f-8c4d-47e37081b582",
     "andi@bca.co.id", "Andi Wijaya", "bank-compliance"),
    ("051affd1-3dc1-5d6f-8162-1d06c1bf67a3", "62645fb4-48bd-5b49-8aa7-d1123371838a",
     "rina@indodax.com", "Rina Hartono", "exchange-compliance"),
    ("04eb0d53-54a9-5027-b422-d26913d1de75", "84cb96f6-6dfb-5e5f-9fbd-d06ce68e7772",
     "admin@ittu.id", "ITTU Platform Admin", "platform-admin"),
]


def upgrade() -> None:
    # -- SECURITY DEFINER login helpers --------------------------------------
    # STABLE + SQL: pure reads, no writes, so they may run inside any
    # transaction (including a read-only one) without side effects.
    op.execute("""
        CREATE OR REPLACE FUNCTION core.login_find_user_by_email(p_email text)
        RETURNS SETOF core.users
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = core, pg_temp AS
        $$ SELECT * FROM core.users WHERE email = p_email $$
    """)
    op.execute("""
        CREATE OR REPLACE FUNCTION core.login_find_user_by_agency_role(
            p_agency_id uuid, p_role text
        )
        RETURNS SETOF core.users
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = core, pg_temp AS
        $$ SELECT * FROM core.users
           WHERE agency_id = p_agency_id AND role = p_role
           ORDER BY created_at LIMIT 1 $$
    """)
    # VOLATILE (default) — the one write path. Upsert by id (the app already
    # computes a deterministic uuid5 id from the email — see app/core/auth.py
    # _user_id), refreshing email/name/role and stamping last_login_at.
    op.execute("""
        CREATE OR REPLACE FUNCTION core.login_upsert_user(
            p_id uuid, p_agency_id uuid, p_email text, p_name text,
            p_role text, p_oauth_sub text
        )
        RETURNS SETOF core.users
        LANGUAGE sql SECURITY DEFINER SET search_path = core, pg_temp AS
        $$
            INSERT INTO core.users (id, agency_id, email, name, role, oauth_sub, last_login_at)
            VALUES (p_id, p_agency_id, p_email, p_name, p_role, p_oauth_sub, now())
            ON CONFLICT (id) DO UPDATE SET
                agency_id = EXCLUDED.agency_id,
                email = EXCLUDED.email,
                name = EXCLUDED.name,
                role = EXCLUDED.role,
                oauth_sub = COALESCE(EXCLUDED.oauth_sub, core.users.oauth_sub),
                last_login_at = now(),
                updated_at = now()
            RETURNING *
        $$
    """)

    # ----------------------------------------------------------------- Seed --
    # Static, trusted constants — inlined so `alembic upgrade head --sql`
    # (offline verification, no Postgres) renders cleanly, same as migration
    # 20260708_05's AGENCIES/ROLES seed.
    for user_id, agency_id, email, name, role in SEED_USERS:
        name_sql = name.replace("'", "''")
        op.execute(
            f"INSERT INTO core.users (id, agency_id, email, name, role) "
            f"VALUES ('{user_id}', '{agency_id}', '{email}', '{name_sql}', '{role}') "
            f"ON CONFLICT (id) DO NOTHING"
        )


def downgrade() -> None:
    for user_id, _agency_id, _email, _name, _role in SEED_USERS:
        op.execute(f"DELETE FROM core.users WHERE id = '{user_id}'")
    op.execute("DROP FUNCTION IF EXISTS core.login_upsert_user(uuid, uuid, text, text, text, text)")
    op.execute("DROP FUNCTION IF EXISTS core.login_find_user_by_agency_role(uuid, text)")
    op.execute("DROP FUNCTION IF EXISTS core.login_find_user_by_email(text)")
