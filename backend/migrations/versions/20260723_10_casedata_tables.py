"""casedata schema: analyst-entered bank_accounts + crypto_transfers, agency-scoped RLS.

Two tables backing the CASEDATA module (app/casedata) — records an investigator
adds by hand that feed the existing engines: bank accounts surface on the TRACE
Bridge watchlist; crypto transfers merge into the TAKEDOWN Investigation graph.

Both are agency-owned, so they get ``agency_id`` + the same RLS shape as the
intel/action tables (migration 20260715_06): ``core.current_agency()``,
fail-closed on NULL. ``data_mode`` isolates POC vs LIVE rows.

Revision ID: 20260723_10
Revises: 20260717_09
Create Date: 2026-07-23
"""

import sqlalchemy as sa
from alembic import op

revision = "20260723_10"
down_revision = "20260717_09"
branch_labels = None
depends_on = None

SCHEMA = "casedata"


def _enable_rls(table: str) -> None:
    op.execute(f'ALTER TABLE "{SCHEMA}".{table} ENABLE ROW LEVEL SECURITY')
    op.execute(
        f"""
        CREATE POLICY {table}_access ON "{SCHEMA}".{table}
        USING (agency_id = core.current_agency())
        WITH CHECK (agency_id = core.current_agency())
        """
    )


def _disable_rls(table: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS {table}_access ON "{SCHEMA}".{table}')
    op.execute(f'ALTER TABLE "{SCHEMA}".{table} DISABLE ROW LEVEL SECURITY')


def upgrade() -> None:
    op.execute(f'CREATE SCHEMA IF NOT EXISTS "{SCHEMA}"')

    op.create_table(
        "bank_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "agency_id", sa.Uuid(), sa.ForeignKey("core.agencies.id"), nullable=False, index=True
        ),
        sa.Column("bank_name", sa.Text(), nullable=False),
        sa.Column("account_number", sa.Text(), nullable=False),
        sa.Column("holder_name", sa.Text()),
        sa.Column("category", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("case_id", sa.Text()),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("data_mode in ('poc','live')", name="ck_bank_accounts_data_mode"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_casedata_bank_accounts_number", "bank_accounts", ["account_number"], schema=SCHEMA
    )
    _enable_rls("bank_accounts")

    op.create_table(
        "crypto_transfers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "agency_id", sa.Uuid(), sa.ForeignKey("core.agencies.id"), nullable=False, index=True
        ),
        sa.Column("tx_hash", sa.Text(), nullable=False),
        sa.Column("from_addr", sa.Text(), nullable=False),
        sa.Column("to_addr", sa.Text(), nullable=False),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("chain", sa.Text(), nullable=False, server_default="tron"),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("category", sa.Text(), nullable=False, server_default="unknown"),
        sa.Column("note", sa.Text(), nullable=False, server_default=""),
        sa.Column("case_id", sa.Text()),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint("data_mode in ('poc','live')", name="ck_crypto_transfers_data_mode"),
        schema=SCHEMA,
    )
    op.create_index(
        "ix_casedata_crypto_transfers_from", "crypto_transfers", ["from_addr"], schema=SCHEMA
    )
    op.create_index(
        "ix_casedata_crypto_transfers_to", "crypto_transfers", ["to_addr"], schema=SCHEMA
    )
    _enable_rls("crypto_transfers")


def downgrade() -> None:
    _disable_rls("crypto_transfers")
    op.drop_table("crypto_transfers", schema=SCHEMA)
    _disable_rls("bank_accounts")
    op.drop_table("bank_accounts", schema=SCHEMA)
    op.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}"')
