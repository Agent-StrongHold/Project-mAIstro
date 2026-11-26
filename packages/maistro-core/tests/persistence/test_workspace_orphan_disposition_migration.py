"""Migration 069's orphan disposition, replayed end to end on a live server (#37).

The admission fence and the tombstone prove that *no new* orphan can be
minted. This file proves the other half of the disposition: what the migration
does to orphan rows that already exist when it runs. Migration 019 deferred the
`canonical_projects` → `canonical_workspaces` foreign key because legacy rows
carried Workspace ids nothing owned; 069 adopted the constraint `NOT VALID`
and gave those rows their disposition in the same transaction:

- non-run-owning orphans are copied into `canonical_orphan_project_quarantine`
  with their full payload and the reason they were held out (provenance
  survives), then removed from the live tree leaf-first;
- run-owning orphans stay live — `canonical_runs.project_id` is
  ``ON DELETE RESTRICT`` and rewriting execution history is no disposition
  this issue authorizes — but their Workspace ids are still tombstoned, so
  the ghost id can never be re-created into authority over them;
- every orphan's Workspace id lands in `canonical_workspace_deletions`, so
  neither a convergence import nor a provisioning helper can later mint the
  Workspace the orphan rows were waiting for.

To exercise this, the file downgrades the target database to revision 068 —
the last revision without the fence — seeds orphan trees that only 068
accepts, and upgrades back to head. Without `MAISTRO_TEST_PG_DSN` the module
skips; `MAISTRO_REQUIRE_PG_LEGS` turns that skip into a failure in the jobs
that own a server.

The downgrade drops the tombstone and quarantine tables with it; the upgrade
re-creates both. Anything those tables recorded for *earlier* tests is
per-run scratch (unique uuid ids), so no live authority depends on rows this
round trip legitimately rebuilds.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

from maistro.testing.postgres import postgres_dsn

pytest.importorskip("asyncpg")

pytestmark = pytest.mark.skipif(
    not postgres_dsn(),
    reason="set MAISTRO_TEST_PG_DSN to a migrated PostgreSQL database to run these",
)


def _alembic_root() -> Path:
    """The directory holding the repo's own alembic.ini."""
    root = Path(__file__)
    while root.parent != root:
        if (root / "alembic.ini").is_file():
            return root
        root = root.parent
    else:  # pragma: no cover - the repo layout is fixed
        pytest.fail("alembic.ini not found above this test")


def _alembic(dsn: str, *args: str) -> subprocess.CompletedProcess[str]:
    """One alembic command in a subprocess aimed at this test's database.

    The round trip has to stay out of process: `alembic/env.py` runs
    `fileConfig()`, whose default `disable_existing_loggers=True` tears down
    every logger the pytest process already holds -- caplog's handler
    included -- so every later log-assertion in the session reads an empty
    `caplog.text` and fails. CI runs this file at the front of one long
    shared session (quality.yml's coverage-postgres invocation walks
    persistence -> runs -> workspaces -> ...), where that is a rail of
    downstream failures that are all green in isolation. Same shape as
    `tests/migrations/test_migration_chain.py::_alembic`, which subprocesses
    for the same reason.
    """
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(_alembic_root()),
        # env.py resolves one URL through DATABASE_URL; scope the answer to
        # the subprocess instead of mutating this process's environment.
        env={**os.environ, "DATABASE_URL": dsn},
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )


def _alembic_or_fail(dsn: str, *args: str) -> None:
    result = _alembic(dsn, *args)
    if result.returncode != 0:
        pytest.fail(
            f"alembic {' '.join(args)} failed "
            f"(rc={result.returncode}):\n{result.stdout}\n{result.stderr}"
        )


async def _seed_orphans(dsn: str) -> dict[str, str]:
    """Orphan trees only the pre-fence schema accepts, keyed for assertions."""
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        ghost_a = f"ghost-a-{uuid4().hex}"
        ghost_b = f"ghost-run-{uuid4().hex}"
        root_a = f"proj-{uuid4().hex}"
        child_a = f"proj-{uuid4().hex}"
        root_b = f"proj-{uuid4().hex}"
        # A root, its child, a membership and a resource — the full leaf-first
        # removal the disposition walks.
        await conn.execute(
            """INSERT INTO canonical_projects
                   (project_id, workspace_id, parent_project_id, is_root, payload)
               VALUES ($1, $2, NULL, TRUE, '{"name": "orphan root"}'::text::jsonb)""",
            root_a,
            ghost_a,
        )
        await conn.execute(
            """INSERT INTO canonical_projects
                   (project_id, workspace_id, parent_project_id, is_root, payload)
               VALUES ($1, $2, $3, FALSE, '{"name": "orphan child"}'::text::jsonb)""",
            child_a,
            ghost_a,
            root_a,
        )
        await conn.execute(
            """INSERT INTO canonical_project_memberships
                   (membership_id, workspace_id, project_id, principal_id, payload)
               VALUES ($1, $2, $3, 'legacy-principal', '{}'::text::jsonb)""",
            f"mem-{uuid4().hex}",
            ghost_a,
            root_a,
        )
        # A run-owning orphan: the RESTRICT the purge must respect.
        await conn.execute(
            """INSERT INTO canonical_projects
                   (project_id, workspace_id, parent_project_id, is_root, payload)
               VALUES ($1, $2, NULL, TRUE, '{"name": "run-owning orphan"}'::text::jsonb)""",
            root_b,
            ghost_b,
        )
        await conn.execute(
            """INSERT INTO canonical_runs (run_id, workspace_id, project_id, status, payload)
               VALUES ($1, $2, $3, 'completed', '{}'::text::jsonb)""",
            f"run-{uuid4().hex}",
            ghost_b,
            root_b,
        )
        return {
            "ghost_a": ghost_a,
            "ghost_b": ghost_b,
            "root_a": root_a,
            "child_a": child_a,
            "root_b": root_b,
        }
    finally:
        await conn.close()


async def _fetch_all(dsn: str, sql: str):
    import asyncpg

    conn = await asyncpg.connect(dsn)
    try:
        return await conn.fetch(sql)
    finally:
        await conn.close()


async def test_the_orphan_disposition_preserves_provenance_and_refuses_new_orphans() -> None:
    import asyncpg

    dsn = postgres_dsn()
    upgraded = False
    try:
        # Seed at 068: the pre-fence schema is what accepted these rows, so
        # the downgrade has to happen before the orphans exist.
        _alembic_or_fail(dsn, "downgrade", "068")
        seeded = await _seed_orphans(dsn)
        _alembic_or_fail(dsn, "upgrade", "head")
        upgraded = True

        quarantine = await _fetch_all(
            dsn,
            "SELECT project_id, workspace_id, payload, reason FROM canonical_orphan_project_quarantine",
        )
        by_id = {row["project_id"]: row for row in quarantine}

        # Provenance: both removed rows are held out with their payload and a
        # reason that names what happened, not just a bare delete.
        assert seeded["root_a"] in by_id
        assert seeded["child_a"] in by_id
        held = by_id[seeded["root_a"]]
        assert held["workspace_id"] == seeded["ghost_a"]
        # No JSON codec on this raw connection: the payload arrives as text.
        assert json.loads(held["payload"])["name"] == "orphan root"
        assert held["reason"] == "workspace_missing_at_fk_adoption"

        live = await _fetch_all(
            dsn,
            f"SELECT project_id FROM canonical_projects WHERE workspace_id IN ('{seeded['ghost_a']}', '{seeded['ghost_b']}')",
        )
        live_ids = {row["project_id"] for row in live}
        # The tree with no runs is removed from the live table entirely...
        assert seeded["root_a"] not in live_ids
        assert seeded["child_a"] not in live_ids
        # ...while the run-owning orphan stays readable exactly as it was.
        assert seeded["root_b"] in live_ids

        # Every orphan Workspace id is tombstoned: the ghost id can never be
        # minted into authority over the rows it once falsely owned.
        tombstones = await _fetch_all(
            dsn,
            f"SELECT workspace_id FROM canonical_workspace_deletions WHERE workspace_id IN ('{seeded['ghost_a']}', '{seeded['ghost_b']}')",
        )
        assert {row["workspace_id"] for row in tombstones} == {
            seeded["ghost_a"],
            seeded["ghost_b"],
        }

        # And the constraint any writer meets from now on: a fresh orphan
        # insert is refused at the database, with the constraint by name.
        conn = await asyncpg.connect(dsn)
        try:
            with pytest.raises(asyncpg.exceptions.ForeignKeyViolationError) as excinfo:
                await conn.execute(
                    """INSERT INTO canonical_projects
                           (project_id, workspace_id, parent_project_id, is_root, payload)
                       VALUES ($1, $2, NULL, TRUE, '{}'::text::jsonb)""",
                    f"proj-{uuid4().hex}",
                    f"ghost-fresh-{uuid4().hex}",
                )
            assert "fk_canonical_projects_workspace" in str(excinfo.value)
        finally:
            await conn.close()
    finally:
        # Whatever the assertions did, leave the database migrated: a later
        # suite must meet head. The caller's environment was never touched.
        if not upgraded:
            _alembic_or_fail(dsn, "upgrade", "head")


async def test_a_tombstoned_orphan_workspace_id_cannot_gain_authority_over_its_history() -> None:
    """The disposition's resurrection path, closed at the store (#37).

    A run-owning orphan stays live for history's sake. Its Workspace id has
    no canonical row and a tombstone instead, so `PgWorkspaceStore.create` —
    the only door into authority — refuses: nothing can later mint the
    Workspace those historical rows were waiting for and claim them.
    """
    import asyncpg

    from maistro.projects.pg_scope_store import PgProjectScopeStore
    from maistro.workspaces.model import WorkspaceDeleted
    from maistro.workspaces.pg_store import PgWorkspaceStore

    dsn = postgres_dsn()
    ghost = f"ghost-tomb-{uuid4().hex}"
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "INSERT INTO canonical_workspace_deletions (workspace_id, deleted_at)"
            " VALUES ($1, now())",
            ghost,
        )
    finally:
        await conn.close()

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        store = PgWorkspaceStore(pool, project_store=PgProjectScopeStore(pool))
        with pytest.raises(WorkspaceDeleted):
            await store.create(creator_user_id="u1", name="Ghost", workspace_id=ghost)
        # And the ghost never became a Workspace: the historical rows it once
        # carried scope for still have no owner to be claimed by.
        assert await store.get(ghost) is None
    finally:
        await pool.close()
