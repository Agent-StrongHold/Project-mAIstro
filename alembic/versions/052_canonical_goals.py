"""Canonical Goals and their append-only revisions (#1572).

`INTEROP_ONTOLOGY_V1` has named `maistro.goals` the owner of the Goal concept
since #458, and nothing implemented it. Migration 050 shows the cost:
`design_creative_briefs` carries `goal_id` and `goal_revision` columns with no
foreign key, because the table they reference did not exist. `BacklogItem`
carries the same pair. This revision creates what they point at.

A Goal is durable desired-outcome and accountability state, not a Run
lifecycle: one Goal may need zero, one or many Runs over its life, and a Run's
outcome is evidence for the next decision rather than a Goal transition. So
`canonical_goals` holds lifecycle and ownership, and `canonical_goal_revisions`
holds what the Goal wants, append-only.

`goal_revision` is an integer starting at 1, which is what every consumer that
landed first already reads -- `BacklogItem.goal_revision`,
`CreativeBrief.goal_revision` and the Design pack types, two of them `ge=1`.
Identity is the pair `(goal_id, goal_revision)`, and that pair is the primary
key: append-only ordering is then a property of the database rather than of a
read-then-write in one process, so two reconcilers racing the same next
revision both pass any Python-side check and exactly one survives the insert.

`current_revision` is an explicit pointer rather than "the newest row", so a
reader never races a concurrent revision. A historical Run keeps the revision
it was admitted against, which is what makes "what were we trying to do when
this ran" answerable after the Goal has moved on.

Adoption, not assumption (#286/#1194/#72 convention): live deployments may
have created these tables before the chain reached them, and the reapply path
(stamp-back + `upgrade head`) re-walks this revision over an existing schema.
So the DDL is `CREATE TABLE IF NOT EXISTS` plus `CREATE INDEX IF NOT EXISTS` --
a fresh table and an adopted one are built from the same definition, and an
adopted one is untouched.

Revision ID: 052
Revises: 051
Create Date: 2026-10-02
"""

from __future__ import annotations

from alembic import op

# Took `051` on parent `050_design_creative_briefs`, then develop's
# `051_canonical_run_eval_scores` (#792) claimed that same number on the
# same parent while this branch was open -- so this revision re-parents
# onto that `051` as `052`, the same renumbering this chain performs on
# every develop collision so it keeps exactly one linear head.
revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_goals (
            goal_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            owner_agent_id TEXT NOT NULL,
            parent_goal_id TEXT
                REFERENCES canonical_goals(goal_id) ON DELETE RESTRICT,
            state TEXT NOT NULL,
            current_revision INTEGER NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT ck_canonical_goals_workspace_not_blank
                CHECK (workspace_id <> ''),
            CONSTRAINT ck_canonical_goals_not_own_parent
                CHECK (parent_goal_id IS NULL OR parent_goal_id <> goal_id)
        )
        """
    )
    # What a persistent Workspace Agent asks on every wake: the non-terminal
    # Goals one Agent is accountable for in one Workspace (#805).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_canonical_goals_owner "
        "ON canonical_goals (workspace_id, owner_agent_id, state)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_canonical_goals_parent ON canonical_goals (parent_goal_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_canonical_goals_project "
        "ON canonical_goals (workspace_id, project_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_goal_revisions (
            goal_id TEXT NOT NULL
                REFERENCES canonical_goals(goal_id) ON DELETE RESTRICT,
            goal_revision INTEGER NOT NULL,
            payload JSONB NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (goal_id, goal_revision),
            CONSTRAINT ck_canonical_goal_revisions_positive
                CHECK (goal_revision >= 1)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS canonical_goal_revisions")
    op.execute("DROP INDEX IF EXISTS ix_canonical_goals_project")
    op.execute("DROP INDEX IF EXISTS ix_canonical_goals_parent")
    op.execute("DROP INDEX IF EXISTS ix_canonical_goals_owner")
    op.execute("DROP TABLE IF EXISTS canonical_goals")
