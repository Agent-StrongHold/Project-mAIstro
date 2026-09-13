"""Preserve canonical Invocation provenance in quota accounting (#718).

The aggregate quota row cannot provide at-most-once accounting or explain a
missing provider usage report by itself.  Keep one immutable evidence row per
canonical physical Invocation, then project it into the existing aggregate.

Revision ID: 035
Revises: 034
Create Date: 2026-09-08
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "quota_usage",
        sa.Column("unreported_count", sa.BigInteger, nullable=False, server_default="0"),
    )
    op.create_table(
        "quota_invocation_evidence",
        sa.Column("invocation_id", sa.Text, primary_key=True),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("cycle_key", sa.Text, nullable=False),
        sa.Column("input_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("usage_reported", sa.Boolean, nullable=False),
    )
    op.create_index(
        "ix_quota_invocation_evidence_provider_cycle",
        "quota_invocation_evidence",
        ["provider", "cycle_key"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_quota_invocation_evidence_provider_cycle",
        table_name="quota_invocation_evidence",
    )
    op.drop_table("quota_invocation_evidence")
    op.drop_column("quota_usage", "unreported_count")
