---
inventory-delta:
  packages/maistro-core/tests: +37
  packages/hive-conductor/backend/tests: +4
---

# #37 Workspace/Membership authority fence (+37, +4)

The reopened P0: `WorkspaceRoutingAdmitter.admitter_for` returned a cached
admitter or minted a Root Project for any non-blank Workspace id without
canonical existence verification, `canonical_projects` carried no foreign key
to `canonical_workspaces` (migration 019 explicitly deferred it), and
deletion was a fact only an absent row could carry — so a stale convergence
mirror, a lost import journal, or a kept-in-configuration id could resurrect
deleted authority. Production change: an admission fence verified on every
`create_root` call (cache hit included), a `canonical_workspace_deletions`
tombstone written in the delete's transaction on every store, the deferred
foreign key added `NOT VALID` (migration 073, renumbered past develop's landed 072 working log) with a non-destructive orphan
disposition, and `_migrate_one` quarantining a legacy source whose id the
canonical store refuses instead of replaying it. Five node groups over two
suites:

`packages/maistro-core/tests/workspaces/test_workspace_tombstones.py` (new,
+18): the deleted id is dead on memory, SQLite and PostgreSQL. Each store
refuses `create` on a tombstoned id with `WorkspaceDeleted`, the tombstone
commits with the delete or not at all, a rolled-back delete leaves the id
re-creatable (its Workspace still exists), and the durable rows survive a
fully disconnected store — the restart half of the contract. The PostgreSQL
leg runs against the migrated database wherever `MAISTRO_TEST_PG_DSN` is set
and skips otherwise, exactly like the rest of the conformance suites.

`packages/maistro-core/tests/projects/test_create_root_workspace_fence.py`
(new, +6): `create_root` — the write every admission path rides on — mints
only for a Workspace a bound authority owns, on the reference store and on
SQLite (provisioned database refuses; never-provisioned database keeps the
pre-#37 behaviour and that escape is pinned so it cannot silently widen).
PostgreSQL's fence is proven against a real server in the persistence file
below, because a mocked connection cannot prove a row lock serializes a
delete.

`packages/maistro-core/tests/persistence/test_workspace_scope_fence_pg.py`
(new, +7): the same fence against live PostgreSQL — unknown and deleted ids
refused with zero resulting rows, resurrection refused from a fresh pool,
the `fk_canonical_projects_workspace` constraint refusing a root for a ghost
Workspace for a writer that bypasses the store entirely, the `FOR UPDATE`
row lock making an admission wait behind a delete holding the Workspace
lock, a committed delete stranding no root from a racing admission, and
id/membership/Root surviving a new pool (the new-process restart leg).
Skips without `MAISTRO_TEST_PG_DSN`.

`packages/maistro-core/tests/persistence/test_workspace_orphan_disposition_migration.py`
(new, +2): migration 073's orphan disposition replayed end to end —
downgrade to 068, seed orphan trees only the pre-fence schema accepts,
upgrade to head. Non-run-owning orphans land in
`canonical_orphan_project_quarantine` with their payload and a named reason
(provenance preserved), are removed from the live tree, and every orphan
Workspace id is tombstoned; a run-owning orphan stays live (its Run history
is immutable) while its ghost id remains un-mintable, and a fresh orphan
insert is refused by the foreign key, by name. This suite caught a real
defect in the first cut of the purge: a run-owning leaf made the whole
leaf-purge DELETE abort on the runs RESTRICT, killing the upgrade — the
leaves CTE now excludes run-owning rows explicitly. Skips without
`MAISTRO_TEST_PG_DSN`.

`packages/maistro-core/tests/tasks/test_workspace_routing.py` (+4): the
router-level fence — an unknown Workspace fails before any Project/Run write,
a cached admitter stops admitting the moment the Workspace is deleted (and
the failed submission leaves no Run), the cache stays stable while the
Workspace lives (per-call verification must not re-bind mid-flight), and the
default Workspace is verified like any other.

`packages/hive-conductor/backend/tests/test_workspace_authority_durable.py`
(+4): `test_a_completed_import_that_loses_its_journal_still_cannot_resurrect_a_deleted_workspace`
parametrized over the sqlite/postgres hive mirrors × lost/corrupt journal.
The Hive-local journal is not authority: with the journal gone or unreadable
after another client deleted the canonical Workspace, `_migrate_one` refuses
at `create` (the tombstone holds) and quarantines the source instead of
reimporting — stable across two process restarts, membership never revived.

The migration-disposition file above is also where the disposition contract
earned its keep: the first cut of 069's leaf purge aborted on a run-owning
orphan (RESTRICT violation aborts the statement, not the row), which is
exactly the class of defect a replayed downgrade/upgrade catches and a
schema-shape comparison cannot.

The remaining ~25 modified test files are fixture provisioning, not new
nodes: every PG-backed fixture that used to ask a bare `create_root` for a
scratch id now provisions the canonical Workspace first (through
`PgWorkspaceStore.create` in production's own order, via the idempotent
`maistro.testing.postgres.provision_workspace` helper), because the fence
now refuses exactly the orphan admission those fixtures were accidentally
exercising. `tests/conftest.py`'s scratch-truncate list deliberately never
included `canonical_workspaces`, so the helper is get-then-create.

Focused command:

```text
uv run pytest packages/maistro-core/tests/workspaces packages/maistro-core/tests/projects packages/maistro-core/tests/tasks/test_workspace_routing.py packages/maistro-core/tests/persistence packages/maistro-core/tests/runs packages/hive-conductor/backend/tests -q
```

## Regression proof (local, merge base `33ac30c5f1`)

`test_workspace_routing.py`'s four new cases fail at the base commit with
`ProjectNotFound` where the fence should raise `WorkspaceNotFound` (the router
minted the orphan Root instead of refusing), and
`test_workspace_tombstones.py`'s refusal cases fail with `ValueError` /
duplicate-root errors (`create` did not know the id was dead). The negative
tests on the unbound in-memory store and the never-provisioned SQLite
database pass on both sides by construction — they pin the documented escape,
not the fix.

## Local PostgreSQL leg (executed, not skipped)

Native pgvector/pg18 on `127.0.0.1:5439` (this lane's compose service),
`alembic upgrade head` at revision 069, `MAISTRO_TEST_PG_DSN` set:

```text
uv run pytest packages/maistro-core/tests/persistence/test_workspace_scope_fence_pg.py \
  packages/maistro-core/tests/workspaces/test_workspace_tombstones.py -q
  -> 25 passed (0 skipped)
uv run pytest packages/maistro-core/tests/runs -q
  -> 2036 passed, 4 skipped
uv run pytest packages/maistro-core/tests -q (fence-touched suites: workspaces,
  projects, tasks, persistence, runs, scheduling, goals, personas, graph, events)
  -> all green; hive-conductor backend suite: 4294 passed, 31 skipped
```
