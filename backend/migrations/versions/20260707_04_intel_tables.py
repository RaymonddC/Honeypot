"""intel schema: personas, scam_sessions, messages, entities, syndicates,
syndicate_members, crime_classifications (INFILTRATE)

Revision ID: 20260707_04
Revises: 20260705_03
Create Date: 2026-07-07
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260707_04"
down_revision = "20260705_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS intel")

    op.create_table(
        "personas",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("profile", JSONB()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        schema="intel",
    )

    op.create_table(
        "scam_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), index=True),
        sa.Column("agency_id", sa.Uuid(), index=True),
        sa.Column("persona_id", sa.Uuid(), sa.ForeignKey("intel.personas.id"), index=True),
        sa.Column("channel_type", sa.Text(), nullable=False, server_default="text"),
        sa.Column("channel", sa.Text()),
        sa.Column("channel_ref", sa.Text()),
        sa.Column("crime_type", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("channel_type in ('text','voice')",
                           name="ck_scam_sessions_channel_type"),
        sa.CheckConstraint("status in ('active','escalated','closed')",
                           name="ck_scam_sessions_status"),
        sa.CheckConstraint("data_mode in ('poc','live')",
                           name="ck_scam_sessions_data_mode"),
        schema="intel",
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("intel.scam_sessions.id"),
                  nullable=False, index=True),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("content", sa.Text()),
        sa.Column("audio_ref", sa.Text()),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("sha256", sa.LargeBinary()),
        sa.Column("prev_sha256", sa.LargeBinary()),
        sa.Column("meta", JSONB()),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.CheckConstraint("direction in ('inbound','outbound')",
                           name="ck_messages_direction"),
        sa.CheckConstraint("data_mode in ('poc','live')", name="ck_messages_data_mode"),
        sa.UniqueConstraint("session_id", "seq", name="uq_messages_session_seq"),
        schema="intel",
    )

    op.create_table(
        "entities",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("intel.scam_sessions.id"),
                  index=True),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("intel.messages.id"), index=True),
        sa.Column("agency_id", sa.Uuid()),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("normalized_value", sa.Text()),
        sa.Column("chain", sa.Text()),
        sa.Column("bank_name", sa.Text()),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("review_status", sa.Text(), nullable=False, server_default="unverified"),
        sa.Column("provenance", JSONB()),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            "type in ('bank_account','crypto_wallet','phone','url','person','org','alias')",
            name="ck_entities_type"),
        sa.CheckConstraint("method in ('regex','llm','ner','human')",
                           name="ck_entities_method"),
        sa.CheckConstraint(
            "review_status in ('unverified','confirmed','rejected','poisoned')",
            name="ck_entities_review_status"),
        sa.CheckConstraint("data_mode in ('poc','live')", name="ck_entities_data_mode"),
        schema="intel",
    )

    op.create_table(
        "syndicates",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agency_id", sa.Uuid()),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("linguistic_fingerprint", JSONB()),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("data_mode in ('poc','live')", name="ck_syndicates_data_mode"),
        schema="intel",
    )

    op.create_table(
        "syndicate_members",
        sa.Column("syndicate_id", sa.Uuid(), sa.ForeignKey("intel.syndicates.id"),
                  primary_key=True),
        sa.Column("entity_id", sa.Uuid(), sa.ForeignKey("intel.entities.id"),
                  primary_key=True),
        sa.Column("link_type", sa.Text()),
        sa.Column("confidence", sa.Numeric(4, 3)),
        schema="intel",
    )

    op.create_table(
        "crime_classifications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("session_id", sa.Uuid(), sa.ForeignKey("intel.scam_sessions.id"),
                  nullable=False, index=True),
        sa.Column("crime_type", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Numeric(4, 3)),
        sa.Column("model_version", sa.Text()),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("data_mode in ('poc','live')",
                           name="ck_crime_classifications_data_mode"),
        schema="intel",
    )


def downgrade() -> None:
    op.drop_table("crime_classifications", schema="intel")
    op.drop_table("syndicate_members", schema="intel")
    op.drop_table("syndicates", schema="intel")
    op.drop_table("entities", schema="intel")
    op.drop_table("messages", schema="intel")
    op.drop_table("scam_sessions", schema="intel")
    op.drop_table("personas", schema="intel")
    op.execute("DROP SCHEMA IF EXISTS intel")
