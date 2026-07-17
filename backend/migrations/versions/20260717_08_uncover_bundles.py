"""UNCOVER persistence: action.action_bundles + public_id/bundle_id bridges
(P-3, docs/Persistence-Plan.md), additive only.

**The gap this closes (deeper than migration 07's):** ``app/uncover/service.py``
holds an in-memory ``_ACTIONS: dict[str, ActionBundle]`` — but unlike
INFILTRATE's ``ScamSession``, **no table exists for the ``ActionBundle``
aggregate itself.** ``action.action_documents``/``action.notifications``
(migration 03) hold per-document/per-dispatch rows only; neither carries the
bundle's own fields (``status`` draft→dispatched, ``outputs``, the selected
entities, ``goaml_draft``, ``routing_plan``, ``totals``, ``created_at``/
``dispatched_at``) — nor any column that groups a set of documents/
notifications back into the ONE bundle that produced them (``case_id`` isn't
it: it's not unique — two ``generate`` calls for the same case yield
indistinguishable document rows without a real grouping key). Confirmed with
the P-3 lead before writing this: reject stashing the envelope as JSONB on a
sibling row (breaks on a zero-document bundle, an emergent identity, a race);
give the aggregate a real table instead.

**Three additive pieces:**

1. **New ``action.action_bundles``** — the aggregate root. Surrogate ``uuid``
   PK (internal) + ``public_id`` (the ``act_…`` id, the natural/business key —
   same pattern as migration 07). ``case_id`` is stored as **``text``**, not
   ``uuid`` (unlike the existing ``case_id uuid`` column on
   ``action_documents``/``notifications``): ``ActionBundle.case_id`` is a
   *required* field and always a business string like ``"CASE-2026-0142"``,
   never a UUID — the ``_safe_uuid``-drop-if-invalid trick migration 07 used
   for INFILTRATE's *optional* ``session.case_id`` would silently NULL out
   this required field on nearly every real bundle. ``goaml_draft`` /
   ``routing_plan`` / ``totals`` / ``selected_entities`` are stored as JSONB
   **snapshots** — the same evidential reasoning as ``persona_snapshot``
   (migration 07): they record what was actually assembled/routed at
   generate-time, not a live re-derivation that could drift from what a court
   exhibit actually said. RLS enabled with the same
   ``USING/WITH CHECK (agency_id = core.current_agency())`` policy as
   migrations 06/07.

2. **``action_documents`` / ``notifications``** get the same ``public_id
   text UNIQUE NOT NULL`` bridge as migration 07's five tables, **plus
   ``bundle_id uuid NOT NULL`` FK → ``action_bundles.id``** — the real
   grouping key the aggregate needed. All three tables are still empty (no
   route has ever persisted to Postgres — same premise as migration 07), so
   every new NOT NULL column needs no backfill.

3. **``action_documents.pdf bytea`` (nullable) + three more scalar columns.**
   ``GeneratedDocument.pdf`` (the actual rendered bytes) has no home:
   ``content_ref`` is documented as an *object-store key*, and no object
   store exists anywhere in this codebase yet. Confirmed with the lead: do
   **not** re-derive the PDF from its stored context on read, even though
   generation is deterministic today (``invariant=1``, ``pageCompression=0``)
   — that determinism only holds for a fixed template + code path; a future
   ReportLab layout tweak would regenerate different bytes that no longer
   match the persisted ``sha256``, silently breaking the custody chain on a
   court exhibit. The document that was issued IS the evidence; store it,
   never re-derive it. ``bytea`` is fine at freeze-order/STR sizes; migrate
   to real object storage (via the untouched ``content_ref`` column) when
   documents grow or multiply.

   While mapping ``DocumentOut``/``GeneratedDocument`` onto the table (same
   exercise that found the ``action_bundles`` gap), three more *required*
   scalar fields turned out to have no column either: ``title``, ``filename``,
   ``template_version`` — all round-tripped in the API response and
   (``filename``) in the download's ``Content-Disposition`` header. Added
   as plain ``text NOT NULL`` columns, same footing as the pre-existing
   ``type``/``format``. (``GeneratedDocument.meta`` is NOT added — it's
   write-time-only scratch data: ``goaml_draft`` is read out of it once,
   immediately, at generate time, and never read again on any later fetch.)

   Same exercise on ``NotificationOut`` found two more: ``target_agency``
   (display name, e.g. "Bank BCA" — distinct from the existing
   ``target_agency_id uuid``, which stays unpopulated: a freeze target like
   a specific bank branch mostly isn't in the seeded agency directory at all,
   so there's nothing real to resolve it to yet) and ``agency_type`` (no
   column existed for it at all). Added as ``text NOT NULL`` on
   ``notifications`` — a notification row is only ever created at dispatch
   time with the full record already in hand, so no backfill concern.

Revision ID: 20260717_08
Revises: 20260716_07
Create Date: 2026-07-17
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260717_08"
down_revision = "20260716_07"
branch_labels = None
depends_on = None

# (schema, table) -> the app-issued opaque id this table needs to round-trip,
# same bridge pattern as migration 07.
PUBLIC_ID_TABLES = [
    ("action", "action_documents"),
    ("action", "notifications"),
]


def _enable_rls(schema: str, table: str) -> None:
    """ENABLE RLS + USING/WITH CHECK policy — matches migrations 05/06."""
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
    # ------------------------------------------------------- action_bundles --
    op.create_table(
        "action_bundles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("public_id", sa.Text(), nullable=False),
        sa.Column("case_id", sa.Text(), nullable=False),  # business key, NOT a uuid — see docstring
        sa.Column(
            "agency_id", sa.Uuid(), sa.ForeignKey("core.agencies.id"), index=True
        ),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("crime_type", sa.Text(), nullable=False),
        sa.Column("outputs", JSONB(), nullable=False, server_default="[]"),
        sa.Column("selected_entities", JSONB(), nullable=False, server_default="[]"),
        sa.Column("goaml_draft", JSONB()),  # nullable — bundle may skip the ltkm output
        sa.Column("routing_plan", JSONB(), nullable=False, server_default="[]"),
        sa.Column("totals", JSONB(), nullable=False, server_default="{}"),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("dispatched_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("status in ('draft','dispatched')", name="ck_action_bundles_status"),
        sa.CheckConstraint("data_mode in ('poc','live')", name="ck_action_bundles_data_mode"),
        schema="action",
    )
    op.create_unique_constraint(
        "uq_action_action_bundles_public_id", "action_bundles", ["public_id"], schema="action"
    )
    _enable_rls("action", "action_bundles")

    # ------------------------------------------------ public_id + bundle_id --
    for schema, table in PUBLIC_ID_TABLES:
        op.add_column(
            table, sa.Column("public_id", sa.Text(), nullable=False), schema=schema
        )
        op.create_unique_constraint(
            f"uq_{schema}_{table}_public_id", table, ["public_id"], schema=schema
        )
        op.add_column(
            table, sa.Column("bundle_id", sa.Uuid(), nullable=False), schema=schema
        )
        op.create_foreign_key(
            f"fk_{table}_bundle_id_action_bundles",
            table,
            "action_bundles",
            ["bundle_id"],
            ["id"],
            source_schema=schema,
            referent_schema="action",
        )
        op.create_index(f"ix_{schema}_{table}_bundle_id", table, ["bundle_id"], schema=schema)

    # ---------------------------------------------- pdf bytes + doc scalars --
    op.add_column("action_documents", sa.Column("pdf", sa.LargeBinary()), schema="action")
    op.add_column(
        "action_documents", sa.Column("title", sa.Text(), nullable=False), schema="action"
    )
    op.add_column(
        "action_documents", sa.Column("filename", sa.Text(), nullable=False), schema="action"
    )
    op.add_column(
        "action_documents", sa.Column("template_version", sa.Text(), nullable=False),
        schema="action",
    )

    # ------------------------------------------------- notification scalars --
    op.add_column(
        "notifications", sa.Column("target_agency", sa.Text(), nullable=False), schema="action"
    )
    op.add_column(
        "notifications", sa.Column("agency_type", sa.Text(), nullable=False), schema="action"
    )


def downgrade() -> None:
    op.drop_column("notifications", "agency_type", schema="action")
    op.drop_column("notifications", "target_agency", schema="action")

    op.drop_column("action_documents", "template_version", schema="action")
    op.drop_column("action_documents", "filename", schema="action")
    op.drop_column("action_documents", "title", schema="action")
    op.drop_column("action_documents", "pdf", schema="action")

    for schema, table in PUBLIC_ID_TABLES:
        op.drop_index(f"ix_{schema}_{table}_bundle_id", table_name=table, schema=schema)
        op.drop_constraint(
            f"fk_{table}_bundle_id_action_bundles", table, schema=schema, type_="foreignkey"
        )
        op.drop_column(table, "bundle_id", schema=schema)
        op.drop_constraint(
            f"uq_{schema}_{table}_public_id", table, schema=schema, type_="unique"
        )
        op.drop_column(table, "public_id", schema=schema)

    _disable_rls("action", "action_bundles")
    op.drop_table("action_bundles", schema="action")
