"""core.audit_log: UNIQUE (agency_id, seq) — stop the chain forking silently.

``app/core/audit.py`` allocates ``seq`` as ``max(seq) + 1`` read inside the
writing transaction. Two transactions committing concurrently for one agency
both read the same ``last`` row, so they claim the same ``seq`` **and inherit
the same ``prev_sha256``** — the chain does not merely renumber, it FORKS. The
damage is worse than it sounds: ``verify_chain`` then reports the log as broken,
and "broken" is read as *tampering*, which is the one conclusion the whole trail
exists to support. A routine concurrent write must never look like evidence of
someone editing the record.

This index is the correctness guarantee. It cannot prevent the race (nothing at
the schema level can), but it converts a **silent** fork into a loud, retryable
``UniqueViolation`` — and ``PostgresAuditRepository.record`` now retries on it,
re-reading the head so the second writer chains onto the first instead of beside
it.

``seq`` is NULLABLE, and this index deliberately leaves NULLs alone: Postgres
treats NULLs as distinct by default, so rows with no sequence number (nothing
writes them today, but the column permits them) are not blocked. Only actual
chain positions are made unique.

**Dirty data:** a duplicate ``(agency_id, seq)`` already in the table means that
agency's chain has ALREADY forked, and this migration refuses to run rather than
proceed. That is deliberate. The repair is to decide which entry is authentic —
an evidentiary judgement a human has to make and record — and a migration that
quietly picked a winner, or renumbered rows (which rewrites their hashes), would
be destroying exactly the evidence someone would later need. Fail loud, name the
rows, let a person adjudicate.

Revision ID: 20260822_17
Revises: 20260818_16
Create Date: 2026-08-22
"""

import sqlalchemy as sa
from alembic import op

revision = "20260822_17"
down_revision = "20260818_16"
branch_labels = None
depends_on = None

INDEX_NAME = "uq_audit_log_agency_seq"

_DUPLICATES = """
    SELECT agency_id, seq, count(*) AS n
    FROM core.audit_log
    WHERE seq IS NOT NULL
    GROUP BY agency_id, seq
    HAVING count(*) > 1
    ORDER BY n DESC, agency_id, seq
    LIMIT 20
"""


def upgrade() -> None:
    # Skipped when rendering offline (`alembic upgrade head --sql`), which has no
    # connection to ask. The CREATE UNIQUE INDEX below still fails on dirty data
    # in that path — just with Postgres's terser message instead of ours.
    if not op.get_context().as_sql:
        rows = op.get_bind().execute(sa.text(_DUPLICATES)).fetchall()
        if rows:
            listed = ", ".join(f"agency {r[0]} seq {r[1]} ×{r[2]}" for r in rows)
            raise RuntimeError(
                "core.audit_log already contains duplicate (agency_id, seq) rows, "
                "which means that agency's hash chain has already FORKED: "
                f"{listed}. This migration will not install the guard on top of "
                "data it cannot vouch for, and it will not pick a winner or "
                "renumber rows — renumbering rewrites their hashes and destroys "
                "the evidence needed to work out what happened. Adjudicate the "
                "duplicates first (which entry is authentic, and why), record "
                "that decision, then re-run."
            )

    op.create_index(
        INDEX_NAME, "audit_log", ["agency_id", "seq"], unique=True, schema="core"
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name="audit_log", schema="core")
