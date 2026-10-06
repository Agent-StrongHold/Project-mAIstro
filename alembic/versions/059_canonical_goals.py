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

Numbered 059, continuing develop's integrated 058 learning-validation provenance revision. The installed base
already carries two merged migration identities this store must not reuse:
develop received the user-model tables as ``056_user_model_facts`` (#1951's
merge ``c560d4c``) and planner stability as ``057_run_store_planner_stability``
(#1914's merge ``4675101``). A database those trees migrated stands stamped at
``056`` or ``057``; were this store to claim either id, ``upgrade head`` would
treat the Goal DDL as already applied and silently skip it. The earlier drafts
of this branch did exactly that renumber (Goals at ``056``, user-model moved
to ``057``, planner to ``058``) and the 2026-10-06 clarification on #1572
forbids it: merged identities keep their meaning and ancestry, and a new
revision appends after the integrated develop head under a centrally
coordinated, unused id. So this store restores develop's ``056``/``057``
byte-for-byte, leaves develop's ``058`` learning-validation provenance in
place, and appends here as ``059`` — one linear head, no duplicate revision
ids, and an installed base that upgrades forward without a stamp
edit (`tests/migrations/test_goal_installed_base_upgrade.py` drives exactly
that walk against real ``c560d4c``/``4675101`` databases).

Revision ID: 059
Revises: 058 (058_learning_validation_provenance)
Create Date: 2026-10-03
"""

from __future__ import annotations

from alembic import op

revision = "059"
down_revision = "058"
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
