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

Numbered 053 directly after `052_learning_stage_ladder`: one linear head, no
duplicate revision ids.

Revision ID: 053
Revises: 052
Create Date: 2026-10-03
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "053"
down_revision = "052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_goals",
        sa.Column("goal_id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("project_id", sa.Text, nullable=False),
        sa.Column("agent_id", sa.Text, nullable=False),
        sa.Column("parent_goal_id", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("current_revision", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_goal_id"],
            ["canonical_goals.goal_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("idx_canonical_goals_project", "canonical_goals", ["project_id"])
    op.create_table(
        "canonical_goal_revisions",
        sa.Column("goal_id", sa.Text, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.PrimaryKeyConstraint("goal_id", "revision"),
        sa.ForeignKeyConstraint(
            ["goal_id"],
            ["canonical_goals.goal_id"],
            ondelete="CASCADE",
        ),
    )
    op.create_table(
        "canonical_goal_transitions",
        sa.Column("goal_id", sa.Text, nullable=False),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.PrimaryKeyConstraint("goal_id", "seq"),
        sa.ForeignKeyConstraint(
            ["goal_id"],
            ["canonical_goals.goal_id"],
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("canonical_goal_transitions")
    op.drop_table("canonical_goal_revisions")
    op.drop_index("idx_canonical_goals_project", table_name="canonical_goals")
    op.drop_table("canonical_goals")
