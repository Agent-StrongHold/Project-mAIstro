"""Persist canonical Invocation quota reservations (#55)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "invocation_quota_budgets",
        sa.Column("budget_id", sa.Text, primary_key=True),
        sa.Column("definition", postgresql.JSONB, nullable=False),
    )
    op.create_table(
        "invocation_quota_reservations",
        sa.Column("invocation_id", sa.Text, primary_key=True),
        sa.Column("identity", postgresql.JSONB, nullable=False),
        sa.Column("state", sa.Text, nullable=False),
        sa.Column("reason", sa.Text, nullable=False, server_default=""),
        sa.Column("revision", sa.Integer, nullable=False, server_default="-1"),
    )
    op.create_table(
        "invocation_quota_allocations",
        sa.Column(
            "invocation_id",
            sa.Text,
            sa.ForeignKey("invocation_quota_reservations.invocation_id"),
            nullable=False,
        ),
        sa.Column(
            "budget_id",
            sa.Text,
            sa.ForeignKey("invocation_quota_budgets.budget_id"),
            nullable=False,
        ),
        sa.Column("maximum", sa.BigInteger, nullable=False),
        sa.Column("held", sa.BigInteger, nullable=False),
        sa.Column("spent", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("measured", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("invocation_id", "budget_id"),
    )
    op.create_index(
        "idx_invocation_quota_alloc_budget",
        "invocation_quota_allocations",
        ["budget_id"],
    )
    op.create_table(
        "invocation_quota_evidence",
        sa.Column(
            "invocation_id",
            sa.Text,
            sa.ForeignKey("invocation_quota_reservations.invocation_id"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer, nullable=False),
        sa.Column("evidence_id", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.PrimaryKeyConstraint("invocation_id", "revision"),
        sa.UniqueConstraint("invocation_id", "evidence_id"),
    )


def downgrade() -> None:
    op.drop_table("invocation_quota_evidence")
    op.drop_index("idx_invocation_quota_alloc_budget", table_name="invocation_quota_allocations")
    op.drop_table("invocation_quota_allocations")
    op.drop_table("invocation_quota_reservations")
    op.drop_table("invocation_quota_budgets")
