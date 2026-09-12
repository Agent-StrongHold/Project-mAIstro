"""Durable Workspace lifecycle state for crash reconciliation (#1121).

The Workspace row and its Root Project are owned by different stores, so they
cannot share a PostgreSQL transaction through the public store protocol.  This
journal makes the boundary explicit: ``creating`` and ``deleting`` rows are
never visible through the canonical Workspace store and are retried during
startup until both halves converge.

Revision ID: 034
Revises: 033
Create Date: 2026-09-10
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_workspace_lifecycle",
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("state", sa.Text, nullable=False, server_default="active"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("workspace_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["canonical_workspaces.workspace_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "state IN ('creating', 'active', 'deleting')",
            name="canonical_workspace_lifecycle_state_check",
        ),
    )
    # A writer running the previous release inserts Workspace rows without a
    # journal row. Rolling upgrades run both versions at once, and the new
    # version reads through an inner join on the journal, so such a row would
    # be invisible for good once the old replica retires. The database
    # journals every new Workspace as `active` itself; the new writer's staged
    # `creating` row overrides that default in its own transaction.
    op.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION canonical_workspace_lifecycle_default()
            RETURNS trigger AS $$
            BEGIN
                INSERT INTO canonical_workspace_lifecycle (workspace_id, state)
                VALUES (NEW.workspace_id, 'active')
                ON CONFLICT (workspace_id) DO NOTHING;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
    )
    op.execute(
        sa.text(
            """
            CREATE TRIGGER canonical_workspace_lifecycle_default
            AFTER INSERT ON canonical_workspaces
            FOR EACH ROW EXECUTE FUNCTION canonical_workspace_lifecycle_default()
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO canonical_workspace_lifecycle (workspace_id, state)
            SELECT workspace_id, 'active' FROM canonical_workspaces
            ON CONFLICT (workspace_id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP TRIGGER IF EXISTS canonical_workspace_lifecycle_default ON canonical_workspaces"
        )
    )
    op.execute(sa.text("DROP FUNCTION IF EXISTS canonical_workspace_lifecycle_default()"))
    op.drop_table("canonical_workspace_lifecycle")
