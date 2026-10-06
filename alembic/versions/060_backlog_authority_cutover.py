"""Backlog authority cutover control state (#102).

Follows `059_backlog_work_source` (its pre-renumber ids were `049`, then
`053`, then `055`, then `057`, then `059`; develop's landed
`049_design_artifact_versions`, `053_learning_lifecycle_columns`,
`054_learning_applicability_epistemics` and `055_task_admission_generations`
own those slots now, develop's `056_user_model_facts` plus #863's
`057_run_store_planner_stability` claim `056` and `057`, and develop's
Gauntlet provenance ledger `058_learning_validation_provenance` (#118,
M4-B2) claims `058`), attaching after the work-source tables so the chain
stays linear with exactly one head.
The explicit authority cutover is a recorded, reversible decision, and the
generated Markdown must be reproducible from the database alone — so the
control state is durable, with the same schema discipline as the work-source
tables: the DDL here is guarded (`CREATE TABLE IF NOT EXISTS`), matching the
SQLite twin's `ensure_schema` (`maistro.backlog.cutover`), and a database
that already carries these tables is adopted untouched.

`backlog_authority` is the append-only ledger of authority revisions: one row
per flip between Markdown and database authority, with its revision number,
actor, instant and note. The current authority is the highest revision;
reverting appends, it never deletes, so the cutover's history survives even a
revert made during migration validation.

`backlog_documents` holds each imported document's parsed token stream
(furniture verbatim plus item positions). It is what makes the generated
`BACKLOG.md` byte-deterministic after a restart: the export replays this
stream and renders each item from `backlog_items`, with no dependency on the
original file.
"""

from __future__ import annotations

from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backlog_authority (
            revision BIGSERIAL PRIMARY KEY,
            authority TEXT NOT NULL,
            actor TEXT NOT NULL,
            at TIMESTAMPTZ NOT NULL,
            note TEXT NOT NULL
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS backlog_documents (
            document_id TEXT PRIMARY KEY,
            tokens JSONB NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS backlog_documents")
    op.execute("DROP TABLE IF EXISTS backlog_authority")
