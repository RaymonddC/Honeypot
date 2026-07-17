"""RLS on the agency-scoped intel/action tables + the two doc-specified missing
tables: core.evidence_manifest, chain.graph_snapshots (docs/Data-Model.md,
docs/Persistence-Plan.md P-1).

Extends the RLS pattern from migration ``20260708_05`` (``core.current_agency()``,
fail-closed on NULL) to:

    intel.scam_sessions, intel.messages, intel.entities, intel.syndicates,
    intel.crime_classifications, action.action_documents, action.notifications

``scam_sessions``, ``entities``, ``syndicates``, ``action_documents`` already had a
plain ``agency_id uuid`` column (added in migrations 03/04, no FK/index yet) — this
migration adds the FK + a missing index. ``messages`` and ``crime_classifications``
had no ``agency_id`` at all — added here. ``notifications`` already had
``target_agency_id`` (the *recipient*) — this adds a separate ``agency_id`` (the
*owning/dispatching* agency) for RLS, distinct from the recipient.

All 7 tables are currently empty (no route persists to Postgres yet — see
docs/Persistence-Plan.md), so every new column is added nullable with no backfill.
RLS fails closed on a NULL ``app.current_agency`` (see migration 05), and the
``WITH CHECK`` also fails closed on a NULL row ``agency_id`` (NULL = NULL is never
true in SQL), so nothing is silently exposed either way.

**Scope note (P-1 lead's call, revised):** ``chain.*`` and ``fiat.*`` raw-ledger /
reference tables (wallets, transactions, wallet_features, wallet_risk_scores,
address_tags, fiat rails) are deliberately NOT agency-scoped — they hold
public-ledger / reference facts shared across agencies, not agency-owned records.
``chain.graph_snapshots`` is the one exception: it's a per-*case* cached graph
export (which entities/wallets an agency is investigating), so it IS agency-owned
and gets ``agency_id`` + RLS below, same shape as the 7 tables above.

core.evidence_manifest gets its own ``agency_id`` + RLS (not in the lead's list of
7, added here) because it is unambiguously agency-scoped court evidence — the same
category as ``core.audit_log``, which already carries RLS. Flagged in the P-1
report.

Revision ID: 20260715_06
Revises: 20260708_05
Create Date: 2026-07-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260715_06"
down_revision = "20260708_05"
branch_labels = None
depends_on = None

# (schema, table) -> RLS policy name, for the 7 lead-specified agency-scoped tables.
AGENCY_SCOPED_TABLES = [
    ("intel", "scam_sessions"),
    ("intel", "messages"),
    ("intel", "entities"),
    ("intel", "syndicates"),
    ("intel", "crime_classifications"),
    ("action", "action_documents"),
    ("action", "notifications"),
]


def _enable_rls(schema: str, table: str) -> None:
    """ENABLE RLS + USING/WITH CHECK policy, matching migration 05's core.* shape."""
    op.execute(f'ALTER TABLE "{schema}".{table} ENABLE ROW LEVEL SECURITY')
    op.execute(
        f"""
        CREATE POLICY {table}_access ON "{schema}".{table}
        USING (agency_id = core.current_agency())
        WITH CHECK (agency_id = core.current_agency())
        """
    )


def _disable_rls(schema: str, table: str) -> None:
    op.execute(f'DROP POLICY IF EXISTS {table}_access ON "{schema}".{table}')
    op.execute(f'ALTER TABLE "{schema}".{table} DISABLE ROW LEVEL SECURITY')


def upgrade() -> None:
    # ---------------------------------------------------------- new columns --
    # messages / crime_classifications had no agency_id at all.
    op.add_column("messages", sa.Column("agency_id", sa.Uuid(), nullable=True), schema="intel")
    op.add_column(
        "crime_classifications", sa.Column("agency_id", sa.Uuid(), nullable=True), schema="intel"
    )
    # notifications: add the OWNING agency, distinct from the existing recipient
    # column target_agency_id.
    op.add_column(
        "notifications", sa.Column("agency_id", sa.Uuid(), nullable=True), schema="action"
    )

    # --------------------------------------------------- indexes (new cols) --
    op.create_index("ix_intel_messages_agency_id", "messages", ["agency_id"], schema="intel")
    op.create_index(
        "ix_intel_crime_classifications_agency_id",
        "crime_classifications",
        ["agency_id"],
        schema="intel",
    )
    op.create_index(
        "ix_action_notifications_agency_id", "notifications", ["agency_id"], schema="action"
    )
    # entities / syndicates already had agency_id (migration 04) but no index.
    op.create_index("ix_intel_entities_agency_id", "entities", ["agency_id"], schema="intel")
    op.create_index("ix_intel_syndicates_agency_id", "syndicates", ["agency_id"], schema="intel")
    # scam_sessions.agency_id and action_documents.agency_id were already indexed.

    # ------------------------------------------------- FKs -> core.agencies --
    for schema, table in AGENCY_SCOPED_TABLES:
        op.create_foreign_key(
            f"fk_{table}_agency_id_agencies",
            table,
            "agencies",
            ["agency_id"],
            ["id"],
            source_schema=schema,
            referent_schema="core",
        )

    # -------------------------------------------------------------- RLS --
    for schema, table in AGENCY_SCOPED_TABLES:
        _enable_rls(schema, table)

    # --------------------------------------------- core.evidence_manifest --
    # Per-session/case reproducibility manifest for court explainability
    # (docs/Data-Model.md §core, docs/Persistence-Plan.md P-1). Session/case FKs
    # are nullable — a manifest may be written before a case exists yet, matching
    # intel.scam_sessions.case_id's own nullable FK-less convention.
    op.create_table(
        "evidence_manifest",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "session_id", sa.Uuid(), sa.ForeignKey("intel.scam_sessions.id"), index=True
        ),
        sa.Column("case_id", sa.Uuid(), sa.ForeignKey("core.cases.id"), index=True),
        sa.Column(
            "agency_id", sa.Uuid(), sa.ForeignKey("core.agencies.id"), index=True
        ),
        # {orchestrator, extractor, classifier, stt, tts}
        sa.Column("model_versions", JSONB()),
        sa.Column("prompt_versions", JSONB()),
        sa.Column("pipeline_config", JSONB()),
        # Reproducibility digests, e.g. {"transcript_sha256": "...", "input_sha256": "..."}
        sa.Column("hashes", JSONB()),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "data_mode in ('poc','live')", name="ck_evidence_manifest_data_mode"
        ),
        schema="core",
    )
    _enable_rls("core", "evidence_manifest")

    # ----------------------------------------------------- chain.graph_snapshots --
    # Cached per-case subgraph export (docs/Data-Model.md §chain) — agency-scoped
    # (lead's call, see module docstring): reveals what an agency is investigating.
    # case_id stays a plain indexed uuid, consistent with the case_id convention on
    # scam_sessions/action_documents/notifications/fiat.correlations (no cross-
    # schema FK).
    op.create_table(
        "graph_snapshots",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("case_id", sa.Uuid(), index=True),
        sa.Column(
            "agency_id", sa.Uuid(), sa.ForeignKey("core.agencies.id"), index=True
        ),
        sa.Column("spec", JSONB()),  # projection parameters (depth, node types, filters…)
        sa.Column("content_ref", sa.Text()),  # object-store key for the serialized blob
        sa.Column("node_count", sa.Integer()),
        sa.Column("edge_count", sa.Integer()),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column(
            "built_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("data_mode in ('poc','live')", name="ck_graph_snapshots_data_mode"),
        schema="chain",
    )
    _enable_rls("chain", "graph_snapshots")


def downgrade() -> None:
    _disable_rls("chain", "graph_snapshots")
    op.drop_table("graph_snapshots", schema="chain")

    _disable_rls("core", "evidence_manifest")
    op.drop_table("evidence_manifest", schema="core")

    for schema, table in AGENCY_SCOPED_TABLES:
        _disable_rls(schema, table)

    for schema, table in AGENCY_SCOPED_TABLES:
        op.drop_constraint(f"fk_{table}_agency_id_agencies", table, schema=schema, type_="foreignkey")

    op.drop_index("ix_intel_syndicates_agency_id", table_name="syndicates", schema="intel")
    op.drop_index("ix_intel_entities_agency_id", table_name="entities", schema="intel")
    op.drop_index(
        "ix_action_notifications_agency_id", table_name="notifications", schema="action"
    )
    op.drop_index(
        "ix_intel_crime_classifications_agency_id",
        table_name="crime_classifications",
        schema="intel",
    )
    op.drop_index("ix_intel_messages_agency_id", table_name="messages", schema="intel")

    op.drop_column("notifications", "agency_id", schema="action")
    op.drop_column("crime_classifications", "agency_id", schema="intel")
    op.drop_column("messages", "agency_id", schema="intel")
