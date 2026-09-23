"""Persist canonical capability Binding authority (#55, #1079).

Revision ID: 040
Revises: 039
Create Date: 2026-09-07

Renumbered twice: first from 032 after develop took that id
(`032_asset_instance_org_scope`) while this branch was open, the same
collision revision 035's own docstring records for that id; then from 039
after develop independently landed `039_canvas_job_admission_key` (#1531)
while this branch was open a second time — both migrations claimed
`revision = "039"` with `down_revision = "038"`, an Alembic branch collision
(two heads at 038) that crash-looped the app container on startup running
migrations, not a git conflict either merge surfaced. Only `capability_bindings`
is created here now: this migration originally also created the capability
Invocation ledger table, but revision 035 already owns it under a schema that
landed separately (a `revision` column, JSONB payload, and the active-effect
unique index) — creating it again here would collide. The DDL for
`capability_bindings` itself is otherwise untouched.

Bindings are immutable authorization/configuration records; JSON payload
columns preserve the complete Pydantic records while the projected columns
make scope lookups indexed and auditable.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "040"
down_revision = "039"
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


def downgrade() -> None:
    op.drop_index("idx_capability_binding_scope", table_name="capability_bindings")
    op.drop_table("capability_bindings")
