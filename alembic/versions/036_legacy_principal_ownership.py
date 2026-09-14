"""Migrate the installer-era ``default`` principal without dropping ownership.

Revision ID: 036
Revises: 035 and 035_outcome_scope_thumb_index

The installer changes the credential's configured principal from ``default`` to
``conductor``.  That is an identity migration, so changing only ``API_KEYS``
would strand every row written before #843.  This migration is deliberately
one PostgreSQL transaction: the mapping is recorded first, ownership rows are
merged, and the old key is removed only after the new key is present.

The container entrypoint already serializes Alembic with an advisory lock.  The
mapping table and idempotent statements below are the database-level guard as
well: a crashed transaction rolls back, and a second replica converges to the
same mapping and rows.
"""

from __future__ import annotations

from alembic import op

revision = "036"
down_revision = ("035", "035_outcome_scope_thumb_index")
branch_labels = None
depends_on = None


# The migration uses a fixed mapping because this is the supported installer
# migration. A future user-selected identity migration must introduce its own
# explicit mapping rather than silently reusing this one.
def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE principal_identity_mappings (
            legacy_principal TEXT PRIMARY KEY,
            canonical_principal TEXT NOT NULL UNIQUE,
            migrated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        INSERT INTO principal_identity_mappings
            (legacy_principal, canonical_principal)
        VALUES ('default', 'conductor')
        ON CONFLICT (legacy_principal) DO UPDATE
            SET canonical_principal = EXCLUDED.canonical_principal
        """
    )

    # Workspace membership is a unique identity boundary.  Merge a mixed
    # old/new deployment before deleting the legacy key; owner wins and the
    # earliest membership timestamp is retained.
    op.execute(
        """
        INSERT INTO canonical_workspace_memberships
            (workspace_id, user_id, role, added_at, payload)
        SELECT workspace_id, 'conductor', role, added_at,
               jsonb_set(
                   jsonb_set(payload, '{user_id}', to_jsonb('conductor'::text), true),
                   '{role}', to_jsonb(role), true
               )
          FROM canonical_workspace_memberships
         WHERE user_id = 'default'
        ON CONFLICT (workspace_id, user_id) DO UPDATE
           SET role = CASE
                         WHEN canonical_workspace_memberships.role = 'owner'
                           OR EXCLUDED.role = 'owner' THEN 'owner'
                         ELSE canonical_workspace_memberships.role
                       END,
               added_at = LEAST(canonical_workspace_memberships.added_at, EXCLUDED.added_at),
               payload = jsonb_set(
                   jsonb_set(
                       canonical_workspace_memberships.payload,
                       '{user_id}', to_jsonb('conductor'::text), true
                   ),
                   '{role}',
                   to_jsonb(CASE
                       WHEN canonical_workspace_memberships.role = 'owner'
                         OR EXCLUDED.role = 'owner' THEN 'owner'
                       ELSE canonical_workspace_memberships.role
                   END),
                   true
               )
        """
    )
    op.execute("DELETE FROM canonical_workspace_memberships WHERE user_id = 'default'")

    # Project memberships also have a unique identity boundary.  Preserve all
    # grant/deny arrays when old and new rows overlap.
    op.execute(
        """
        INSERT INTO canonical_project_memberships
            (membership_id, workspace_id, project_id, principal_id, payload)
        SELECT membership_id, workspace_id, project_id, 'conductor',
               jsonb_set(payload, '{principal_id}', to_jsonb('conductor'::text), true)
          FROM canonical_project_memberships
         WHERE principal_id = 'default'
        ON CONFLICT (project_id, principal_id) DO UPDATE
           SET payload = jsonb_set(
               jsonb_set(
                   jsonb_set(
                       jsonb_set(
                           canonical_project_memberships.payload,
                           '{principal_id}', to_jsonb('conductor'::text), true
                       ),
                       '{grants}',
                       COALESCE(canonical_project_memberships.payload->'grants', '[]'::jsonb)
                           || COALESCE(EXCLUDED.payload->'grants', '[]'::jsonb),
                       true
                   ),
                   '{denies}',
                   COALESCE(canonical_project_memberships.payload->'denies', '[]'::jsonb)
                       || COALESCE(EXCLUDED.payload->'denies', '[]'::jsonb),
                   true
               ),
               '{delegable_grants}',
               COALESCE(canonical_project_memberships.payload->'delegable_grants', '[]'::jsonb)
                   || COALESCE(EXCLUDED.payload->'delegable_grants', '[]'::jsonb),
               true
           )
        """
    )
    op.execute("DELETE FROM canonical_project_memberships WHERE principal_id = 'default'")

    # Direct principal ownership columns.  These tables are either append-only
    # evidence or have no uniqueness boundary, so an in-place update is lossless.
    for table in (
        "learnings",
        "episodic_memories",
        "outcomes",
        "audit_log",
        "design_projects",
        "child_profiles",
        "asset_definitions",
        "asset_instances",
        "books",
    ):
        column = (
            "org_id"
            if table
            in {
                "design_projects",
                "child_profiles",
                "asset_definitions",
                "asset_instances",
                "books",
            }
            else "user_id"
        )
        op.execute(f"UPDATE {table} SET {column} = 'conductor' WHERE {column} = 'default'")

    # Strike state is keyed by principal and has a foreign-keyed violation log.
    # Merge state first, retarget violations second, then remove the old key.
    op.execute(
        """
        INSERT INTO security_strikes
            (user_id, strike_count, scrutiny_level, locked_until, disabled,
             last_violation_at, last_appeal, last_appeal_at, created_at, updated_at)
        SELECT 'conductor', strike_count, scrutiny_level, locked_until, disabled,
               last_violation_at, last_appeal, last_appeal_at, created_at, updated_at
          FROM security_strikes
         WHERE user_id = 'default'
        ON CONFLICT (user_id) DO UPDATE
           SET strike_count = security_strikes.strike_count + EXCLUDED.strike_count,
               disabled = security_strikes.disabled OR EXCLUDED.disabled,
               last_violation_at = GREATEST(
                   security_strikes.last_violation_at, EXCLUDED.last_violation_at
               ),
               last_appeal_at = GREATEST(
                   security_strikes.last_appeal_at, EXCLUDED.last_appeal_at
               ),
               updated_at = GREATEST(security_strikes.updated_at, EXCLUDED.updated_at)
        """
    )
    op.execute("UPDATE security_violations SET user_id = 'conductor' WHERE user_id = 'default'")
    op.execute("DELETE FROM security_strikes WHERE user_id = 'default'")

    # Rate-limit buckets are principal-labelled durable state.  Merge a mixed
    # bucket rather than resetting abuse history during the identity change.
    op.execute(
        """
        INSERT INTO security_rate_limits (key, window_start, count)
        SELECT replace(key, 'principal:default', 'principal:conductor'), window_start, count
          FROM security_rate_limits
         WHERE key = 'principal:default'
        ON CONFLICT (key, window_start) DO UPDATE
           SET count = security_rate_limits.count + EXCLUDED.count
        """
    )
    op.execute("DELETE FROM security_rate_limits WHERE key = 'principal:default'")

    # Run actor/provenance references are used by visibility checks, so they
    # follow the identity too.  The mapping row retains the historical fact
    # that these records were authored under the installer-era principal.
    op.execute(
        """
        UPDATE canonical_runs
           SET payload = jsonb_set(payload, '{actor_principal_id}',
                                   to_jsonb('conductor'::text), true)
         WHERE payload->>'actor_principal_id' = 'default'
        """
    )
    op.execute(
        """
        UPDATE canonical_event_log
           SET actor_id = 'conductor'
         WHERE actor_id = 'default'
        """
    )


def downgrade() -> None:
    # Do not reverse ownership: a downgrade cannot know whether a post-migration
    # row was newly created by conductor. The mapping is the durable evidence.
    op.drop_table("principal_identity_mappings")
