"""The Workspace gets a durable home of its own (#516).

`canonical_projects.workspace_id`, `canonical_runs.workspace_id` and their
siblings have always been bare `Text` columns with nothing to reference,
because there was no Workspace table to reference. Migration 012 gave the
Project tree a system of record and left the thing those Projects belong to
without one: `maistro.workspaces` shipped `InMemoryWorkspaceStore` and nothing
else, so the only Workspaces that survived a restart were the ones the
Conductor kept in its own SQLite store, under its own model, beside a
`workspace_id` space core knew nothing about.

Two tables, mirroring how 012 split Projects from their memberships:

  * **`canonical_workspaces`** — identity. `workspace_id`, `name`, and the
    payload the model round-trips through, same JSONB convention as
    `canonical_projects`.
  * **`canonical_workspace_memberships`** — access, keyed on
    `(workspace_id, user_id)` so one user has one role in one Workspace, with
    `ON DELETE CASCADE` from the Workspace. `WorkspaceStore.delete` cascades
    memberships in Python; the constraint is what makes that true of a row
    deleted any other way.

`role` is a real column rather than only a payload key, because "does this
Workspace still have an owner" is a question the database has to answer. The
store takes a row lock on the Workspace before demoting or removing a
membership, and the partial index below is what makes that question cheap:
without it, every demotion scans the membership table.

No foreign key from `canonical_projects.workspace_id` to the new table. There
are existing rows carrying Workspace ids that no Workspace record owns, and
backfilling a constraint over them is its own migration with its own failure
modes — it belongs with the convergence that gives those rows one owner (#37),
not with the table that makes the owner expressible.

Revision ID: 019
Revises: 018
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_workspaces",
        sa.Column("workspace_id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
    )
    # `list_for_user` orders by this, and it is the only ordering the protocol
    # promises.
    op.create_index("ix_canonical_workspaces_created", "canonical_workspaces", ["created_at"])

    op.create_table(
        "canonical_workspace_memberships",
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["canonical_workspaces.workspace_id"], ondelete="CASCADE"
        ),
    )
    # `list_for_user` reads memberships by user and then the Workspaces they
    # name, so this is the index that keeps the first half from scanning.
    op.create_index(
        "ix_canonical_workspace_memberships_user",
        "canonical_workspace_memberships",
        ["user_id"],
    )
    # "Does this Workspace still have an owner" is asked on every demotion and
    # every membership removal. A partial index over owners alone answers it
    # without walking a Workspace's whole roster.
    op.create_index(
        "ix_canonical_workspace_memberships_owner",
        "canonical_workspace_memberships",
        ["workspace_id"],
        postgresql_where=sa.text("role = 'owner'"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_canonical_workspace_memberships_owner",
        table_name="canonical_workspace_memberships",
    )
    op.drop_index(
        "ix_canonical_workspace_memberships_user",
        table_name="canonical_workspace_memberships",
    )
    op.drop_table("canonical_workspace_memberships")
    op.drop_index("ix_canonical_workspaces_created", table_name="canonical_workspaces")
    op.drop_table("canonical_workspaces")
