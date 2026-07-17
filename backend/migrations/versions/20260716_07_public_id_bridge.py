"""Public-id bridge + persona snapshot for the INFILTRATE repository (P-2b,
docs/Persistence-Plan.md P-2), additive only — no FK/PK type changes.

**The gap this closes:** ``app/infiltrate/service.py`` mints opaque, prefixed
string ids for every domain object it hands back over the API — sessions
(``f"sess_{uuid.uuid4().hex[:12]}"``), messages (``msg_``), entities (``ent_``),
syndicates (``syn_``), and the persona pool (``app/infiltrate/personas.py``,
e.g. ``"per_busari"``). None of those are valid UUID literals, but every PK in
migrations 01-06 is a native Postgres ``uuid`` column — inserting a
``"sess_..."`` string into one fails outright.

Three ways to close that gap were considered:
1. Retype the PKs/FKs to ``text``. Rejected: docs/Data-Model.md commits to
   UUIDv7 PKs as a design principle; retyping degrades index/storage
   characteristics and ripples through every FK in a system built for
   long-lived court evidence.
2. Change the app's id format to mint real UUIDs. Rejected: those ids are in
   API responses, the frontend's TS types, and URLs — an API break with a far
   bigger blast radius than one additive migration. The prefixed-id style is
   good API design and stays as-is.
3. **Surrogate ``uuid`` PK (internal, FK plumbing only) + the app id as the
   natural/business key** — the approach taken here. Standard, well
   understood, and it honors both the UUIDv7-PK principle and the existing API
   contract. Adds ``public_id text UNIQUE NOT NULL`` — "the id the API
   exposes" — to the five tables the repository writes to; the ``uuid`` PK
   never leaves the DB. All five tables are empty (nothing has persisted to
   Postgres yet — see migration 06), so a NOT NULL column needs no backfill.

**``persona_snapshot`` on ``scam_sessions``:** the in-memory ``SessionOut``
embeds a full ``PersonaOut`` (name/age/occupation/region) rather than a live
FK join, and this column preserves that at the DB layer too. That's not just
convenient — it's evidentially correct: if a persona definition changes later,
a past session's record must still reflect what actually ran, exactly the
reasoning behind ``core.evidence_manifest`` pinning model/prompt versions per
session for court reproducibility. A live join to ``intel.personas`` would let
history silently drift; a snapshot can't. (``escalations``/``scam_signals``
need no such column — they're message-scoped and ride in each message's
existing ``meta`` JSONB. ``custody.chain_intact`` is deliberately never
stored — it's re-verified from the stored hash chain on every read, so a
persisted boolean can never silently diverge from the data it asserts.)

Revision ID: 20260716_07
Revises: 20260715_06
Create Date: 2026-07-16
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20260716_07"
down_revision = "20260715_06"
branch_labels = None
depends_on = None

# (schema, table) -> the app-issued opaque id this table needs to round-trip.
PUBLIC_ID_TABLES = [
    ("intel", "scam_sessions"),
    ("intel", "messages"),
    ("intel", "entities"),
    ("intel", "syndicates"),
    ("intel", "personas"),
]


def upgrade() -> None:
    for schema, table in PUBLIC_ID_TABLES:
        op.add_column(
            table, sa.Column("public_id", sa.Text(), nullable=False), schema=schema
        )
        op.create_unique_constraint(
            f"uq_{schema}_{table}_public_id", table, ["public_id"], schema=schema
        )

    op.add_column(
        "scam_sessions", sa.Column("persona_snapshot", JSONB(), nullable=True), schema="intel"
    )


def downgrade() -> None:
    op.drop_column("scam_sessions", "persona_snapshot", schema="intel")

    for schema, table in PUBLIC_ID_TABLES:
        op.drop_constraint(
            f"uq_{schema}_{table}_public_id", table, schema=schema, type_="unique"
        )
        op.drop_column(table, "public_id", schema=schema)
