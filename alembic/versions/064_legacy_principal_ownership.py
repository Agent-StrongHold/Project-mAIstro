"""Migrate the installer-era ``default`` principal without dropping ownership.

Revision ID: 064
Revises: 063

The installer changes the credential's configured principal from ``default`` to
``conductor``.  That is an identity migration, so changing only ``API_KEYS``
would strand every row written before #843.  This migration is deliberately
one PostgreSQL transaction: the mapping is recorded first, ownership rows are
merged, and the old key is removed only after the new key is present.

The container entrypoint already serializes Alembic with an advisory lock.  The
mapping table and idempotent statements below are the database-level guard as
well: a crashed transaction rolls back, and a second replica converges to the
same mapping and rows.

Numbered 064, appending after develop's integrated ``063`` canonical-goals
head. The branch originally drafted this as ``036`` beside
``035_outcome_scope_thumb_index``, but develop's integrated history already
assigned the 036 identities (``036_consumer_cursors``,
``036_audit_log_org_scope``); claiming a sibling id would fork the chain into
two heads, and threading under develop's shipped migrations would rewrite
ancestry databases are already stamped with. Per the integration rule recorded
on ``063_canonical_goals``: merged identities keep their meaning, and a new
revision appends after the integrated head under an unused id.
"""

from __future__ import annotations

import hashlib

from alembic import op
from sqlalchemy import text

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None


# The migration uses a fixed mapping because this is the supported installer
# migration. A future user-selected identity migration must introduce its own
# explicit mapping rather than silently reusing this one.
def _fact_key(owner_user_id: str, statement: str) -> str:
    """Owner-bound statement digest, inlined from the application.

    Must stay byte-identical to ``maistro.memory.user_model.types.fact_key``
    as of this revision (``sha256(owner \x1f normalize_statement(statement))``);
    the live migration test pins the two together. Inlined rather than imported
    so the recorded migration never changes behavior with later app code.
    """
    normalized = " ".join(statement.split()).casefold()
    raw = "\x1f".join((owner_user_id, normalized))
    return hashlib.sha256(raw.encode()).hexdigest()


def upgrade() -> None:
    # IF NOT EXISTS, not bare CREATE: the chain's re-adoption contract
    # (stamp-back + re-upgrade, pinned by test_migration_chain.py) re-runs a
    # tip revision over the schema it already built, and the mapping table is
    # the one object this revision creates. The merge statements below are
    # already no-ops on a converged schema; the DDL must be too.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS principal_identity_mappings (
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
    # old/new deployment before deleting the legacy key.  Roles are a
    # capability ladder (owner ⊃ contributor ⊃ member, per
    # WorkspaceMembership.can_contribute/can_administer), so the strongest
    # role across both rows wins -- not just owner -- and the earliest
    # membership timestamp is retained.
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
                         WHEN canonical_workspace_memberships.role = 'contributor'
                           OR EXCLUDED.role = 'contributor' THEN 'contributor'
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
                       WHEN canonical_workspace_memberships.role = 'contributor'
                         OR EXCLUDED.role = 'contributor' THEN 'contributor'
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
    # ``tasks.user_id`` is the task-visibility boundary (the API scopes every
    # task read to the authenticated principal) and ``canvases.org_id`` is the
    # Canvas owner (`_owner_id(auth)`; reads 404 unless it matches), so both
    # follow the identity. The ``org_id`` columns are scope labels written from
    # the same authenticated principal (episodic/memory/audit scope filters,
    # Design artifact ownership), and ``elevation_grants.principal_id`` names
    # who may hold a durable elevation — leaving any of them behind would
    # strand the legacy principal's resources after the credential moves.
    # Exception: ``audit_log`` rows carrying an ADR-073 decision proof. The
    # Ed25519 proof signs ``canonical_audit_bytes``, which covers ``user_id``
    # and ``org_id``; retargeting either under an unchanged ``signature`` makes
    # the durable row fail ``PgAuditLog.verify()`` — precisely the tampering
    # the proof exists to detect. Signed rows are immutable evidence and keep
    # their original fields; a reader that must resolve the current principal
    # for one of them joins through ``principal_identity_mappings``.
    for table, column in (
        ("learnings", "user_id"),
        ("episodic_memories", "user_id"),
        ("outcomes", "user_id"),
        ("audit_log", "user_id"),
        ("tasks", "user_id"),
        ("tasks", "service_principal_id"),
        ("canvases", "org_id"),
        ("learnings", "org_id"),
        ("episodic_memories", "org_id"),
        ("outcomes", "org_id"),
        ("audit_log", "org_id"),
        ("learning_stage_transitions", "org_id"),
        ("design_projects", "org_id"),
        ("design_artifact_locks", "org_id"),
        ("design_artifact_versions", "org_id"),
        ("design_branch_controls", "org_id"),
        ("design_project_guidance", "org_id"),
        ("child_profiles", "org_id"),
        ("asset_definitions", "org_id"),
        ("asset_instances", "org_id"),
        ("books", "org_id"),
        ("user_model_facts", "owner_user_id"),
        ("user_model_statement_keys", "owner_user_id"),
        ("design_artifact_locks", "created_by"),
        ("design_creative_briefs", "created_by"),
    ):
        if table == "audit_log":
            op.execute(
                f"UPDATE {table} SET {column} = 'conductor'"
                f" WHERE {column} = 'default' AND signature = ''"
            )
        else:
            op.execute(f"UPDATE {table} SET {column} = 'conductor' WHERE {column} = 'default'")

    # ``user_model_statement_keys.fact_key`` is the table's primary key and the
    # owner-bound digest ``fact_key(owner, normalize_statement(statement))`` --
    # not a descriptive label. The bulk update above retargets the descriptive
    # ``owner_user_id`` column only, so a re-key is required too: left hashed
    # under ``default``, runtime promotion under ``conductor`` computes a
    # different digest, no longer resolves the migrated lineage, and files a
    # duplicate fact -- or, for a migrated tombstone, re-promotes wording the
    # owner had struck. Recompute the digest from the lineage's statement under
    # the canonical owner and merge collisions: a tombstoned lineage keeps the
    # key (the strike must survive the rename), an already-keyed conductor
    # lineage otherwise wins, and a legacy digest made redundant by the merge
    # is dropped. Idempotent: converged rows recompute to their own key.
    bind = op.get_bind()
    keyed = bind.execute(
        text(
            """
            SELECT DISTINCT ON (k.fact_key) k.fact_key, k.lineage_id, f.statement
              FROM user_model_statement_keys k
              JOIN user_model_facts f ON f.lineage_id = k.lineage_id
             WHERE k.owner_user_id IN ('default', 'conductor')
             ORDER BY k.fact_key, f.revision
            """
        )
    ).fetchall()
    for old_key, lineage_id, statement in keyed:
        new_key = _fact_key("conductor", statement)
        if new_key == old_key:
            continue
        claimed = bind.execute(
            text("SELECT lineage_id FROM user_model_statement_keys WHERE fact_key = :k"),
            {"k": new_key},
        ).scalar()
        tombstoned = bind.execute(
            text(
                "SELECT 1 FROM user_model_facts"
                " WHERE lineage_id = :l AND state = 'tombstoned' LIMIT 1"
            ),
            {"l": lineage_id},
        ).scalar()
        if claimed == lineage_id:
            # Same lineage under both digests; the legacy one is redundant.
            bind.execute(
                text("DELETE FROM user_model_statement_keys WHERE fact_key = :k"),
                {"k": old_key},
            )
            continue
        if claimed is not None and not tombstoned:
            # conductor already keyed this wording; its lineage stays canonical.
            bind.execute(
                text("DELETE FROM user_model_statement_keys WHERE fact_key = :k"),
                {"k": old_key},
            )
            continue
        if claimed is not None:
            # The migrated lineage is tombstoned: re-point the key at it so the
            # strike keeps blocking re-promotion under the canonical owner.
            bind.execute(
                text("DELETE FROM user_model_statement_keys WHERE fact_key = :k"),
                {"k": new_key},
            )
        bind.execute(
            text("UPDATE user_model_statement_keys SET fact_key = :n WHERE fact_key = :o"),
            {"n": new_key, "o": old_key},
        )

    # Durable elevation grants name who may hold an elevated capability; the
    # grant must follow the principal or the migrated operator loses it.
    op.execute(
        "UPDATE elevation_grants SET principal_id = 'conductor' WHERE principal_id = 'default'"
    )

    # Deliberately NOT migrated: ``task_idempotency``'s principal columns and
    # its sha256 ``scope_key``. A claim is TTL-bounded and can only be matched
    # by a request authenticating as its principal; the retired credential no
    # longer resolves, so the rows are unreachable history that the existing
    # ``expires_at`` purge retires. Recomputing the digest in SQL would be the
    # riskier path. The mapping row is the resolver for anything else that
    # reads a historical principal string out of an immutable payload.
    #
    # Also deliberately NOT migrated (append-only provenance, immutable
    # evidence): ``backlog_events.actor``, ``backlog_authority.actor`` and
    # ``learning_stage_transitions.actor``. These record who acted at the
    # time; rewriting them would destroy the historical attribution. The
    # mapping row (legacy_principal -> canonical_principal) resolves any
    # reader that needs the current identity for a historical actor string.

    # Strike state is keyed by principal and has a foreign-keyed violation log.
    # Merge state first, retarget violations second, then remove the old key.
    # Summing ``strike_count`` alone would leave enforcement stale: the ladder
    # in ``security.strikes`` derives ``disabled``/``locked_until``/scrutiny
    # from the count (>=3 disables, 2 locks, 1 elevates), so a mixed install
    # where neither row is disabled but the combined history crosses a rung
    # must re-derive its state. Re-apply the ladder to the merged count while
    # keeping whichever existing state is stricter: a disable from either side
    # stays, a still-future lock is preserved, and a merged count landing on
    # the locked rung locks from the later violation timestamp (the runtime's
    # ``LOCKOUT_DURATION`` is 8 hours).
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
               disabled = security_strikes.disabled OR EXCLUDED.disabled
                          OR security_strikes.strike_count + EXCLUDED.strike_count >= 3,
               scrutiny_level = CASE
                   WHEN security_strikes.disabled OR EXCLUDED.disabled
                        OR security_strikes.scrutiny_level = 'disabled'
                        OR EXCLUDED.scrutiny_level = 'disabled'
                        OR security_strikes.strike_count + EXCLUDED.strike_count >= 3
                       THEN 'disabled'
                   WHEN security_strikes.scrutiny_level = 'locked'
                        OR EXCLUDED.scrutiny_level = 'locked'
                        OR security_strikes.strike_count + EXCLUDED.strike_count = 2
                       THEN 'locked'
                   WHEN security_strikes.scrutiny_level = 'elevated'
                        OR EXCLUDED.scrutiny_level = 'elevated'
                        OR security_strikes.strike_count + EXCLUDED.strike_count >= 1
                       THEN 'elevated'
                   ELSE 'normal'
               END,
               locked_until = NULLIF(
                   GREATEST(
                       COALESCE(security_strikes.locked_until, '-infinity'::timestamptz),
                       COALESCE(EXCLUDED.locked_until, '-infinity'::timestamptz),
                       CASE
                           WHEN security_strikes.strike_count + EXCLUDED.strike_count = 2
                           THEN GREATEST(
                                    COALESCE(security_strikes.last_violation_at,
                                             '-infinity'::timestamptz),
                                    COALESCE(EXCLUDED.last_violation_at,
                                             '-infinity'::timestamptz)
                                ) + interval '8 hours'
                           ELSE '-infinity'::timestamptz
                       END
                   ),
                   '-infinity'::timestamptz
               ),
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
