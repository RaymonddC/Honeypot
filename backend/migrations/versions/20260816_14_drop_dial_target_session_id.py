"""drop honeypot.dial_targets.session_id — the call log is one-to-many.

Phase 4 of docs/Voice-Honeypot-Outbound.md (§3.3). Migration 20260816_13 gave
``dial_targets`` a nullable ``session_id`` FK on the assumption that a target is
dialed once. **Requeue** (§3.6) breaks that assumption: an operator resets a
finished target back to ``queued`` and it is dialed again, so one target
accumulates MANY calls over time.

A single ``session_id`` can then only mean "the first call" or "the latest call"
— ambiguous either way, and both readings silently lose history. The reverse
side, ``intel.scam_sessions.dial_target_id`` (added in the same migration 13),
already expresses the true cardinality: many sessions → one target. It is
therefore the call log, and ``session_id`` is redundant. Dropping it now, before
phase 4's dialer writes to it, avoids code depending on an ambiguous column.

Dropping this column also removes the ``dial_targets ⇄ scam_sessions`` FK cycle
that forced migration 13 to add the ``scam_sessions`` FK by a trailing ALTER (and
to mark the ORM relationship ``use_alter=True``). The remaining reference is
one-directional (sessions → targets), so the ORM's ``use_alter`` is dropped in
the same commit. The ``fk_scam_sessions_dial_target_id`` constraint itself is
untouched — its name and definition are unchanged, only how SQLAlchemy orders
table creation.

No data migration: nothing writes ``session_id`` yet (phase 3 shipped CRUD only),
so every existing row has NULL there.

Revision ID: 20260816_14
Revises: 20260816_13
Create Date: 2026-08-16
"""

import sqlalchemy as sa
from alembic import op

revision = "20260816_14"
down_revision = "20260816_13"
branch_labels = None
depends_on = None

SCHEMA = "honeypot"


def upgrade() -> None:
    # The column's FK to intel.scam_sessions and its index are dropped with it.
    op.drop_column("dial_targets", "session_id", schema=SCHEMA)


def downgrade() -> None:
    # Restore the column exactly as migration 13 created it (nullable, indexed,
    # FK to intel.scam_sessions). Re-creating the cycle is fine on the way down:
    # both tables already exist, so the FK can be created inline.
    op.add_column(
        "dial_targets",
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("intel.scam_sessions.id")),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_honeypot_dial_targets_session_id", "dial_targets", ["session_id"], schema=SCHEMA
    )
