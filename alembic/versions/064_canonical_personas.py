"""Give the live Workspace Persona a durable canonical owner (#12).

The Persona model was previously process-local, so a restart could leave a
Workspace with no readable live product context and allowed durable deployments
to diverge from the in-memory one-Persona invariant. The Workspace foreign key
also makes deletion clean up the dependent Persona without creating a second
ownership path.

Renumbered from 034 to 064 when develop's chain claimed the 034 slot first;
the renumber kept the single-head contract
(tests/migrations/test_single_migration_head.py).

Revision ID: 064
Revises: 063
"""

from __future__ import annotations

from alembic import op

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS, like 063: stamp-back and re-upgrade is a live repair
    # path, and the chain's contract is that re-applying a revision over the
    # schema it already built is adoption, not an error
    # (tests/migrations/test_migration_chain.py drives exactly that walk).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_personas (
            persona_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL,
            FOREIGN KEY (workspace_id)
                REFERENCES canonical_workspaces (workspace_id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_canonical_personas_workspace"
        " ON canonical_personas (workspace_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_canonical_personas_workspace")
    op.execute("DROP TABLE IF EXISTS canonical_personas")
