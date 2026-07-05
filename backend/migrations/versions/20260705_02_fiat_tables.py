"""fiat schema: fiat_accounts, fiat_transactions, correlations (TRACE / BridgeWatch)

Revision ID: 20260705_02
Revises: 20260704_01
Create Date: 2026-07-05
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260705_02"
down_revision = "20260704_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS fiat")

    op.create_table(
        "fiat_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("account_number", sa.Text(), nullable=False, index=True),
        sa.Column("bank_name", sa.Text(), nullable=False),
        sa.Column("holder_name", sa.Text()),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column("source", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("account_number", "bank_name",
                            name="uq_fiat_accounts_number_bank"),
        sa.CheckConstraint("data_mode in ('poc','live')", name="ck_fiat_accounts_data_mode"),
        schema="fiat",
    )

    op.create_table(
        "fiat_transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("from_account_id", sa.Uuid(),
                  sa.ForeignKey("fiat.fiat_accounts.id"), index=True),
        sa.Column("to_account_id", sa.Uuid(),
                  sa.ForeignKey("fiat.fiat_accounts.id"), index=True),
        sa.Column("amount", sa.Numeric(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column("raw", JSONB()),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("channel in ('transfer','qris','ewallet')",
                           name="ck_fiat_transactions_channel"),
        sa.CheckConstraint("data_mode in ('poc','live')",
                           name="ck_fiat_transactions_data_mode"),
        schema="fiat",
    )

    op.create_table(
        "correlations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), index=True),
        sa.Column("fiat_tx_id", sa.Uuid(),
                  sa.ForeignKey("fiat.fiat_transactions.id"), nullable=False, index=True),
        sa.Column("crypto_tx_id", sa.Uuid(),
                  sa.ForeignKey("chain.transactions.id"), nullable=False, index=True),
        sa.Column("time_delta_seconds", sa.Integer(), nullable=False),
        sa.Column("amount_match", sa.Numeric(), nullable=False),
        sa.Column("confidence", sa.Numeric(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("data_mode in ('poc','live')",
                           name="ck_correlations_data_mode"),
        schema="fiat",
    )


def downgrade() -> None:
    op.drop_table("correlations", schema="fiat")
    op.drop_table("fiat_transactions", schema="fiat")
    op.drop_table("fiat_accounts", schema="fiat")
    op.execute("DROP SCHEMA IF EXISTS fiat")
