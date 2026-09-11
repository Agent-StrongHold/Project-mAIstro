"""Give the live Workspace Persona a durable canonical owner (#12).

The Persona model was previously process-local, so a restart could leave a
Workspace with no readable live product context and allowed durable deployments
to diverge from the in-memory one-Persona invariant. The Workspace foreign key
also makes deletion clean up the dependent Persona without creating a second
ownership path.

Revision ID: 034
Revises: 033
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "034"
down_revision = "033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_personas",
        sa.Column("persona_id", sa.Text, primary_key=True),
        sa.Column("workspace_id", sa.Text, nullable=False, unique=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["canonical_workspaces.workspace_id"], ondelete="CASCADE"
        ),
    )
    op.create_index("ix_canonical_personas_workspace", "canonical_personas", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_canonical_personas_workspace", table_name="canonical_personas")
    op.drop_table("canonical_personas")
