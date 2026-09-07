"""Persist canonical capability Binding and Invocation authority (#55, #1079).

Revision ID: 032
Revises: 031
Create Date: 2026-09-07

Bindings are immutable authorization/configuration records. Invocations are the
logical external-effect ledger whose COMPLETED/UNKNOWN history must survive a
worker or process restart so recovery can deduplicate or refuse an unsafe
replay. JSON payload columns preserve the complete Pydantic records while the
projected columns make scope/effect lookups indexed and auditable.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "032"
down_revision = "031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "capability_bindings",
        sa.Column("binding_id", sa.Text(), primary_key=True),
        sa.Column("workspace_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("capability", sa.Text(), nullable=False),
        sa.Column("node_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_capability_binding_scope",
        "capability_bindings",
        ["workspace_id", "project_id", "capability", "binding_id"],
    )

    op.create_table(
        "capability_invocations",
        sa.Column("invocation_id", sa.Text(), primary_key=True),
        sa.Column("run_id", sa.Text(), nullable=False),
        sa.Column("node_run_id", sa.Text(), nullable=False),
        sa.Column("attempt_id", sa.Text(), nullable=False),
        sa.Column("binding_id", sa.Text(), nullable=False),
        sa.Column("effect_key", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
    )
    op.create_index(
        "idx_capability_invocation_effect",
        "capability_invocations",
        ["run_id", "node_run_id", "binding_id", "effect_key", "created_at", "invocation_id"],
    )
    op.create_index(
        "idx_capability_invocation_attempt",
        "capability_invocations",
        ["attempt_id", "created_at", "invocation_id"],
    )


def downgrade() -> None:
    op.drop_index("idx_capability_invocation_attempt", table_name="capability_invocations")
    op.drop_index("idx_capability_invocation_effect", table_name="capability_invocations")
    op.drop_table("capability_invocations")
    op.drop_index("idx_capability_binding_scope", table_name="capability_bindings")
    op.drop_table("capability_bindings")
