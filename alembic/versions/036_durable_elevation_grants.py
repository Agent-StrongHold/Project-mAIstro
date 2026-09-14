"""Persist short-lived elevation grants in the canonical database."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "036"
down_revision = "035"
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
