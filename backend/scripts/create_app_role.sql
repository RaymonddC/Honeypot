-- backend/scripts/create_app_role.sql
--
-- Creates the non-superuser, NON-OWNING Postgres role the ITTU backend must
-- connect as for Row-Level Security to actually take effect. Table owners and
-- superusers bypass RLS entirely (docs/Persistence-Plan.md P-1, migration
-- 20260708_05, docs/Security-Evidence.md §2) — so the app can never connect as
-- the role that ran the migrations.
--
-- Run this ONCE per database/environment, connected as the OWNING/migration
-- role (the one `alembic upgrade head` ran as), AFTER migrations have created
-- the schemas + tables:
--
--   psql "$MIGRATION_DATABASE_URL" -v app_role_password='<a-strong-password>' \
--        -f backend/scripts/create_app_role.sql
--
-- (no extra quoting needed in the -v value — psql's :'var' substitution below
-- quotes/escapes it safely as a SQL literal.)
--
-- Then point the app at the NEW role, not the owning one:
--
--   ITTU_DATABASE_URL=postgresql+asyncpg://ittu_app:<password>@<host>/<db>
--
-- Idempotent: safe to re-run after every migration (GRANTs are naturally
-- idempotent; role creation is guarded).
--
-- ⚠️ NEON CAVEAT: the role in the connection string Neon's dashboard hands you
-- by default OWNS every table it creates (it's the one migrations ran as) and
-- therefore BYPASSES RLS entirely. If ITTU_DATABASE_URL uses that role, every
-- RLS policy from migrations 05/06 is a silent no-op — the app sees ALL
-- agencies' rows regardless of app.current_agency, with no error to warn you.
-- You MUST run this script against the Neon database (as the owning role) to
-- create ittu_app as a SEPARATE, non-owning role, then set ITTU_DATABASE_URL to
-- ittu_app's connection string — never the owner's. See docs/Deploy.md.

-- NB: the guarded CREATE ROLE below deliberately does NOT use a PL/pgSQL DO
-- block — psql's `:'var'` interpolation is NOT performed inside dollar-quoted
-- ($$...$$) bodies, so a DO block would send the literal, unsubstituted text
-- ":'app_role_password'" to the server. \if/\gset are plain psql meta-commands
-- and interpolate normally.
SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ittu_app') AS role_exists \gset
\if :role_exists
    \echo 'role ittu_app already exists — skipping CREATE ROLE (use ALTER ROLE ittu_app PASSWORD ... to rotate the password)'
\else
    CREATE ROLE ittu_app LOGIN PASSWORD :'app_role_password';
\endif

-- Schema access: the app needs to see the schemas to resolve unqualified names.
GRANT USAGE ON SCHEMA core, intel, chain, fiat, action, casedata, honeypot TO ittu_app;

-- Row-level data access. RLS policies (migrations 05/06) then restrict WHICH
-- rows are visible/writable within these grants — this is table-level
-- read/write permission, not tenant isolation (RLS's job, enforced separately).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA core TO ittu_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA intel TO ittu_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA chain TO ittu_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA fiat TO ittu_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA action TO ittu_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA casedata TO ittu_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA honeypot TO ittu_app;

-- Sequences (SERIAL/IDENTITY columns, if any land later) need USAGE for nextval().
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA core TO ittu_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA intel TO ittu_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA chain TO ittu_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA fiat TO ittu_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA action TO ittu_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA casedata TO ittu_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA honeypot TO ittu_app;

-- Future tables/sequences created by later migrations (run AS the owning role)
-- get the same grants automatically — this script does not need to be re-run
-- after every new migration, only when a NEW schema is introduced.
ALTER DEFAULT PRIVILEGES IN SCHEMA core
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ittu_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA intel
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ittu_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA chain
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ittu_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA fiat
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ittu_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA action
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ittu_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA casedata
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ittu_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA honeypot
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ittu_app;
