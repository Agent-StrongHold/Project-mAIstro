"""Quota admission tables and canonical Invocation usage evidence.

Revision ID: 043_invocation_quota_door
Revises: 047
Create Date: 2026-09-27

The effect door's budget reservations (#1196) and the at-most-once provider
usage evidence (#718) attach to the canonical Invocation. They follow the
current chain tip so they do not reuse revision ids 033/035/036, which
develop already assigned. Re-parented onto each new develop head as this
branch has stayed open -- 046, now 047: a migration must append after the
deployed head, never fork beside it, or `alembic upgrade head` refuses with
multiple heads.

Capability approvals are created here when missing: the SQLite store
already bootstraps that table, and PostgreSQL needs the same
effect-identity unique key without a second Invocation DDL.

Revision identifiers stay within Alembic's 32-character version_num column.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "043_invocation_quota_door"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE quota_usage ADD COLUMN IF NOT EXISTS "
        "unreported_count BIGINT NOT NULL DEFAULT 0"
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
    op.create_table(
        "capability_approvals",
        sa.Column("request_id", sa.Text, primary_key=True),
        sa.Column("run_id", sa.Text, nullable=False),
        sa.Column("node_run_id", sa.Text, nullable=False),
        sa.Column("binding_id", sa.Text, nullable=False),
        sa.Column("effect_key", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "node_run_id",
            "binding_id",
            "effect_key",
            name="uq_capability_approval_effect",
        ),
    )


def downgrade() -> None:
    op.drop_table("capability_approvals")
    op.drop_table("invocation_quota_evidence")
    op.drop_index("idx_invocation_quota_alloc_budget", table_name="invocation_quota_allocations")
    op.drop_table("invocation_quota_allocations")
    op.drop_table("invocation_quota_reservations")
    op.drop_table("invocation_quota_budgets")
    op.drop_index(
        "ix_quota_invocation_evidence_provider_cycle",
        table_name="quota_invocation_evidence",
    )
    op.drop_table("quota_invocation_evidence")
    op.drop_column("quota_usage", "unreported_count")
