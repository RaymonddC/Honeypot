"""honeypot.dial_attempts — the call log (CDR): one row per dial ATTEMPT.

Phase 4 (migration 20260816_14 / commit fad427a) logged a call only when it
CONNECTED: an ``intel.scam_sessions`` row is created for an ``engaged`` outcome
and for nothing else. A no-answer or a carrier failure therefore left no
per-attempt trace at all — ``dial_targets.attempt_count`` is a bare counter, and
``status``/``last_error`` hold only the LATEST value. An investigator could not
ask "when did we call this number, and what happened each time?": the answer
"tried three times, no answer at 14:03 and 16:20, engaged at 09:12" was
unreconstructible.

That is the gap this table closes. It is the standard telephony split, and both
halves are kept:

* ``honeypot.dial_attempts`` (here)   — the CDR. Every attempt, every outcome.
* ``intel.scam_sessions``             — the conversation: transcript, extracted
                                        intel, custody chain. Connected calls only.

Sessions are deliberately NOT used as the attempt log. The triage queue (design
spec §5) reads sessions as an analyst work queue, and filling it with
transcript-less no-answers would make it a chore to work rather than a queue of
real conversations. Phase 4's reasoning on that point stands; what was missing
was somewhere else to put the attempt history.

``session_id`` lives here rather than on ``dial_targets`` — where migration
20260816_14 correctly removed it as ambiguous under Requeue ("first" or
"latest"?). On an attempt row it is unambiguous by construction: a row IS one
attempt, so it links to at most one conversation.

UNIQUE (target_id, attempt_no) makes the actor's logging idempotent under
Dramatiq's at-least-once redelivery — a replayed attempt collides instead of
silently doubling the call history.

RLS. ``dial_attempts`` has no ``agency_id``, one hop further out than
``dial_targets``. Its policy joins attempt → target → campaign:

    USING (target_id IN (
        SELECT t.id FROM honeypot.dial_targets t
        JOIN honeypot.dial_campaigns c ON c.id = t.campaign_id
        WHERE c.agency_id = core.current_agency()))

Same reasoning as migration 20260816_13 chose for ``dial_targets``: leaving the
table un-policied would expose every other agency's call history (who they
called and when — arguably more sensitive than the target list itself), and
denormalizing ``agency_id`` would duplicate ownership somewhere it can drift.
The join is written out explicitly rather than leaning on the inner tables' own
RLS: it is self-documenting, and it stays correct even if those policies change.
No SECURITY DEFINER helper is needed — the references run one way (attempts →
targets → campaigns), so nothing can re-trigger this policy.

The FK to ``intel.scam_sessions`` adds no creation cycle: this table is created
after both ``intel`` and ``honeypot`` exist, and nothing references it back, so
it needs none of the ``use_alter`` handling migration 20260816_13 required for
the (since-removed) mutual link.

Revision ID: 20260816_15
Revises: 20260816_14
Create Date: 2026-08-16
"""

import sqlalchemy as sa
from alembic import op

revision = "20260816_15"
down_revision = "20260816_14"
branch_labels = None
depends_on = None

SCHEMA = "honeypot"

_OUTCOME = "outcome in ('engaged','no_answer','failed')"
_DATA_MODE = "data_mode in ('poc','live')"


def upgrade() -> None:
    op.create_table(
        "dial_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "target_id", sa.Uuid(),
            sa.ForeignKey(f"{SCHEMA}.dial_targets.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("duration_seconds", sa.Integer()),
        # Only an `engaged` attempt has a conversation to point at.
        sa.Column(
            "session_id", sa.Uuid(), sa.ForeignKey("intel.scam_sessions.id"), index=True
        ),
        sa.Column("data_mode", sa.Text(), nullable=False, server_default="poc"),
        sa.Column(
            "started_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(_OUTCOME, name="ck_dial_attempts_outcome"),
        sa.CheckConstraint(_DATA_MODE, name="ck_dial_attempts_data_mode"),
        sa.CheckConstraint("attempt_no > 0", name="ck_dial_attempts_attempt_no"),
        sa.UniqueConstraint(
            "target_id", "attempt_no", name="uq_dial_attempts_target_attempt"
        ),
        schema=SCHEMA,
    )

    # Ownership is two hops away (attempt → target → campaign) — join to it
    # rather than denormalize. See the module docstring for why.
    op.execute(f'ALTER TABLE "{SCHEMA}".dial_attempts ENABLE ROW LEVEL SECURITY')
    op.execute(
        f"""
        CREATE POLICY dial_attempts_access ON "{SCHEMA}".dial_attempts
        USING (target_id IN (
            SELECT t.id FROM "{SCHEMA}".dial_targets t
            JOIN "{SCHEMA}".dial_campaigns c ON c.id = t.campaign_id
            WHERE c.agency_id = core.current_agency()
        ))
        WITH CHECK (target_id IN (
            SELECT t.id FROM "{SCHEMA}".dial_targets t
            JOIN "{SCHEMA}".dial_campaigns c ON c.id = t.campaign_id
            WHERE c.agency_id = core.current_agency()
        ))
        """
    )

    # The non-owning app role needs DML here like every other honeypot table.
    # scripts/create_app_role.sql's ALTER DEFAULT PRIVILEGES normally covers a
    # newly created table automatically; this is the belt-and-braces path for a
    # database whose role predates those defaults. Guarded on the role existing
    # because ephemeral test clusters (pgserver) and fresh dev databases run the
    # migration chain WITHOUT ever creating ittu_app — an unconditional GRANT
    # would abort the whole upgrade there.
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'ittu_app') THEN
                GRANT SELECT, INSERT, UPDATE, DELETE
                    ON "{SCHEMA}".dial_attempts TO ittu_app;
            END IF;
        END
        $$
        """
    )


def downgrade() -> None:
    op.execute(f'DROP POLICY IF EXISTS dial_attempts_access ON "{SCHEMA}".dial_attempts')
    op.execute(f'ALTER TABLE "{SCHEMA}".dial_attempts DISABLE ROW LEVEL SECURITY')
    op.drop_table("dial_attempts", schema=SCHEMA)
