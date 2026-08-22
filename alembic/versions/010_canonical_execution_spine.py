"""The canonical execution spine in PostgreSQL (#132).

`Workspace/Project → Graph → Run → NodeRun → Attempt` had two homes and neither
was the durable system of record ADR-082226-5104 names: in-memory (lost on
restart) and SQLite (durable, but decision 9 says SQLite is not a canonical
datastore). After #41, a Run created by `POST /tasks` was the canonical
execution identity for exactly as long as the process lived.

The spine is the one thing that must not be ephemeral — it is what an audit, a
recovery, a retry and a resumed HITL pause all read.

Shape follows `runs/sqlite_store.py` and `projects/sqlite_scope_store.py`: a
JSONB payload holding the whole model, plus the few columns that are indexed or
constrained. Denormalising more would mean two sources of truth for the same
field and a migration every time a model gains one.

Three constraints do the real work, and all three are partial or composite
indexes PostgreSQL enforces rather than application checks:

  - one Root Project per Workspace;
  - one active Attempt per NodeRun;
  - dense per-parent ordinals.

Under SQLite those were belt-and-braces behind a whole-database write lock.
Here they are the primary defence, because PostgreSQL admits concurrent writers
and a check-then-insert between two of them is a race.

Revision ID: 010
Revises: 009
Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── canonical_projects ─────────────────────────────────────────
    op.create_table(
        "canonical_projects",
        sa.Column("project_id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("parent_project_id", sa.Text, nullable=True),
        sa.Column("is_root", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.ForeignKeyConstraint(
            ["parent_project_id"], ["canonical_projects.project_id"], ondelete="RESTRICT"
        ),
    )
    # A Workspace has exactly one Root Project. Enforced here rather than in the
    # store because two concurrent `create_root` calls would both see none.
    op.create_index(
        "ix_canonical_projects_one_root",
        "canonical_projects",
        ["workspace_id"],
        unique=True,
        postgresql_where=sa.text("is_root"),
    )
    op.create_index("ix_canonical_projects_parent", "canonical_projects", ["parent_project_id"])
    op.create_index("ix_canonical_projects_workspace", "canonical_projects", ["workspace_id"])

    op.create_table(
        "canonical_project_memberships",
        sa.Column("membership_id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("project_id", sa.Text, nullable=False),
        sa.Column("principal_id", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["canonical_projects.project_id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_canonical_memberships_project_principal",
        "canonical_project_memberships",
        ["project_id", "principal_id"],
    )

    op.create_table(
        "canonical_project_resources",
        sa.Column("resource_id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("project_id", sa.Text, nullable=False),
        sa.Column("resource_type", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.ForeignKeyConstraint(
            ["project_id"], ["canonical_projects.project_id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_canonical_resources_project_type",
        "canonical_project_resources",
        ["project_id", "resource_type"],
    )

    # ── canonical_runs ─────────────────────────────────────────────
    op.create_table(
        "canonical_runs",
        sa.Column("run_id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("project_id", sa.Text, nullable=False),
        sa.Column("parent_run_id", sa.Text, nullable=True),
        sa.Column("parent_node_run_id", sa.Text, nullable=True),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.ForeignKeyConstraint(["parent_run_id"], ["canonical_runs.run_id"]),
        # A Run belongs to a Project, and deleting the Project out from under it
        # would leave durable execution history pointing at nothing. RESTRICT
        # rather than CASCADE: Run history is the audit record, so the Project
        # deletion is the operation that must fail.
        sa.ForeignKeyConstraint(
            ["project_id"], ["canonical_projects.project_id"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_canonical_runs_workspace_project", "canonical_runs", ["workspace_id", "project_id"]
    )
    op.create_index("ix_canonical_runs_parent", "canonical_runs", ["parent_run_id"])
    # Not indexed for its own sake: recovery scans for Runs left mid-flight by a
    # process that died, and without this that is a sequential scan of every Run
    # the deployment has ever created.
    op.create_index(
        "ix_canonical_runs_live",
        "canonical_runs",
        ["status"],
        postgresql_where=sa.text("status NOT IN ('completed', 'failed', 'cancelled', 'timed_out')"),
    )

    # ── canonical_node_runs ────────────────────────────────────────
    op.create_table(
        "canonical_node_runs",
        sa.Column("node_run_id", sa.Text, primary_key=True),
        sa.Column("run_id", sa.Text, nullable=False),
        sa.Column("node_id", sa.Text, nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["canonical_runs.run_id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_canonical_node_runs_run_ordinal"),
    )
    op.create_index("ix_canonical_node_runs_run", "canonical_node_runs", ["run_id", "ordinal"])

    # `canonical_runs.parent_node_run_id` closes its loop only now that
    # canonical_node_runs exists — the two tables reference each other, so one
    # of the constraints has to be added after both are created.
    op.create_foreign_key(
        "fk_canonical_runs_parent_node_run",
        "canonical_runs",
        "canonical_node_runs",
        ["parent_node_run_id"],
        ["node_run_id"],
    )

    # ── canonical_attempts ─────────────────────────────────────────
    op.create_table(
        "canonical_attempts",
        sa.Column("attempt_id", sa.Text, primary_key=True),
        sa.Column("node_run_id", sa.Text, nullable=False),
        sa.Column("ordinal", sa.Integer, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.ForeignKeyConstraint(
            ["node_run_id"], ["canonical_node_runs.node_run_id"], ondelete="RESTRICT"
        ),
        sa.UniqueConstraint(
            "node_run_id", "ordinal", name="uq_canonical_attempts_node_run_ordinal"
        ),
    )
    op.create_index(
        "ix_canonical_attempts_node_run", "canonical_attempts", ["node_run_id", "ordinal"]
    )
    # The constraint the whole retry model rests on: at most one Attempt per
    # NodeRun may be non-terminal. Two workers racing to start the same node
    # both pass an application-level check; only one passes this.
    op.create_index(
        "ix_canonical_attempts_one_active",
        "canonical_attempts",
        ["node_run_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('created', 'running')"),
    )


def downgrade() -> None:
    op.drop_constraint("fk_canonical_runs_parent_node_run", "canonical_runs", type_="foreignkey")
    op.drop_table("canonical_attempts")
    op.drop_table("canonical_node_runs")
    op.drop_table("canonical_runs")
    op.drop_table("canonical_project_resources")
    op.drop_table("canonical_project_memberships")
    op.drop_table("canonical_projects")
