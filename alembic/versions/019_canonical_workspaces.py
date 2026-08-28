"""Canonical Workspace and WorkspaceMembership persistence (#37).

Workspace is the durable environment boundary in ADR-081226-9944. Until this
revision the canonical Workspace model had only an in-memory store while the
canonical Project/Run spine was durable in PostgreSQL. That inverted the
ownership hierarchy after restart: children survived their Workspace owner.

The Workspace row owns identity. Membership is a separate relation, matching
the accepted hierarchy rather than embedding users inside the Workspace
payload. Role is materialized as a column because last-owner protection needs a
transactional predicate; the full immutable-at-read model remains in JSONB.

This migration deliberately does not add a foreign key from the pre-existing
canonical_projects.workspace_id column. Existing installations may already
contain Project scope rows created before canonical Workspace persistence
existed. #38 owns reconciling/backfilling those historical scope anchors before
that constraint can be made fail-closed without fabricating Workspace records.

Revision ID: 019
Revises: 018
Create Date: 2026-08-27
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
        sa.Column("payload", postgresql.JSONB, nullable=False),
    )
    op.create_table(
        "canonical_workspace_memberships",
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "user_id"),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["canonical_workspaces.workspace_id"],
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "role IN ('member', 'contributor', 'owner')",
            name="ck_canonical_workspace_memberships_role",
        ),
    )
    op.create_index(
        "ix_canonical_workspace_memberships_user",
        "canonical_workspace_memberships",
        ["user_id", "workspace_id"],
    )
    op.create_index(
        "ix_canonical_workspace_memberships_owner",
        "canonical_workspace_memberships",
        ["workspace_id"],
        postgresql_where=sa.text("role = 'owner'"),
    )


def downgrade() -> None:
    op.drop_table("canonical_workspace_memberships")
    op.drop_table("canonical_workspaces")
