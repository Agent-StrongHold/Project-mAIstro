"""Durable CreativeBrief versions — the Design Studio shared-context contract (#774).

A CreativeBrief is the versioned creative projection of one canonical Project
Goal revision (DESIGN-STUDIO.md; #773/#774). Runs and artifacts must be able
to state exactly which Goal revision and which CreativeBrief version they
consumed — forever — so the table is append-only: no update path exists, and
a redirect creates a new version rather than rewriting history. That is also
why there is no deletion path and retention stays `undecided` on #325, like
`design_outputs`: these rows are the provenance the immutability contract
exists to protect.

Scope follows the canonical spine, not the soft `org` axis: the brief names
its `workspace_id` and `project_id`, the store refuses a Project registered
to a different Workspace, and the foreign key keeps `project_id` pointing at
a real canonical Project (RESTRICT — deleting a Project out from under its
creative provenance must fail, exactly as it does for `canonical_runs`).

The payload column holds the full validated CreativeBrief document; the
identity columns exist so scope/version/goal queries index instead of
scanning JSONB. `uq_design_creative_briefs_lineage_version` is the authority
behind first-writer-wins version minting.

Adoption, not assumption (#286/#1194/#72 convention): live deployments may
have created this table before the chain reached it, and the reapply path
(stamp-back + `upgrade head`) re-walks this revision over an existing schema.
So the DDL is `CREATE TABLE IF NOT EXISTS` plus `CREATE INDEX IF NOT EXISTS` —
a fresh table and an adopted one are built from the same definition, and an
adopted one is untouched. An adopted table created without the foreign key
keeps working; the store's paired (project, workspace) check carries the
scope guarantee regardless.

Revision ID: 050
Revises: 049
Create Date: 2026-09-28
"""

from __future__ import annotations

from alembic import op

# Renumbered from `047` to `049` as develop collisions claimed 047 and 048
# (#1133's durable Binding revocations, #398's Canvas job retry backoff), then
# to `050` when #780's design-artifact version ledger took `049` first — the
# same renumbering every develop collision performs so the chain keeps exactly
# one linear head. The eval-score evidence (#792), which had taken `049` on
# develop before this branch's ledger claimed the same number on the same
# parent, re-parents onto this `050` as `051`.
revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS design_creative_briefs (
            brief_id TEXT PRIMARY KEY,
            lineage_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            supersedes_brief_id TEXT,
            workspace_id TEXT NOT NULL,
            project_id TEXT NOT NULL
                REFERENCES canonical_projects(project_id) ON DELETE RESTRICT,
            goal_id TEXT NOT NULL,
            goal_revision INTEGER NOT NULL,
            payload JSONB NOT NULL,
            created_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_design_creative_briefs_lineage_version
                UNIQUE (lineage_id, version),
            CONSTRAINT ck_design_creative_briefs_workspace_not_blank
                CHECK (workspace_id <> '')
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_design_creative_briefs_lineage "
        "ON design_creative_briefs (workspace_id, lineage_id, version)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_design_creative_briefs_project_goal "
        "ON design_creative_briefs (workspace_id, project_id, goal_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_design_creative_briefs_project_goal")
    op.execute("DROP INDEX IF EXISTS ix_design_creative_briefs_lineage")
    op.execute("DROP TABLE IF EXISTS design_creative_briefs")
