"""Persist canonical capability Invocations and quota reservations (#1196).

Revision ID: 033
Revises: 032
Create Date: 2026-09-08

The quota scope lock makes admission atomic across workers. Reservations remain
in the database until settlement or explicit reconciliation, so a process loss
does not silently turn an in-flight provider effect into free capacity.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("invocation_quota_scopes", sa.Column("scope_key", sa.Text, primary_key=True))
    op.create_table(
        "invocation_quota_reservations",
        sa.Column("invocation_id", sa.Text, primary_key=True),
        sa.Column("reservation_id", sa.Text, nullable=False, unique=True),
        sa.Column("scope_key", sa.Text, nullable=False),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("project_id", sa.Text, nullable=False),
        sa.Column("principal_id", sa.Text, nullable=False),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("capability", sa.Text, nullable=False),
        sa.Column("requests", sa.Integer, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("images", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("state", sa.Text, nullable=False, server_default=sa.text("'reserved'")),
    )
    op.create_index(
        "ix_invocation_quota_reservations_scope_created",
        "invocation_quota_reservations",
        ["scope_key", "created_at", "state"],
    )
    op.create_table(
        "invocation_quota_usage",
        sa.Column("usage_id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("invocation_id", sa.Text, nullable=False, unique=True),
        sa.Column("scope_key", sa.Text, nullable=False),
        sa.Column("timestamp", sa.Float, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("images", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Float, nullable=False),
    )
    op.create_index(
        "ix_invocation_quota_usage_scope_timestamp",
        "invocation_quota_usage",
        ["scope_key", "timestamp"],
    )
    op.create_table(
        "capability_invocations",
        sa.Column("invocation_id", sa.Text, primary_key=True),
        sa.Column("run_id", sa.Text, nullable=False),
        sa.Column("node_run_id", sa.Text, nullable=False),
        sa.Column("attempt_id", sa.Text, nullable=False),
        sa.Column("binding_id", sa.Text, nullable=False),
        sa.Column("effect_key", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("created_at", sa.Float, nullable=False),
        sa.Column("payload_json", JSONB, nullable=False),
    )
    op.create_index(
        "ix_capability_invocation_effect",
        "capability_invocations",
        ["run_id", "node_run_id", "binding_id", "effect_key", "created_at", "invocation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_capability_invocation_effect", table_name="capability_invocations")
    op.drop_table("capability_invocations")
    op.drop_index("ix_invocation_quota_usage_scope_timestamp", table_name="invocation_quota_usage")
    op.drop_table("invocation_quota_usage")
    op.drop_index(
        "ix_invocation_quota_reservations_scope_created",
        table_name="invocation_quota_reservations",
    )
    op.drop_table("invocation_quota_reservations")
    op.drop_table("invocation_quota_scopes")
