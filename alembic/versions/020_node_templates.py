"""Durable NodeTemplate registry (#556).

`GraphTemplate` has had a durable home since #145 (revision 014). `NodeTemplate`
had none, so half the template model could not survive a restart: a Node records
`source_template` naming a `(template_id, version)` and a content hash, and with
no NodeTemplate table there was nothing for that provenance to resolve against
after a process died. SPEC-081226-bb3a AC-12 asks that a template and its
instantiated object resolve the same provenance across a reopen; it could hold
for one of the two template families.

The shape mirrors `graph_templates` deliberately -- same identity
`(template_id, version)`, same stored `content_hash`, same JSONB payload -- so
the two registries cannot drift into answering the same question differently.
`node_type` is the one extra column: it is the discriminator a catalog lists by,
and reading it out of the payload for every row would make the obvious query a
table scan of JSON.

`content_hash` is stored rather than recomputed on read for the reason 014
records: a Node's `source_template` carries the hash it was instantiated from,
and an audit asking "was this Node built from what that version says today?" has
to compare without materialising the model.

Revision ID: 020
Revises: 019
Create Date: 2026-08-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "020"
down_revision = "019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "node_templates",
        sa.Column("template_id", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("workspace_id", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("node_type", sa.Text, nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("payload", postgresql.JSONB, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("NOW()"),
        ),
        sa.PrimaryKeyConstraint("template_id", "version", name="pk_node_templates"),
        sa.CheckConstraint("version >= 1", name="ck_node_templates_version"),
    )
    op.create_index("ix_node_templates_workspace", "node_templates", ["workspace_id", "name"])


def downgrade() -> None:
    op.drop_index("ix_node_templates_workspace", table_name="node_templates")
    op.drop_table("node_templates")
