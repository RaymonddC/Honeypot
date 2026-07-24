"""core.cases.stage — the investigation lifecycle stage (case-centric flow).

``core.cases.status`` is coarse (open/active/closed/archived). The case-centric
UI needs the finer investigation *stage* an analyst walks a case through:
intake → freeze → trace → takedown → report → recovery → closed. Added nullable
with a server default of ``intake`` (existing rows adopt it); RLS on core.cases
is unchanged (migration 20260708_05).

Revision ID: 20260723_11
Revises: 20260723_10
Create Date: 2026-07-23
"""

import sqlalchemy as sa
from alembic import op

revision = "20260723_11"
down_revision = "20260723_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cases",
        sa.Column("stage", sa.Text(), nullable=False, server_default="intake"),
        schema="core",
    )


def downgrade() -> None:
    op.drop_column("cases", "stage", schema="core")
