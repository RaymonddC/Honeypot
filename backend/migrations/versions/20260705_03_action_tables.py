"""action schema: action_documents, notifications (UNCOVER)

Revision ID: 20260705_03
Revises: 20260705_02
Create Date: 2026-07-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260705_03"
down_revision = "20260705_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS action")

    op.create_table(
        "action_documents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), index=True),
        sa.Column("agency_id", sa.Uuid(), index=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("format", sa.Text()),
        sa.Column("content_ref", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("generated_by", sa.Uuid()),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("sha256", sa.LargeBinary()),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.CheckConstraint("type in ('account_blocking','str_report','summary')",
                           name="ck_action_documents_type"),
        sa.CheckConstraint("status in ('draft','issued','acknowledged')",
                           name="ck_action_documents_status"),
        sa.CheckConstraint("data_mode in ('poc','live')",
                           name="ck_action_documents_data_mode"),
        schema="action",
    )

    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), index=True),
        sa.Column("target_agency_id", sa.Uuid(), index=True),
        sa.Column("channel", sa.Text()),
        sa.Column("payload", JSONB()),
        sa.Column("status", sa.Text(), nullable=False, server_default="mock"),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column("sent_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("status in ('mock','queued','sent','failed')",
                           name="ck_notifications_status"),
        sa.CheckConstraint("data_mode in ('poc','live')",
                           name="ck_notifications_data_mode"),
        schema="action",
    )


def downgrade() -> None:
    op.drop_table("notifications", schema="action")
    op.drop_table("action_documents", schema="action")
    op.execute("DROP SCHEMA IF EXISTS action")
