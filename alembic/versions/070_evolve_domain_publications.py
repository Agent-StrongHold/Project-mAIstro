"""Durable Evolve domain snapshots and effect publications (#1064).

Revision ID: 070
Revises: 069

The Evolve product's recovery contract requires that a genuinely new process
can reconstruct the exact population/tournament a stranded canonical Run was
admitted against, and that one logical NodeRun can never publish the same
domain effect twice across processes or replicas. ``services/
evolve_domain_store.py`` is the runtime store: versioned domain snapshots at
admission/finalize boundaries plus an ordered publication journal whose
primary key is the exactly-once fence. This revision owns ``CREATE TABLE``
for real deployments, with DDL byte-identical to the store's
``POSTGRES_EVOLVE_DOMAIN_SCHEMA`` runtime bootstrap (the same pairing the
delegation/event tables use): the pg-pool test fixture truncates a *migrated*
database, so a table only runtime DDL would create breaks every
PostgreSQL-leg suite at setup.

The DDL is guarded (``CREATE TABLE IF NOT EXISTS``) so a database that
already carries the runtime bootstrap is adopted untouched and a fresh one
is built to exactly the definition the store reads.
"""

from __future__ import annotations

from alembic import op

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS evolve_domain_snapshots (
            workspace_id TEXT NOT NULL,
            run_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            version INT NOT NULL DEFAULT 1,
            payload JSONB NOT NULL,
            seq BIGSERIAL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, run_id, kind)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS evolve_domain_publications (
            workspace_id TEXT NOT NULL,
            effect_kind TEXT NOT NULL,
            node_run_id TEXT NOT NULL,
            benchmark TEXT NOT NULL DEFAULT '',
            attempt_id TEXT NOT NULL DEFAULT '',
            run_id TEXT NOT NULL,
            payload JSONB NOT NULL,
            seq BIGSERIAL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, effect_kind, node_run_id, benchmark)
        )
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_evolve_domain_snapshots_ws_seq
            ON evolve_domain_snapshots (workspace_id, seq)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_evolve_domain_publications_ws_kind_seq
            ON evolve_domain_publications (workspace_id, effect_kind, seq)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_evolve_domain_publications_ws_kind_seq")
    op.execute("DROP INDEX IF EXISTS ix_evolve_domain_snapshots_ws_seq")
    op.execute("DROP TABLE IF EXISTS evolve_domain_publications")
    op.execute("DROP TABLE IF EXISTS evolve_domain_snapshots")
