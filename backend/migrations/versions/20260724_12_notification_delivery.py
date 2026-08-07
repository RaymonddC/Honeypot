"""action.notifications delivery lifecycle (C1: production-ready dispatch).

Additive only. The dispatch→notify loop already persisted a notification row
per target agency, but with a *one-shot* status (mock/queued/sent/failed) and
no delivery metadata — so a real LIVE deployment couldn't retry a failed
webhook, prove authenticity, or dedupe a redelivery. This migration adds the
columns the durable delivery path (the ``dispatch_notifications`` Dramatiq
actor) needs, and widens the status check to include the ``sending`` in-flight
state:

- ``idempotency_key text UNIQUE`` — the token echoed to the recipient
  (``X-ITTU-Idempotency-Key`` header + packet) so an at-least-once retry never
  double-actions a freeze/STR at the agency.
- ``attempt_count int NOT NULL DEFAULT 0`` — delivery attempts made.
- ``last_error text`` — last failure reason (HTTP status / transport error).
- ``updated_at timestamptz NOT NULL DEFAULT now()`` — bumped on every status
  transition.

The table is still (per migrations 07/08) only ever written by the P-3
Postgres repository, so the new NOT NULL columns have sane server defaults and
need no backfill. RLS is untouched (the row's ``agency_id`` policy from
migration 06 still governs every read/write).

Revision ID: 20260724_12
Revises: 20260723_11
Create Date: 2026-07-24
"""

import sqlalchemy as sa
from alembic import op

revision = "20260724_12"
down_revision = "20260723_11"
branch_labels = None
depends_on = None

_OLD_STATUS = "status in ('mock','queued','sent','failed')"
_NEW_STATUS = "status in ('mock','queued','sending','sent','failed')"


def upgrade() -> None:
    op.add_column(
        "notifications", sa.Column("idempotency_key", sa.Text()), schema="action"
    )
    op.create_unique_constraint(
        "uq_action_notifications_idempotency_key",
        "notifications", ["idempotency_key"], schema="action",
    )
    op.add_column(
        "notifications",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        schema="action",
    )
    op.add_column(
        "notifications", sa.Column("last_error", sa.Text()), schema="action"
    )
    op.add_column(
        "notifications",
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        schema="action",
    )

    # Widen the status check to admit the in-flight 'sending' state.
    op.drop_constraint("ck_notifications_status", "notifications",
                       schema="action", type_="check")
    op.create_check_constraint("ck_notifications_status", "notifications",
                               _NEW_STATUS, schema="action")


def downgrade() -> None:
    op.drop_constraint("ck_notifications_status", "notifications",
                       schema="action", type_="check")
    op.create_check_constraint("ck_notifications_status", "notifications",
                               _OLD_STATUS, schema="action")

    op.drop_column("notifications", "updated_at", schema="action")
    op.drop_column("notifications", "last_error", schema="action")
    op.drop_column("notifications", "attempt_count", schema="action")
    op.drop_constraint("uq_action_notifications_idempotency_key",
                       "notifications", schema="action", type_="unique")
    op.drop_column("notifications", "idempotency_key", schema="action")
