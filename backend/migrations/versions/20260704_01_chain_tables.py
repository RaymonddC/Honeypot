"""chain schema: wallets, transactions, wallet_features, wallet_risk_scores, address_tags

Revision ID: 20260704_01
Revises:
Create Date: 2026-07-04
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260704_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS chain")

    op.create_table(
        "wallets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("address", sa.Text(), nullable=False, index=True),
        sa.Column("chain", sa.Text(), nullable=False),
        sa.Column("first_seen", sa.DateTime(timezone=True)),
        sa.Column("last_seen", sa.DateTime(timezone=True)),
        sa.Column("native_balance", sa.Numeric()),
        sa.Column("source", sa.Text()),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("address", "chain", name="uq_wallets_address_chain"),
        sa.CheckConstraint("chain in ('btc','eth','tron','bsc')", name="ck_wallets_chain"),
        sa.CheckConstraint("data_mode in ('poc','live')", name="ck_wallets_data_mode"),
        schema="chain",
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tx_hash", sa.Text(), nullable=False, index=True),
        sa.Column("chain", sa.Text(), nullable=False),
        sa.Column("from_addr", sa.Text(), nullable=False, index=True),
        sa.Column("to_addr", sa.Text(), nullable=False, index=True),
        sa.Column("value", sa.Numeric(), nullable=False),
        sa.Column("token_symbol", sa.Text()),
        sa.Column("token_contract", sa.Text()),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("block_number", sa.BigInteger()),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column("raw", JSONB()),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("chain", "tx_hash", "from_addr", "to_addr",
                            name="uq_transactions_ingest"),
        sa.CheckConstraint("data_mode in ('poc','live')", name="ck_transactions_data_mode"),
        schema="chain",
    )

    op.create_table(
        "wallet_features",
        sa.Column("wallet_id", sa.Uuid(), sa.ForeignKey("chain.wallets.id"), primary_key=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), primary_key=True,
                  server_default=sa.text("now()")),
        sa.Column("tx_velocity", sa.Numeric()),
        sa.Column("total_volume", sa.Numeric()),
        sa.Column("mean_volume", sa.Numeric()),
        sa.Column("unique_counterparties", sa.Integer()),
        sa.Column("rapid_relay_rate", sa.Numeric()),
        sa.Column("round_number_pct", sa.Numeric()),
        sa.Column("fan_ratio", sa.Numeric()),
        sa.Column("account_age_days", sa.Integer()),
        sa.Column("inout_ratio", sa.Numeric()),
        sa.Column("time_entropy", sa.Numeric()),
        sa.Column("chain_depth", sa.Integer()),
        sa.Column("self_loop_count", sa.Integer()),
        sa.Column("max_tx_size", sa.Numeric()),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.CheckConstraint("data_mode in ('poc','live')", name="ck_wallet_features_data_mode"),
        schema="chain",
    )

    op.create_table(
        "wallet_risk_scores",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("wallet_id", sa.Uuid(), sa.ForeignKey("chain.wallets.id"), index=True),
        sa.Column("iso_forest_score", sa.Numeric()),
        sa.Column("typology_flags", JSONB()),
        sa.Column("composite_risk", sa.Text()),
        sa.Column("confidence", sa.Numeric()),
        sa.Column("reasoning", sa.Text()),
        sa.Column("model_version", sa.Text()),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.CheckConstraint("composite_risk in ('low','medium','high')",
                           name="ck_wallet_risk_scores_composite"),
        sa.CheckConstraint("data_mode in ('poc','live')", name="ck_wallet_risk_scores_data_mode"),
        schema="chain",
    )

    op.create_table(
        "address_tags",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("address", sa.Text(), nullable=False, index=True),
        sa.Column("chain", sa.Text(), nullable=False),
        sa.Column("tag", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric()),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.UniqueConstraint("address", "chain", "source", name="uq_address_tags"),
        sa.CheckConstraint(
            "category in ('exchange','mixer','scam','gambling','sanctioned','service','unknown')",
            name="ck_address_tags_category"),
        schema="chain",
    )


def downgrade() -> None:
    op.drop_table("address_tags", schema="chain")
    op.drop_table("wallet_risk_scores", schema="chain")
    op.drop_table("wallet_features", schema="chain")
    op.drop_table("transactions", schema="chain")
    op.drop_table("wallets", schema="chain")
    op.execute("DROP SCHEMA IF EXISTS chain")
