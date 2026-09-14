"""Project membership becomes one row per (project, principal) (#38, #1148).

`canonical_project_memberships` was keyed on `membership_id` alone, and both
`PgProjectScopeStore.set_membership` and its SQLite twin minted a fresh
`membership_id` on every call (`ProjectMembership`'s `default_factory=_id`).
Two grants to the same `(project_id, principal_id)` therefore accumulated two
independent rows, and nothing removed either one:
`projects.authorization.resolve_project_authorization` unions every row it
finds at a Project, so an earlier grant a later explicit deny was meant to
narrow stayed live forever, and the protocol had no `remove_membership` to
retract a grant outright.

`canonical_workspace_memberships` (migration 019) already keys on
`(workspace_id, user_id)` for exactly this reason. This migration brings
Project membership to the same shape: one canonical current row per
`(project_id, principal_id)`, with `membership_id` kept as a stable identity
column rather than the uniqueness boundary -- `set_membership` now preserves
it (and the original `created_at`) across a re-grant/role-change/deny the way
`Project.project_id` already survives a `move_project`/`update_defaults`.

De-duplicates first, keeping the most recently created row per
`(project_id, principal_id)` -- ties broken on `membership_id` for a
deterministic choice -- so the new primary key can never fail to apply to
whatever an environment already holds.

Revision ID: 033
Revises: 032
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM canonical_project_memberships
            WHERE membership_id NOT IN (
                SELECT DISTINCT ON (project_id, principal_id) membership_id
                FROM canonical_project_memberships
                ORDER BY project_id, principal_id,
                         (payload->>'created_at')::timestamptz DESC,
                         membership_id DESC
            )
            """
        )
    )
    op.drop_constraint(
        "canonical_project_memberships_pkey",
        "canonical_project_memberships",
        type_="primary",
    )
    op.create_primary_key(
        "canonical_project_memberships_pkey",
        "canonical_project_memberships",
        ["project_id", "principal_id"],
    )
    op.drop_index(
        "ix_canonical_memberships_project_principal",
        table_name="canonical_project_memberships",
    )
    op.create_index(
        "ix_canonical_memberships_principal",
        "canonical_project_memberships",
        ["principal_id"],
    )


def downgrade() -> None:
    # Post-upgrade code preserves membership_id per (project_id, principal_id)
    # but no longer requires it to be globally unique, so two different pairs
    # could in principle end up sharing one (a caller-supplied identity from
    # e.g. a future import path). Restoring membership_id as the sole primary
    # key would then fail outright. Rather than delete either row, mint a
    # fresh, deterministic id for every row after the first in each duplicate
    # group -- every membership survives the downgrade; only the shared
    # identity is resolved.
    op.execute(
        sa.text(
            """
            UPDATE canonical_project_memberships AS m
            SET membership_id = m.membership_id || ':' || m.project_id || ':' || m.principal_id
            WHERE m.ctid NOT IN (
                SELECT DISTINCT ON (membership_id) ctid
                FROM canonical_project_memberships
                ORDER BY membership_id, project_id, principal_id
            )
            """
        )
    )
    op.drop_index(
        "ix_canonical_memberships_principal",
        table_name="canonical_project_memberships",
    )
    op.drop_constraint(
        "canonical_project_memberships_pkey",
        "canonical_project_memberships",
        type_="primary",
    )
    op.create_primary_key(
        "canonical_project_memberships_pkey",
        "canonical_project_memberships",
        ["membership_id"],
    )
    op.create_index(
        "ix_canonical_memberships_project_principal",
        "canonical_project_memberships",
        ["project_id", "principal_id"],
    )
