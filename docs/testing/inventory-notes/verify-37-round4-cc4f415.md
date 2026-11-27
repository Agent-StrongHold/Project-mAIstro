---
inventory-delta:
  packages/maistro-core/tests: +3
---

# Verification round 4 (repair) — #37 at cc4f4153aa (two develop-sync merges + coverage-gate diff repair)

Round L37 repair (job 61b3f7ea376942a485582304ceca7fba). Develop sync resolved
twice — `origin/develop` 7615ebd709 (merge f5ce0ef2bf, clean) and the
mid-round advance c2beba3f81 (merge cc4f4153aa) — and the one failing hosted
gate — **Coverage gate (publish-set floor + diff coverage)** at ea73052, run
45971098862 job 140418819817 — repaired. The other producers
(coverage (PostgreSQL) 15m34s, coverage (no services), coverage (MinIO)) and
every `Quality / *` job were green in that run; `combine` and the 87% floor
passed there too, so the only defect was the per-file diff gate:

```
FAIL: 2 file(s) below the diff-coverage floor
  packages/maistro-core/src/maistro/projects/sqlite_scope_store.py:
      75.0% of 4 changed branch arcs (need 80%); partial at 386
  packages/maistro-core/src/maistro/tasks/admission.py:
      80.0% of 15 changed lines (need 90%); uncovered 598, 599, 605
```

## What was uncovered, and the repair

1. `admission.py` 598-599 — the stale-cache eviction in
   `WorkspaceRoutingAdmitter.admitter_for` had no test: no test resolved a
   cached admitter whose Root changed underneath it. Covered by
   `test_a_cached_admitter_is_rebuilt_when_the_root_under_the_id_changes`
   (tests/tasks/test_workspace_routing.py), which swaps the router's project
   store for a fresh tree — the docstring's "scope store that lost its tree"
   scenario — and asserts the stale admitter is dropped and the rebuilt one
   binds the new Root.
2. `admission.py` 605 — the rebuild lock's already-rebuilt early return was
   unreachable by any test. Writing its test **exposed a real race**: the
   eviction popped unconditionally, so racing re-resolutions evicted each
   other's fresh rebuilds (observed 8 distinct admitters; negative control —
   the new test fails 8 != 1 against the pre-fix code). Fixed in production
   code with a compare-and-evict (`pop` only while the cache still holds the
   stale entry this call decided against); `test_concurrent_rebuilds_share_one_admitter`
   pins one admitter for the racing rebuild, mirroring the existing cold-cache
   race pin. This is #37's own concurrent-deletion/admission fence territory:
   the eviction path the branch added is now held to the same single-admitter
   contract the cold path already pins.
3. `sqlite_scope_store.py:386` — `_workspace_row` treated exactly one
   `OperationalError` ("no such table: canonical_workspaces") as the
   bootstrap escape; the other outcome (a different OperationalError
   re-raised, 386->388) had no test. Covered by
   `test_an_operational_error_that_is_not_the_missing_table_propagates`
   (tests/projects/test_create_root_workspace_fence.py): a locked-database
   fault must propagate rather than be misread as "never provisioned", which
   would mint a Root under an id nothing verified.

## Gates re-run locally at the repaired tree

- Full unit producer leg:
  `coverage run --branch --source=packages/maistro-core/src/maistro -m pytest
  packages/maistro-core/tests --timeout=30 -q` — 17984 passed, 1323 skipped,
  7 xfailed (19314 collected = recorded 19311 + this note's +3).
- Full coverage-postgres producer legs against pgvector/pgvector:pg17
  (CI's service image/credentials, port 5499): `tests/migrations` on an
  unmigrated database (174 passed), `alembic upgrade head`, the
  persistence/events/capabilities/runs/graph/projects/workspaces/personas/
  goals/scheduling/tasks/security/memory/quota list (7741 passed, 99 skipped),
  `tests/backlog` (115 passed), hive-conductor evolve + brief-commit PG legs
  (58 + 49 passed), and the gate's own hive-conductor producer
  (`packages/hive-conductor/backend/tests`, 4601 passed, 121 skipped).
- `uv run coverage xml -o coverage.xml` then CI's exact gate invocation
  `uv run python scripts/check-diff-coverage.py coverage.xml --base
  origin/develop` — `ok: every measured file this change touches is at or
  above 90% lines / 80% branch arcs`, exit 0. The two files above no longer
  appear in any FAIL list.
- `uv run ruff check .` and `uv run ruff format --check .` clean;
  `uv run mypy packages/maistro-core/src` — no findings in changed files
  (one pre-existing `maistro_bootstrap.cli` import-not-found in
  `cli/_install.py`, an artifact of syncing without `--all-extras`).

No production behavior outside `admission.py`'s eviction guard changed; no
gate definitions, ledgers, or thresholds were edited.

## Second develop sync (c2beba3f81) and the 072 -> 073 renumber

`origin/develop` advanced mid-round to c2beba3f81 (#2532), landing its own
`072_workspace_working_log` — a revision-id collision with this branch's
tombstone/Project-FK revision. Left un-merged, the next merge-queue
evaluation would combine both into a two-head migration chain. Resolution
follows the branch's own landed convention (a landed trunk migration never
moves; the newcomer renumbers):

- `072_workspace_tombstones_and_project_fk.py` ->
  `073_workspace_tombstones_and_project_fk.py`, `revision = "073"`,
  `down_revision = "072"` (the working log); docstring records both
  renumbers (069-written -> 072 -> 073).
- Head-chain assertions updated with both landed identities:
  `test_capability_invocation_effect_index_migration.py` (heads == ["073"],
  working-log 072 + tombstone 073 named),
  `test_goal_installed_base_upgrade.py` (CHAIN_HEAD = "073"),
  `test_legacy_principal_ownership_live.py` (versions == {"073"}),
  `test_migration_chain.py` (tombstone comment).
- `tests/migrations/test_workspace_tombstones_installed_base.py` docstring
  and the installed-base comment name the shipped revision.
- `quality/durable-table-retention.json`: the two #37 rows' `owner_module`
  now points at the 073 filename; the merged ledger keeps the branch's
  tombstone/quarantine rows **and** develop's working-log rows
  (129 tables, `check-durable-table-inventory.py` ok) — no rows lost in
  either merge (`git diff --numstat origin/develop -- quality/` reviewed).
- Live docs updated for the drift: ADR-092326-97c4 (+ the two #37 notes
  updated by the round-3 precedent); historical `verify-37-*` round records
  left as history.
- `tests/fixtures/ci_quality_obligations.json`: `coverage-postgres` digest
  recomputed from the merged workflow (both sides edited that job: this
  branch's 20->40 timeout and develop's working-log producer legs); the
  other three digests unchanged and verified byte-identical.

Post-merge proof (all at cc4f4153aa): `alembic upgrade head` on a fresh
pg17 database walks 070 -> 071 -> 072 -> 073 single-head;
`tests/migrations` 174 passed; `tests/test_ci_quality_split.py` 96 passed;
container/wiring/tombstone/fence/routing suites 243 passed; the live AC2
probe re-run on the merged tree (deleted id refused on re-create with the
tombstone row present, unknown id refused before any write, zero rows);
full re-run of the coverage pipeline (unit core leg 17986 passed/1342
skipped, PG producer list 7747 passed/99 skipped, backlog 115 passed, hive
PG legs 58+49, gate's hive producer 4720 passed/2 skipped) ending in
`check-diff-coverage.py coverage.xml --base origin/develop` exit 0;
`check-suite-inventory.py` ok for `packages/maistro-core/tests` on the
merged tree (develop's note deltas + this note's +3 balance); ruff
check/format clean; backlog consistency OK.
