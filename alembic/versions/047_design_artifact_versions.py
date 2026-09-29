"""Versioned creative artifact state: versions, locks, guidance, branch control (#780).

Four tables extending the design artifact surface with the identity a product
needs to preserve human+AI history:

* `design_artifact_versions` — the append-only change/version ledger. Every
  material change to a creative artifact lands as a new row carrying its
  lineage, parent version, fork relationship, producing human principal or
  canonical Run/NodeRun/Attempt, CreativeBrief reference, shared-decision
  inputs, and draft/accepted/rejected state. Content is never updated in
  place; UNIQUE (project_id, lineage_id, version) makes supersession
  first-writer-wins. The one mutation is the narrow review transition
  draft -> accepted/rejected, which changes no content.
* `design_artifact_locks` — explicit user locks (version/region/decision/
  branch). Release is an explicit action that records who released and when.
* `design_project_guidance` — durable user guidance recorded during active
  work; superseded rows stay readable (invalidation by supersession).
* `design_branch_controls` — per-branch control mode naming the canonical Run
  it is attached to. Product state projected onto canonical execution — pause,
  waiting and cancellation remain canonical Run states, not a second lifecycle.

`org_id` deliberately carries no foreign key: migration 024 removed the
placeholder `orgs`/`teams` anchors 003 had created — `org` is a soft scope
axis (ADR-068) enforced by stores, not by the schema — and these tables
follow the same shape as `design_projects.org_id` at chain tip.

Revision ID: 047
Revises: 046
Create Date: 2026-09-28
"""

from __future__ import annotations

from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS design_artifact_versions (
            id UUID PRIMARY KEY,
            org_id TEXT NOT NULL,
            project_id UUID NOT NULL REFERENCES design_projects(id) ON DELETE CASCADE,
            lineage_id TEXT NOT NULL,
            version INTEGER NOT NULL,
            kind TEXT NOT NULL,
            origin TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            format TEXT,
            content TEXT NOT NULL DEFAULT '',
            url TEXT,
            trust_tier TEXT NOT NULL DEFAULT 't3',
            state TEXT NOT NULL DEFAULT 'draft',
            parent_version INTEGER,
            fork_lineage_id TEXT,
            fork_version INTEGER,
            brief_ref TEXT,
            decision_inputs_json TEXT,
            author TEXT NOT NULL DEFAULT '',
            run_id TEXT,
            node_run_id TEXT,
            attempt_id TEXT,
            content_sha TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL,
            UNIQUE (project_id, lineage_id, version)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_artifact_versions_lineage "
        "ON design_artifact_versions (org_id, project_id, lineage_id, version)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_artifact_versions_run "
        "ON design_artifact_versions (run_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS design_artifact_locks (
            lock_id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            project_id UUID NOT NULL REFERENCES design_projects(id) ON DELETE CASCADE,
            lineage_id TEXT NOT NULL,
            scope TEXT NOT NULL,
            version INTEGER,
            address TEXT,
            decision_ref TEXT,
            decision_digest TEXT,
            reason TEXT NOT NULL DEFAULT '',
            created_by TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL,
            released_at TIMESTAMPTZ,
            released_by TEXT
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_artifact_locks_lineage "
        "ON design_artifact_locks (org_id, project_id, lineage_id, released_at)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS design_project_guidance (
            guidance_id TEXT PRIMARY KEY,
            org_id TEXT NOT NULL,
            project_id UUID NOT NULL REFERENCES design_projects(id) ON DELETE CASCADE,
            lineage_id TEXT,
            text TEXT NOT NULL,
            author TEXT NOT NULL DEFAULT '',
            run_id TEXT,
            created_at TIMESTAMPTZ NOT NULL,
            active BOOLEAN NOT NULL DEFAULT TRUE,
            superseded_by TEXT
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_project_guidance_lookup "
        "ON design_project_guidance (org_id, project_id, active)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS design_branch_controls (
            control_id UUID PRIMARY KEY,
            org_id TEXT NOT NULL,
            project_id UUID NOT NULL REFERENCES design_projects(id) ON DELETE CASCADE,
            lineage_id TEXT NOT NULL,
            mode TEXT NOT NULL,
            run_id TEXT,
            updated_by TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ NOT NULL,
            UNIQUE (project_id, lineage_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_design_branch_controls_lookup "
        "ON design_branch_controls (org_id, project_id, lineage_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS design_branch_controls")
    op.execute("DROP TABLE IF EXISTS design_project_guidance")
    op.execute("DROP TABLE IF EXISTS design_artifact_locks")
    op.execute("DROP TABLE IF EXISTS design_artifact_versions")
