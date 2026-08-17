"""honeypot schema (numbers, dial_campaigns, dial_targets) + scam_sessions call columns.

Phase 1 of docs/Voice-Honeypot-Outbound.md — the data model behind outbound
honeypot calling. Schema only: no router, service, or worker yet (phases 3–4),
so this migration adds tables nothing writes to *yet* and changes no behavior.

Three new tables in a new ``honeypot`` schema:

- ``honeypot.numbers`` — the pool of Twilio numbers we dial FROM, rotated so a
  burned caller-ID doesn't end the operation. Registered by an operator (bought
  and webhook-configured in the Twilio console), never provisioned via API —
  design spec §9. ``phone_number`` is globally UNIQUE: a physical number can
  only be owned once, which is a real-world constraint rather than a tenant one.
- ``honeypot.dial_campaigns`` — one uploaded batch, with a self-imposed
  ``pacing_per_minute`` cap (Twilio's per-account concurrency is the hard
  ceiling). ``case_id`` carries NO foreign key, matching
  ``intel.scam_sessions.case_id``: the link is advisory and may pre-date the
  case row.
- ``honeypot.dial_targets`` — one row per number, carrying the durable dial
  lifecycle. Deliberately the same shape as ``action.notifications``'s delivery
  columns (``status``/``attempt_count``/``last_error``/``updated_at``, migration
  20260724_12): both are "a queued unit of outbound work a Dramatiq actor
  retries", so the C1 retry/settle patterns carry over unchanged.
  ``(campaign_id, phone_number)`` is UNIQUE — a campaign never dials the same
  number twice.

Plus four additive, nullable columns on ``intel.scam_sessions`` (design spec
§3.4) for the voice specifics a text chat has no use for: ``duration_seconds``,
``recording_url`` (the Twilio recording — evidence, same custody principle as
``core.evidence_manifest``), ``disposition``, and ``dial_target_id``.

⚠️ MUTUAL LINK. ``dial_targets.session_id`` → ``intel.scam_sessions.id`` and
``scam_sessions.dial_target_id`` → ``honeypot.dial_targets.id`` reference each
other. Both sides are NULLABLE precisely so this is writable: whichever row is
created first leaves the other side NULL and is linked afterwards. The
``scam_sessions`` FK is therefore added by ALTER *after* both tables exist (and
dropped first on downgrade); the ORM marks it ``use_alter=True`` for the same
reason.

RLS. ``numbers`` and ``dial_campaigns`` are agency-owned and get the standard
``agency_id = core.current_agency()`` policy (migrations 05/06/10), fail-closed
on a NULL agency.

``dial_targets`` has no ``agency_id`` of its own, so it gets a policy that
**joins through its campaign** rather than denormalizing the owner:

    USING (campaign_id IN (SELECT id FROM honeypot.dial_campaigns
                           WHERE agency_id = core.current_agency()))

Rationale for that choice over the two alternatives:

1. *No policy at all* (relying on the campaign's) was rejected outright — RLS is
   per-table, so an un-policied ``dial_targets`` would let any authenticated
   agency read every other agency's investigation targets. Those rows are a list
   of numbers under investigation; that is exactly the cross-tenant leak RLS
   exists to prevent.
2. *Denormalizing ``agency_id`` onto the target* would give a simpler policy but
   duplicates ownership in two places, where it can silently drift if a campaign
   is ever reassigned.

Unlike the ``cases ⇄ case_shares`` policies (migration 05), this needs no
SECURITY DEFINER helper: the reference is one-directional (targets → campaigns,
never back), so consulting ``dial_campaigns`` cannot re-trigger this policy.
The inner ``dial_campaigns`` RLS still applies to the subquery and filters to the
same agency, which is the intended answer either way.

NB: ``honeypot`` is a NEW schema, so ``backend/scripts/create_app_role.sql`` is
updated in the same commit to grant ``ittu_app`` USAGE + DML + default
privileges on it. Without that the non-owning app role cannot see these tables
at all.

Revision ID: 20260816_13
Revises: 20260724_12
Create Date: 2026-08-16
"""

import sqlalchemy as sa
from alembic import op

revision = "20260816_13"
down_revision = "20260724_12"
branch_labels = None
depends_on = None

SCHEMA = "honeypot"

_STATUS_NUMBER = "status in ('active','retired','rate_limited')"
_STATUS_CAMPAIGN = "status in ('draft','running','paused','completed')"
_STATUS_TARGET = "status in ('queued','dialing','no_answer','engaged','failed')"
_DATA_MODE = "data_mode in ('poc','live')"

# Added by ALTER after both sides exist — see the mutual-link note above.
_FK_SESSION_TARGET = "fk_scam_sessions_dial_target_id"


def _enable_agency_rls(table: str) -> None:
    """Standard agency-owned policy (migrations 05/06/10), fail-closed on NULL."""
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

    # ------------------------------------------------------------- numbers --
    op.create_table(
        "numbers",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "agency_id", sa.Uuid(), sa.ForeignKey("core.agencies.id"), nullable=False, index=True
        ),
        sa.Column("phone_number", sa.Text(), nullable=False, unique=True),
        sa.Column("twilio_sid", sa.Text()),
        sa.Column("label", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Text(), nullable=False, server_default="active"),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(_STATUS_NUMBER, name="ck_numbers_status"),
        sa.CheckConstraint(_DATA_MODE, name="ck_numbers_data_mode"),
        schema=SCHEMA,
    )
    _enable_agency_rls("numbers")

    # ----------------------------------------------------- dial_campaigns --
    op.create_table(
        "dial_campaigns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("public_id", sa.Text(), nullable=False, unique=True),  # "camp_..."
        sa.Column(
            "agency_id", sa.Uuid(), sa.ForeignKey("core.agencies.id"), nullable=False, index=True
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Uuid(), index=True),  # advisory link, no FK (see docstring)
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("pacing_per_minute", sa.Integer(), nullable=False, server_default="6"),
        sa.Column("created_by", sa.Uuid(), sa.ForeignKey("core.users.id")),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(_STATUS_CAMPAIGN, name="ck_dial_campaigns_status"),
        sa.CheckConstraint(_DATA_MODE, name="ck_dial_campaigns_data_mode"),
        sa.CheckConstraint("pacing_per_minute > 0", name="ck_dial_campaigns_pacing"),
        schema=SCHEMA,
    )
    _enable_agency_rls("dial_campaigns")

    # ------------------------------------------------------- dial_targets --
    op.create_table(
        "dial_targets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "campaign_id", sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.dial_campaigns.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("phone_number", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text()),
        sa.Column(
            "session_id", sa.Uuid(), sa.ForeignKey("intel.scam_sessions.id"), index=True
        ),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.CheckConstraint(_STATUS_TARGET, name="ck_dial_targets_status"),
        sa.CheckConstraint(_DATA_MODE, name="ck_dial_targets_data_mode"),
        # A campaign never dials the same number twice.
        sa.UniqueConstraint("campaign_id", "phone_number", name="uq_dial_targets_campaign_number"),
        schema=SCHEMA,
    )
    # Ownership lives on the campaign — join through it rather than denormalize.
    op.execute(f'ALTER TABLE "{SCHEMA}".dial_targets ENABLE ROW LEVEL SECURITY')
    op.execute(
        f"""
        CREATE POLICY dial_targets_access ON "{SCHEMA}".dial_targets
        USING (campaign_id IN (
            SELECT id FROM "{SCHEMA}".dial_campaigns
            WHERE agency_id = core.current_agency()
        ))
        WITH CHECK (campaign_id IN (
            SELECT id FROM "{SCHEMA}".dial_campaigns
            WHERE agency_id = core.current_agency()
        ))
        """
    )

    # ------------------------------- intel.scam_sessions call columns (§3.4) --
    op.add_column("scam_sessions", sa.Column("duration_seconds", sa.Integer()), schema="intel")
    op.add_column("scam_sessions", sa.Column("recording_url", sa.Text()), schema="intel")
    op.add_column("scam_sessions", sa.Column("disposition", sa.Text()), schema="intel")
    op.add_column("scam_sessions", sa.Column("dial_target_id", sa.Uuid()), schema="intel")
    op.create_index(
        "ix_intel_scam_sessions_dial_target_id", "scam_sessions", ["dial_target_id"], schema="intel"
    )
    # Added last: closes the intel ⇄ honeypot mutual link once both sides exist.
    op.create_foreign_key(
        _FK_SESSION_TARGET,
        "scam_sessions", "dial_targets",
        ["dial_target_id"], ["id"],
        source_schema="intel", referent_schema=SCHEMA,
    )


def downgrade() -> None:
    # Break the mutual link first, or dropping dial_targets would fail.
    op.drop_constraint(_FK_SESSION_TARGET, "scam_sessions", schema="intel", type_="foreignkey")
    op.drop_index("ix_intel_scam_sessions_dial_target_id", "scam_sessions", schema="intel")
    op.drop_column("scam_sessions", "dial_target_id", schema="intel")
    op.drop_column("scam_sessions", "disposition", schema="intel")
    op.drop_column("scam_sessions", "recording_url", schema="intel")
    op.drop_column("scam_sessions", "duration_seconds", schema="intel")

    _disable_rls("dial_targets")
    op.drop_table("dial_targets", schema=SCHEMA)
    _disable_rls("dial_campaigns")
    op.drop_table("dial_campaigns", schema=SCHEMA)
    _disable_rls("numbers")
    op.drop_table("numbers", schema=SCHEMA)
    op.execute(f'DROP SCHEMA IF EXISTS "{SCHEMA}"')
