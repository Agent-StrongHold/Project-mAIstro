"""Persist short-lived elevation grants in the canonical database.

Rebased onto the trunk chain twice (#72 merge, then the 2026-09 develop
sync): the revision ids up to 038 were already taken by the canonical
migrations, so the table first attached as "039" — and when develop added
its own `039` (canvas job admission key) on the same parent "038", that
collision made `alembic history` fail outright ("042 overlaps with other
requested revisions 039"). It now attaches after the develop chain tip
`042`, keeping the chain linear with exactly one head.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "elevation_grants",
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("principal_id", sa.Text, nullable=False),
        sa.Column("action_class", sa.Text, nullable=False),
        sa.Column("kind", sa.Text, nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ttl_seconds", sa.Integer, nullable=False),
        sa.Column("signed_by", sa.Text, nullable=False),
        sa.Column("action_args_hash", sa.Text, nullable=True),
    )
    op.create_index(
        "idx_elevation_grants_lookup",
        "elevation_grants",
        ["principal_id", "action_class", "granted_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_elevation_grants_lookup", table_name="elevation_grants")
    op.drop_table("elevation_grants")
