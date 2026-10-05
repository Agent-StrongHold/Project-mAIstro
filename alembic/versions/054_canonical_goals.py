"""The canonical Goal store: `canonical_goals` and its append-only children.

`INTEROP_ONTOLOGY_V1` names `maistro.goals` the owner of the shared Goal
concept, and #1572 ships the store that makes the owner real: durable Goals
with an append-only revision chain and a recorded, attributed mutation
history. Three tables, mirroring the model's three surfaces:

  * **`canonical_goals`** — identity, Workspace/Project scope, the
    accountable Agent, Subgoal lineage (`parent_goal_id`), lifecycle state,
    and `current_revision`, the compare-and-set pointer every mutation is a
    guarded `UPDATE ... WHERE current_revision = ?` against.
  * **`canonical_goal_revisions`** — the immutable desired-state chain, one
    row per accepted revision, keyed `(goal_id, revision)`. Append-only: no
    code path rewrites or deletes a revision.
  * **`canonical_goal_transitions`** — recorded lifecycle moves and Agent
    reassignments, each carrying both sides of the change and the actor.

No execution state lives here: the canonical `Goal -> Graph -> Run ->
NodeRun -> Attempt` spine keeps its own primitives, and a Run carries its
Goal binding as payload provenance written once at admission (#1572).

Numbered 054 directly after `053_learning_lifecycle_columns`: this issue's
first draft took 053 off develop's 052 head; develop's own
`053_learning_lifecycle_columns` then landed on the same number (its
docstring records the same story one collision earlier, at 052). Renumbered
and re-parented onto develop's revision, per that precedent: one linear
head, no duplicate revision ids.

Revision ID: 054
Revises: 053
Create Date: 2026-10-03
"""

from __future__ import annotations

from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # IF NOT EXISTS, like 046/047: stamp-back and re-upgrade is a live repair
    # path, and the chain's contract is that re-applying a revision over the
    # schema it already built is adoption, not an error
    # (tests/migrations/test_migration_chain.py drives exactly that walk).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_goals (
            goal_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            agent_id TEXT NOT NULL,
            parent_goal_id TEXT
                REFERENCES canonical_goals (goal_id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            current_revision INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            updated_at TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_canonical_goals_project ON canonical_goals (project_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_goal_revisions (
            goal_id TEXT NOT NULL,
            revision INTEGER NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            payload JSONB NOT NULL,
            PRIMARY KEY (goal_id, revision),
            FOREIGN KEY (goal_id)
                REFERENCES canonical_goals (goal_id) ON DELETE CASCADE
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_goal_transitions (
            goal_id TEXT NOT NULL,
            seq INTEGER NOT NULL,
            at TIMESTAMPTZ NOT NULL,
            kind TEXT NOT NULL,
            payload JSONB NOT NULL,
            PRIMARY KEY (goal_id, seq),
            FOREIGN KEY (goal_id)
                REFERENCES canonical_goals (goal_id) ON DELETE CASCADE
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS canonical_goal_transitions")
    op.execute("DROP TABLE IF EXISTS canonical_goal_revisions")
    op.execute("DROP INDEX IF EXISTS idx_canonical_goals_project")
    op.execute("DROP TABLE IF EXISTS canonical_goals")
