"""Durable per-Workspace working log over PostgreSQL (#301, M4-H / #105).

Revision ID: 072
Revises: 071 (develop's landed 071 = #69's Sentinel decision-integrity revision)

ADR-082226-5104's log-as-context is only real when the observation log
outlives the process, and until this revision a PostgreSQL deployment could
not honour that at all: the container's working-memory wiring read only the
SQLite pool, so a ``postgresql://`` database URL answered with the in-process
log and a warning. ``PgWorkspaceLogStore`` closes that gap behind the existing
``WorkspaceLogStore`` protocol seam; this revision owns ``CREATE TABLE`` for
real deployments, with DDL mirroring the store's
``ensure_working_log_schema`` runtime bootstrap (the same pairing the Goal
tables use for migration 063). The pg-pool test fixture truncates a
*migrated* database, so a table only runtime DDL would create breaks every
PostgreSQL-leg suite at setup.

Two tables, both append-only in practice, mirroring the SQLite twin:

* ``workspace_working_log`` — the lossless observation log (#301). Rows are
  never updated or deleted except by ``purge_workspace`` (retention, driven by
  Workspace deletion); resets and simplification are appended markers, so the
  log stays lossless. ``seq`` is an identity column the log assigns on
  append; a caller-chosen position is ignored, exactly like SQLite's
  AUTOINCREMENT.
* ``workspace_working_results`` — full results behind references,
  content-addressed per Workspace. Identical results inside one Workspace are
  one row; ``put_result`` is idempotent (``ON CONFLICT DO NOTHING``).

Retention is declared in ``quality/durable-table-retention.json`` with
``purge_workspace`` as the driven deletion path.

The DDL is guarded (``CREATE TABLE IF NOT EXISTS``) so a database that
already carries the runtime bootstrap is adopted untouched and a fresh one
is built to exactly the definition the store reads
(tests/migrations/test_migration_chain.py drives exactly that walk).
"""

from __future__ import annotations

from alembic import op

revision = "072"
down_revision = "071"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_working_log (
            seq BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            entry_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            cycle INTEGER NOT NULL,
            run_id TEXT NOT NULL DEFAULT '',
            result_ref TEXT,
            digest TEXT NOT NULL DEFAULT '',
            survive_reset BOOLEAN NOT NULL DEFAULT FALSE,
            created_at TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL,
            UNIQUE (workspace_id, entry_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_workspace_working_log_ws"
        " ON workspace_working_log (workspace_id, seq)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS workspace_working_results (
            workspace_id TEXT NOT NULL,
            result_id TEXT NOT NULL,
            source TEXT NOT NULL,
            digest TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            content TEXT NOT NULL,
            meta JSONB NOT NULL DEFAULT '{}',
            PRIMARY KEY (workspace_id, result_id)
        )
        """
    )


def downgrade() -> None:
    # Results first: they are the payload behind log references, so a log row
    # outliving its result would dangle in the half-downgraded schema.
    op.execute("DROP TABLE IF EXISTS workspace_working_results")
    op.execute("DROP TABLE IF EXISTS workspace_working_log")
