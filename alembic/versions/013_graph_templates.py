"""Durable GraphTemplate registry (#145).

`Schedule.graph_template_id` has always been the field a firing resolves to
decide what to run, and nothing ever resolved it because there was nowhere to
look it up. This is that place.

Identity is `(template_id, version)`. `GraphTemplate` already treats version as
a separate axis — `_reusable_content` excludes `template_id`, `workspace_id` and
`version` from the content hash — so two versions of one template are the same
template with different topology.

`content_hash` is stored rather than recomputed on read for one reason: a Run's
`source_template` records the hash it instantiated from, and an audit asking
"was this Run built from what that version says today?" has to be able to
compare without materialising the model.

Revision ID: 013
Revises: 012
Create Date: 2026-08-22
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "graph_templates",
        sa.Column("template_id", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("template_id", "version", name="pk_graph_templates"),
        sa.CheckConstraint("version >= 1", name="ck_graph_templates_version"),
    )
    op.create_index("ix_graph_templates_workspace", "graph_templates", ["workspace_id", "name"])


def downgrade() -> None:
    op.drop_index("ix_graph_templates_workspace", table_name="graph_templates")
    op.drop_table("graph_templates")
