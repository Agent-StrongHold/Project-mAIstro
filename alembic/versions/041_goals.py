"""Canonical Goals and their append-only revisions (#1572).

Revision ID: 041
Revises: 036_audit_log_org_scope
Create Date: 2026-09-25

Follows `036_audit_log_org_scope`, the current single head (itself parented
on 040), so the chain stays linear.

A Goal belongs to one Project, and `project_id` is `ON DELETE RESTRICT` like
every other child of `canonical_projects`: a Project delete can never take a
Goal's append-only history with it, however it races a Goal insert. Goals go
with their Workspace instead, deleted explicitly by the Project stores'
`purge_workspace_in` before the Projects; revisions cascade from their Goal. A Subgoal's
parent is held to the same Project by the composite foreign key on
`(parent_goal_id, project_id)` against the `(goal_id, project_id)` unique
constraint, so the database refuses a cross-Project parent on its own.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "041"
down_revision = "036_audit_log_org_scope"
branch_labels = None
depends_on = None

_STATES = "'active', 'satisfied', 'cancelled', 'failed', 'superseded'"


def upgrade() -> None:
    op.create_table(
        "goals",
        sa.Column("goal_id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("parent_goal_id", sa.Text(), nullable=True),
        sa.Column("owner_agent_id", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("current_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"state IN ({_STATES})", name="ck_goals_state"),
        sa.CheckConstraint("current_revision >= 1", name="ck_goals_current_revision"),
        sa.UniqueConstraint("goal_id", "project_id", name="uq_goals_goal_project"),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["canonical_projects.project_id"],
            name="fk_goals_project",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_goal_id", "project_id"],
            ["goals.goal_id", "goals.project_id"],
            name="fk_goals_parent_same_project",
            ondelete="CASCADE",
        ),
    )
    op.create_index("idx_goals_project", "goals", ["project_id", "created_at"])
    op.create_index("idx_goals_parent", "goals", ["parent_goal_id", "project_id"])
    op.create_index(
        "idx_goals_active_owner",
        "goals",
        ["workspace_id", "owner_agent_id"],
        postgresql_where=sa.text("state = 'active'"),
    )
    op.create_table(
        "goal_revisions",
        sa.Column("goal_id", sa.Text(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("owner_agent_id", sa.Text(), nullable=False),
        sa.Column("desired_state", sa.Text(), nullable=False),
        sa.Column("success_conditions", sa.Text(), nullable=False),
        sa.Column("stop_conditions", sa.Text(), nullable=False),
        sa.Column("author_principal_id", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("goal_id", "revision", name="pk_goal_revisions"),
        sa.CheckConstraint("revision >= 1", name="ck_goal_revisions_revision"),
        sa.ForeignKeyConstraint(
            ["goal_id"],
            ["goals.goal_id"],
            name="fk_goal_revisions_goal",
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    op.drop_table("goal_revisions")
    op.drop_index("idx_goals_active_owner", table_name="goals")
    op.drop_index("idx_goals_parent", table_name="goals")
    op.drop_index("idx_goals_project", table_name="goals")
    op.drop_table("goals")
