"""Deleted Workspaces stay deleted, and new Projects cannot outlive the fact.

Revision ID: 069
Revises: 068

Two fences for the one-Workspace-authority contract (#37), both appended
behind the shipped stores rather than rewritten into them:

**`canonical_workspace_deletions`** — the tombstone. `PgWorkspaceStore.delete`
now inserts the id here in the same transaction that removes the Workspace
row, and `create` refuses a tombstoned id inside the transaction that would
mint it. Without the table, "deleted" is a fact only an absent row can carry,
so any evidence-shaped record — a stale Hive convergence mirror, a lost
import journal replayed by `_migrate_one`, a provisioning helper that kept
the id in configuration — could resurrect deleted authority by creating the
row again. The tombstone is evidence that survives the absence: it commits
with the delete or not at all.

**`canonical_projects` → `canonical_workspaces` foreign key.** Migration 019
deferred it because legacy rows carried Workspace ids nothing owned and
backfilling a constraint over them "belongs with the convergence that gives
those rows one owner (#37)". This is that migration. The constraint is added
``NOT VALID``: PostgreSQL enforces it for every row written from now on —
no new orphan admission is possible, at the database, for any writer,
including ones that never call `create_root_in` — while existing rows are
deliberately not scanned, because failing the migration on rows that predate
the fence would trade a data-quality problem for an upgrade blocker.

**Orphan disposition (non-destructive, auditable).** Historical Project rows
whose Workspace id has no canonical Workspace are moved, not deleted: each is
copied into `canonical_orphan_project_quarantine` with its full payload and
the reason it was held out, then removed from the live tree together with the
memberships and resources that reference only it. Provenance survives in the
quarantine table; nothing references a quarantined Workspace id again. Rows
that own Runs are left in place untouched — `canonical_runs.project_id` is
``ON DELETE RESTRICT``, so removing them would require rewriting the
execution spine's history, which no disposition in this issue authorizes.
They stay readable exactly as they are (historical Run scope is immutable)
and stay un-admittable: `create_root_in` refuses their Workspace id and the
tombstone it writes keeps it refused. For those leftover rows the foreign key
is ``NOT VALID`` precisely so their presence cannot block the fence for new
rows. An operator may later quarantine them by hand and ``VALIDATE
CONSTRAINT`` to tighten the guarantee; that runbook is the approved
disposition, not a migration-time bulk rewrite.

SQLite carries no legacy orphan population to migrate (its schema is created
by the stores themselves), so the twin fences there are the transactional
Workspace-existence check in `create_root_in` and the
`canonical_workspace_deletions` table in `SqliteWorkspaceStore.ensure_schema`.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None

_QUARANTINE_REASON = "workspace_missing_at_fk_adoption"

# Bounded leaf-first removal, mirroring `PgProjectScopeStore.purge_workspace_in`:
# children before parents, because the self-referencing parent link is
# `ON DELETE RESTRICT`. A run-owning orphan is excluded from the leaves rather
# than tolerated failing: its `canonical_runs` RESTRICT would abort the whole
# DELETE statement — every leaf in that pass, not just the run-owning row —
# and the upgrade would die mid-disposition. Excluded, it stays live (its
# history is immutable) and the loop still terminates when a pass removes
# nothing else.
_PURGE_PASSES = 64


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_workspace_deletions (
            workspace_id TEXT PRIMARY KEY,
            deleted_at TIMESTAMPTZ NOT NULL
        )
        """
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS canonical_orphan_project_quarantine (
            project_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            parent_project_id TEXT,
            is_root BOOLEAN NOT NULL,
            payload JSONB NOT NULL,
            reason TEXT NOT NULL,
            quarantined_at TIMESTAMPTZ NOT NULL
        )
        """
    )

    conn = op.get_bind()

    # The disposition is one statement per phase so the whole upgrade is a
    # single PostgreSQL transaction (Alembic's default online): a crash
    # between phases rolls the quarantine copy and the removal back together,
    # never leaving a row copied but not removed or vice versa.
    conn.execute(
        text(
            """
            INSERT INTO canonical_orphan_project_quarantine
                (project_id, workspace_id, parent_project_id, is_root,
                 payload, reason, quarantined_at)
            SELECT p.project_id, p.workspace_id, p.parent_project_id, p.is_root,
                   p.payload, :reason, now()
              FROM canonical_projects p
             WHERE NOT EXISTS (
                   SELECT 1 FROM canonical_workspaces w
                    WHERE w.workspace_id = p.workspace_id)
               AND NOT EXISTS (
                   SELECT 1 FROM canonical_orphan_project_quarantine q
                    WHERE q.project_id = p.project_id)
            """
        ),
        {"reason": _QUARANTINE_REASON},
    )

    # Tombstone the orphan ids too: an id that was used to carry scope
    # without ever owning a Workspace must not be importable or re-creatable
    # later — that is the resurrection path this issue exists to close.
    conn.execute(
        text(
            """
            INSERT INTO canonical_workspace_deletions
                (workspace_id, deleted_at)
            SELECT DISTINCT q.workspace_id, now()
              FROM canonical_orphan_project_quarantine q
              ON CONFLICT (workspace_id) DO NOTHING
            """
        )
    )

    conn.execute(
        text(
            """
            DELETE FROM canonical_project_memberships m
             USING canonical_orphan_project_quarantine q
             WHERE m.project_id = q.project_id
            """
        )
    )
    conn.execute(
        text(
            """
            DELETE FROM canonical_project_resources r
             USING canonical_orphan_project_quarantine q
             WHERE r.project_id = q.project_id
            """
        )
    )
    for _ in range(_PURGE_PASSES):
        result = conn.execute(
            text(
                """
                WITH leaves AS (
                    SELECT q.project_id
                      FROM canonical_orphan_project_quarantine q
                     WHERE EXISTS (
                           SELECT 1 FROM canonical_projects p
                            WHERE p.project_id = q.project_id)
                       AND NOT EXISTS (
                           SELECT 1 FROM canonical_projects c
                            WHERE c.parent_project_id = q.project_id)
                       AND NOT EXISTS (
                           SELECT 1 FROM canonical_runs r
                            WHERE r.project_id = q.project_id)
                )
                DELETE FROM canonical_projects p
                 USING leaves l
                 WHERE p.project_id = l.project_id
                """
            )
        )
        if result.rowcount == 0:
            break

    conn.execute(
        text(
            """
            DELETE FROM canonical_project_memberships m
             WHERE NOT EXISTS (
                   SELECT 1 FROM canonical_projects p
                    WHERE p.project_id = m.project_id)
               AND NOT EXISTS (
                   SELECT 1 FROM canonical_workspaces w
                    WHERE w.workspace_id = m.workspace_id)
            """
        )
    )
    conn.execute(
        text(
            """
            DELETE FROM canonical_project_resources r
             WHERE NOT EXISTS (
                   SELECT 1 FROM canonical_projects p
                    WHERE p.project_id = r.project_id)
               AND NOT EXISTS (
                   SELECT 1 FROM canonical_workspaces w
                    WHERE w.workspace_id = r.workspace_id)
            """
        )
    )

    # Enforced for every row written from this revision onward; existing rows
    # are intentionally not scanned (``NOT VALID``), per the disposition above.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                 WHERE conname = 'fk_canonical_projects_workspace'
                   AND conrelid = 'canonical_projects'::regclass
            ) THEN
                ALTER TABLE canonical_projects
                    ADD CONSTRAINT fk_canonical_projects_workspace
                    FOREIGN KEY (workspace_id)
                    REFERENCES canonical_workspaces (workspace_id)
                    ON DELETE RESTRICT
                    NOT VALID;
            END IF;
        END
        $$;
        """
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE canonical_projects DROP CONSTRAINT IF EXISTS fk_canonical_projects_workspace"
    )
    op.execute("DROP TABLE IF EXISTS canonical_orphan_project_quarantine")
    op.execute("DROP TABLE IF EXISTS canonical_workspace_deletions")
