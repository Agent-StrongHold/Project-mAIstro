"""Design project persistence schema — design_projects and design_outputs tables.

Adds tables for design project artifacts, discovery context, and trust tier tracking.
Complements canvas layer (canvases, layers) for design skill outputs.

Revision ID: 003
Revises: 002
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── orgs / teams — the scope tables this migration references ──
    #
    # This migration has never been able to run. Its design_projects foreign
    # keys point at `orgs` and `teams`, and no migration in this repository
    # creates either; the hand-written SQL twin of this file
    # (maistro-design/migrations/0003_design_projects_outputs.sql) even carries
    # the definitions commented out, under "Ensure orgs and teams tables exist
    # (from maistro-core)" — they do not exist in maistro-core. So
    # `alembic upgrade head` failed here with UndefinedTable against any
    # database this repo provisions, which is why nothing downstream of 003 was
    # ever reached (#122).
    #
    # Editing a released migration is normally wrong. It is right here
    # precisely because this one could not have been applied anywhere: there is
    # no deployed state for the edit to contradict. IF NOT EXISTS keeps it
    # idempotent for anyone who created the tables by hand to get past this.
    #
    # Column shapes are dictated by the referencing columns below: both ids are
    # TEXT. These are minimal scope anchors (ADR-068's soft `org` and `team`
    # axes), not a tenancy model — the hard tenant boundary stays Stronghold's.
    op.execute(
        "CREATE TABLE IF NOT EXISTS orgs (id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '')"
    )
    op.execute(
        "CREATE TABLE IF NOT EXISTS teams ("
        "id TEXT PRIMARY KEY, "
        "org_id TEXT REFERENCES orgs(id) ON DELETE CASCADE, "
        "name TEXT NOT NULL DEFAULT '')"
    )

    # ── design_projects (DesignProject) ────────────────────────────
    op.create_table(
        "design_projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.func.gen_random_uuid(),
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("skill_slug", sa.Text, nullable=False),
        sa.Column("design_system_slug", sa.Text, nullable=False),
        sa.Column("org_id", sa.Text, nullable=False),
        sa.Column("team_id", sa.Text, nullable=True),
        sa.Column("trust_tier", sa.Text, nullable=False, server_default="t3"),
        sa.Column("canvas_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("discovery_json", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["org_id"], ["orgs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="SET NULL"),
    )

    # Indexes for design_projects
    op.create_index("idx_design_projects_org_id", "design_projects", ["org_id"])
    op.create_index("idx_design_projects_org_skill", "design_projects", ["org_id", "skill_slug"])
    op.create_index("idx_design_projects_skill_slug", "design_projects", ["skill_slug"])
    # Descending index expressed as a text clause. `postgresql_order_by` is not
    # a SQLAlchemy dialect kwarg — it raised ArgumentError before a single
    # statement reached the database, which is the second reason this migration
    # never ran.
    op.create_index(
        "idx_design_projects_created_at",
        "design_projects",
        [sa.text("created_at DESC")],
    )

    # ── design_outputs (DesignOutput) ──────────────────────────────
    op.create_table(
        "design_outputs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.func.gen_random_uuid(),
        ),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("format", sa.Text, nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("trust_tier", sa.Text, nullable=False, server_default="t3"),
        sa.Column("metadata_json", postgresql.JSONB, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(["project_id"], ["design_projects.id"], ondelete="CASCADE"),
    )

    # Indexes for design_outputs
    op.create_index("idx_design_outputs_project_id", "design_outputs", ["project_id"])
    op.create_index("idx_design_outputs_format", "design_outputs", ["format"])
    # Descending index expressed as a text clause. `postgresql_order_by` is not
    # a SQLAlchemy dialect kwarg — it raised ArgumentError before a single
    # statement reached the database, which is the second reason this migration
    # never ran.
    op.create_index(
        "idx_design_outputs_created_at",
        "design_outputs",
        [sa.text("created_at DESC")],
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("idx_design_outputs_created_at")
    op.drop_index("idx_design_outputs_format")
    op.drop_index("idx_design_outputs_project_id")
    op.drop_index("idx_design_projects_created_at")
    op.drop_index("idx_design_projects_skill_slug")
    op.drop_index("idx_design_projects_org_skill")
    op.drop_index("idx_design_projects_org_id")

    # Drop tables
    op.drop_table("design_outputs")
    op.drop_table("design_projects")
