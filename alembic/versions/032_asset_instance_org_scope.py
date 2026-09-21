"""Asset instances carry their org scope explicitly (#857).

Revision ID: 032
Revises: 031
Create Date: 2026-09-02

``asset_definitions``, ``child_profiles`` and ``books`` were created with an
``org_id`` column in 002, but ``asset_instances`` was not, and nothing read
the column on any of them: the asset store neither persisted nor filtered a
scope, so the tables' org axis was decorative. This migration gives instances
the column the store now predicates on.

The default is ``''`` rather than a fake single-org value: the org axis is
soft (ADR-068), legacy rows name no scope, and rows that name none are not
readable under any scope — absence is the safe answer for an unscoped row,
not an implicit grant of every scope.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "asset_instances",
        sa.Column("org_id", sa.Text, nullable=False, server_default=sa.text("''")),
    )
    op.create_index(
        "ix_asset_instances_org_id",
        "asset_instances",
        ["org_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_asset_instances_org_id", table_name="asset_instances")
    op.drop_column("asset_instances", "org_id")
