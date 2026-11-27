# Verification round — #37 at ac4608de1e (CI gate-repair handoff)

Round L37 verify (job 39a5be1f): independent verification at the exact
assigned head `ac4608de1e6779d7cb401897dfec0240bb3beb25` (auto-37, develop
base `618954f052`). No tree edits beyond this record, no GitHub actions, no
closure keywords. Re-derives the three RED gates named for this PR line
(coverage (PostgreSQL) = cancelled; integration-scope/lint; postgres (pg17))
from the three repair commits since `f93bf88894`, and re-proves them locally.

## The three repairs, re-verified against evidence

- `7e22b04f4b` (postgres (pg17) leg): the RESTRICT refusal SQLSTATE is
  major-dependent. Direct probe with `VERBOSITY=verbose` against
  `pgvector:pg17` (17.12) and `pgvector:pg18` (18.6): pg17 reports **23503**
  (ForeignKeyViolationError), pg18 reports **23001**
  (RestrictViolationError) for the same `fk_canonical_projects_workspace`
  breach — sibling asyncpg classes, so `40f961d1ef`'s single-class pin could
  only pass on pg18. The repaired test accepts either and asserts the named
  constraint in the refusal; `personas/test_durable_store_pg.py` + full
  persistence/projects/workspaces pass on **both** majors (1566 passed each).
- `c02fb6e36f` (integration-scope/lint): develop's landed
  `071_sentinel_decision_integrity` took the branch's 071 slot; the
  durable-table ledger's `canonical_orphan_project_quarantine.owner_module`
  pointed at the removed filename. Re-run at this head:
  `check-durable-table-inventory.py` → **ok: 129 durable tables, exit 0**;
  `tests/test_check_durable_table_inventory.py` → **37 passed**.
- `ac4608de1e` (coverage (PostgreSQL) cancel): `quality.yml` diff is exactly
  `timeout-minutes: 20 -> 40` on `coverage-postgres` with a measured-arc
  comment; the gate itself (publish-set floor + diff coverage) and every
  producer command are unchanged — capacity, not scope, mirroring the
  coverage-gate 15->30 precedent. No suite, test, or source file touched.

## Develop-sync block resolved

`c71f575dd0` merges origin/develop; live `git ls-remote origin develop` =
`618954f052` = merge-base, branch ahead 29, tree clean. The renumber is
coherent end-to-end: `alembic upgrade head` on a fresh pg17 and a fresh pg18
database both walk `070 -> 071` (Sentinel) `-> 072` (Deleted Workspaces stay
deleted).

## Local gate evidence at this head (all exit 0 unless noted)

- Driver checks (job dir): `uv sync --locked --extra dev`, `ruff check .`,
  `ruff format --check .`, PR-path pytest **803 passed/233 skipped**,
  hive-conductor pytest **90 passed/65 skipped** (server-less shape),
  `check-suite-inventory.py` x3 (hive-conductor 4722, maistro-core 19311,
  maistro-design 725).
- `check-vulture-baseline.py packages/*/src --min-confidence 60 --exclude
  '*/third_party/*'` (CI-exact) → 1217 reviewed = 1217 findings.
- Workflow gates, CI's exact invocations: `/tmp/actionlint -no-color
  -oneline -shellcheck` (1.7.7) exit 0; `shellcheck --severity=warning
  tools/*.sh` and `install.sh get.sh` exit 0; `check-workflow-inventory.py`
  clean (33 dispositioned); `check-workflow-write-safety.py` ok.
- `check-backlog-consistency.py` → OK (167 items).

## Real-PG acceptance evidence (pgvector pg17:12 on :5434; pg18:6 on :5437)

Fresh `maistro_verify37` per major, CI env shape
(`DB_*` + `MAISTRO_TEST_PG_DSN`/`MAISTRO_TEST_DATABASE_URL` +
`MAISTRO_REQUIRE_PG_LEGS=1`), chain applied before the suites:

- pg17: personas/persistence/projects/workspaces → **1566 passed/89 skipped**;
  same set on pg18 → **1566 passed/89 skipped**.
- pg17: `tests/migrations` on a second fresh, unmigrated DB
  (`maistro_mig37`) → **174 passed** (4m29s) — AC5 installed-base purge and
  orphan-quarantine provenance against the renumbered chain.
- pg17, migrated DB: runs/graph/goals/scheduling/tasks(pg)+container-postgres/
  events/quota/backlog → **6086 passed/12 skipped/4 xfailed** (5m47s).
- pg17: hive `test_workspace_authority.py` +
  `test_workspace_authority_durable.py` + manual-fire + recovery-cadence →
  **63 passed**, including `test_a_completed_import_that_loses_its_journal_
  still_cannot_resurrect_a_deleted_workspace` and
  `test_interrupted_import_never_replays_over_canonical_changes` (AC4).

Fence surfaces re-read in the tree: `PgWorkspaceStore.delete` writes the
tombstone in the delete transaction and `create` refuses tombstoned ids
(AC2), `pg_scope_store` `SELECT … FOR UPDATE` before any Project write with
cross-pool race tests (`test_an_admission_waits_on_a_delete_holding_the_
workspace_lock`, `test_a_committed_delete_strands_no_root_from_a_racing_
admission`) (AC3), restart/pool-replacement identity tests (AC1), orphan
disposition provenance tests (AC5).

## Closure-keyword audit

PR #2525 body says "Refs #37" only. All non-merge commit subjects/bodies in
`618954f052..ac4608de` scanned — zero `fixes/closes/resolves #N` matches.

## Still external to this branch (unchanged from prior rounds)

Live CI at `ac4608de` (the timeout repair exists precisely because the last
run at `c02fb6e` was cancelled; no green run at this SHA yet — pending, not
inferred); AC6's #1419 evidence map; issue-level closure per the issue's own
closure gate (needs CI link + AC-by-AC evidence before any close).
