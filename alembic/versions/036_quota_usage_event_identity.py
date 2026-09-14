"""Persist quota event identities for crash-safe retries (#1204)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "036_quota_usage_event_identity"
down_revision = ("035", "035_outcome_scope_thumb_index")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quota_usage_events",
        sa.Column("event_id", sa.Text, primary_key=True),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("cycle_key", sa.Text, nullable=False),
        sa.Column("input_tokens", sa.BigInteger, nullable=False),
        sa.Column("output_tokens", sa.BigInteger, nullable=False),
    )


def downgrade() -> None:
    op.drop_table("quota_usage_events")
