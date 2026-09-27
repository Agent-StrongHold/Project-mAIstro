"""Persist short-lived elevation grants in the canonical database.

Rebased onto the trunk chain three times (#72 merge, the 2026-09 develop
sync, then the #1204 sync that brought `039_quota_usage_event_identity`):
the revision ids up to 038 were already taken by the canonical migrations,
so the table first attached as "039" — and when develop added its own
`039` (canvas job admission key) on the same parent "038", that collision
made `alembic history` fail outright ("042 overlaps with other requested
revisions 039"). It was renumbered to 043 on parent 042, and when develop
then landed its own #1204 migration `039_quota_usage_event_identity` on
the same parent 042, that left two heads — and when develop then landed
`044_canvas_store_tables` on `039_quota_usage_event_identity`, that took
"044" too. It therefore now attaches after develop's chain tip `044` as
`045`, keeping the chain linear with exactly one head.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "045"
down_revision = "044"
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
