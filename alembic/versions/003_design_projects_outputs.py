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
        # No foreign keys on org_id/team_id. They referenced `orgs.id` and
        # `teams.id`, which no migration creates and no model defines — so this
        # migration could not apply to any database, and because alembic runs
        # the chain under transactional DDL it took 001 and 002 down with it:
        # `alembic upgrade head` on an empty database left *zero* tables (#177).
        #
        # Plain scoped columns is also what the architecture calls for, not just
        # what makes this run. Every sibling table — learnings, outcomes,
        # episodic_memories, asset_definitions, books, child_profiles — already
        # models org_id/team_id this way. Per CLAUDE.md decision 7 and ADR-019,
        # maistro-core carries the *soft* scope axes (global -> org -> team ->
        # user -> agent -> session) and only the *hard* tenant boundary is
        # Stronghold's. A scope axis is a label, not a foreign key into a
        # tenancy table core owns, which is why there is no `orgs` table to
        # point at. The indexes below are what these columns are for.
    )

    # Indexes for design_projects
    op.create_index("idx_design_projects_org_id", "design_projects", ["org_id"])
    op.create_index("idx_design_projects_org_skill", "design_projects", ["org_id", "skill_slug"])
    op.create_index("idx_design_projects_skill_slug", "design_projects", ["skill_slug"])
    # `sa.text("created_at DESC")`, not `postgresql_order_by=` — that argument
    # does not exist, and SQLAlchemy raises ArgumentError rather than ignoring
    # it. Unreachable until the dangling foreign keys above were fixed, because
    # the migration failed three statements earlier (#177). The descending
    # order is kept rather than dropped: these indexes exist for "most recent
    # first" reads.
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
    # `sa.text("created_at DESC")`, not `postgresql_order_by=` — that argument
    # does not exist, and SQLAlchemy raises ArgumentError rather than ignoring
    # it. Unreachable until the dangling foreign keys above were fixed, because
    # the migration failed three statements earlier (#177). The descending
    # order is kept rather than dropped: these indexes exist for "most recent
    # first" reads.
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
