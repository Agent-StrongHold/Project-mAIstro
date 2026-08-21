"""ADR-040 / ADR-039: canvas asset tables.

Revision ID: 002
Revises: 001
Create Date: 2026-05-09

Adds the persistence layer for the ADR-039 typed canvas model:

- asset_definitions  — registered, named, reusable AssetDefinitions
- asset_sheets       — generated reference sheets, one per asset_id
- asset_instances    — placement of a definition (registered or inline)
                       on a canvas, with scene-graph parent_id +
                       parent_socket
- child_profiles     — the personalisation key
- books              — natural container for WorldStyle + StyleVolume[]

The legacy canvas tables (canvases, layers, generation_jobs,
composites) created elsewhere are unaffected by this migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── child_profiles ─────────────────────────────────────────────
    op.create_table(
        "child_profiles",
        sa.Column("profile_id", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("pronouns", sa.Text, nullable=True),
        sa.Column(
            "likeness_refs",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "accommodations",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("age_range", sa.Text, nullable=True),
        sa.Column("reading_level", sa.Text, nullable=True),
        sa.Column("org_id", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ── asset_definitions ──────────────────────────────────────────
    op.create_table(
        "asset_definitions",
        sa.Column("asset_id", sa.Text, primary_key=True),
        sa.Column("kind", sa.Text, nullable=False, index=True),
        sa.Column("base_prompt", sa.Text, nullable=False),
        sa.Column(
            "sockets",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("skin_set", postgresql.JSONB, nullable=True),
        sa.Column("default_world_style", postgresql.JSONB, nullable=True),
        sa.Column("pose_geometry", postgresql.JSONB, nullable=True),
        sa.Column("org_id", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ── asset_sheets ───────────────────────────────────────────────
    op.create_table(
        "asset_sheets",
        sa.Column(
            "asset_id",
            sa.Text,
            sa.ForeignKey("asset_definitions.asset_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("refs", postgresql.JSONB, nullable=False),
        sa.Column("sheet_image", sa.Text, nullable=False),
        sa.Column("revision", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column(
            "generation_params",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # ── asset_instances ────────────────────────────────────────────
    op.create_table(
        "asset_instances",
        sa.Column("instance_id", sa.Text, primary_key=True),
        sa.Column("canvas_id", sa.Text, nullable=False, index=True),
        sa.Column(
            "definition_id",
            sa.Text,
            sa.ForeignKey("asset_definitions.asset_id", ondelete="RESTRICT"),
            nullable=True,
            index=True,
        ),
        sa.Column("inline_definition", postgresql.JSONB, nullable=True),
        sa.Column(
            "parent_id",
            sa.Text,
            sa.ForeignKey("asset_instances.instance_id", ondelete="SET NULL"),
            nullable=True,
            index=True,
        ),
        sa.Column("parent_socket", sa.Text, nullable=True),
        sa.Column(
            "transform",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("slot", postgresql.JSONB, nullable=True),
        sa.Column("anchor", sa.Text, nullable=True),
        sa.Column(
            "occlusion",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text('\'{"in_front_of": [], "behind": []}\'::jsonb'),
        ),
        sa.Column("personalization", postgresql.JSONB, nullable=True),
        sa.Column("skin_binding", postgresql.JSONB, nullable=True),
        sa.Column("prompt_nudge", sa.Text, nullable=True),
        sa.Column("visible", sa.Boolean, nullable=False, server_default=sa.text("TRUE")),
        sa.Column("locked", sa.Boolean, nullable=False, server_default=sa.text("FALSE")),
        sa.Column(
            "history",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("z_index", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "(definition_id IS NULL) <> (inline_definition IS NULL)",
            name="exactly_one_definition",
        ),
    )

    # ── books ──────────────────────────────────────────────────────
    op.create_table(
        "books",
        sa.Column("book_id", sa.Text, primary_key=True),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("world_style", postgresql.JSONB, nullable=False),
        sa.Column(
            "style_volumes",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "profile_id",
            sa.Text,
            sa.ForeignKey("child_profiles.profile_id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("org_id", sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("books")
    op.drop_table("asset_instances")
    op.drop_table("asset_sheets")
    op.drop_table("asset_definitions")
    op.drop_table("child_profiles")
