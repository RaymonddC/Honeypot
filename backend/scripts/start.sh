#!/usr/bin/env sh
# Container entrypoint: auto-migrate (when configured), then serve.
#
# Alembic runs ONLY under postgres persistence AND with an owner/migration URL.
# The app connects as the non-owning `ittu_app` role (RLS-subject) which can't
# run DDL, so migrations use ITTU_MIGRATION_DATABASE_URL (the owning role).
# `alembic upgrade head` is idempotent — a fast no-op once the DB is at head —
# so it's safe to run on every container start. A failed migration aborts
# startup on purpose: never serve app code against an un-migrated schema.
set -e

if [ "$ITTU_PERSISTENCE" = "postgres" ] && [ -n "$ITTU_MIGRATION_DATABASE_URL" ]; then
  echo "[entrypoint] ITTU_PERSISTENCE=postgres -> alembic upgrade head"
  alembic upgrade head
else
  echo "[entrypoint] skipping migrations (persistence=${ITTU_PERSISTENCE:-memory}, migration_url ${ITTU_MIGRATION_DATABASE_URL:+set})"
fi

# Bind to $PORT when the platform provides one (Render/Fly/Cloud Run); else 8000.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
