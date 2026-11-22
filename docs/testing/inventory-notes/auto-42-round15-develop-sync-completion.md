# auto-42 round 15: develop-sync salvage — complete the blocked merge to origin/develop 4fd7801fb

Salvage of the develop-sync the previous round left mid-merge: the worktree sat
at HEAD `909a02cd7810` with a merge of `eb36d8061` (then 2 commits behind
`origin/develop`) in progress and exactly one unmerged path. This round
resolved that conflict, committed the merge, then merged `origin/develop`
(`4fd7801fb333`) on top, so the branch carries develop's full tip — including
`55a647059` (#1336 public runtime cancellation fence test) and `4fd7801fb`
(#1752 candidate lineage/archive retention for maistro-evolve).

## What the conflict resolution did

- `tests/migrations/test_capability_invocation_effect_index_migration.py`:
  kept the lane's deletion (develop modified it; "deleted by us"). It tests
  migration `043_capability_invocation_effect_index`, the `logical_effect`-era
  index migration this lane retired as a competing mechanism — the standing
  reconciliation recorded in `auto-42-develop-sync-55be1459-reconciliation.md`.
  The branch folds the #1194/#42 effect-claim shape into migration `035`
  (`effect_scope` + `uq_capability_invocation_active_effect`) with the same
  shape in `PgInvocationStore.ensure_schema`; the equivalent live-catalog
  coverage is `tests/migrations/test_migration_chain.py`'s reapplication test
  (stamp `039_quota_usage_event_identity`, re-upgrade walks `044` + `046`,
  asserts `effect_scope` and the scope-keyed claim index). The auto-merged
  chain test already carries exactly that shape, and `alembic upgrade head` /
  `downgrade base` / `upgrade head` walks the reconciled single-headed chain
  (…042 → 044 → 046 → 048 → 049 → 050 → 051) cleanly against live PostgreSQL.
- No quality ledger rows were lost by either merge (checked with
  `git diff --numstat` against the pre-merge head and `origin/develop`; the
  radon/vulture/reachability/disposition gates all pass at the merged head).

## Inventory

No recorded suite count moved: the develop tests the merges brought in
(working-graph, rubric, design versions, evolve archive, public cancellation
fence) were already counted in `docs/testing/inventory/baseline.json` via
develop's own accounting, and `check-suite-inventory.py` reports all 14 suites
matching at the merged head.

## Executed evidence (at merged head 5049951e2)

- `uv sync --locked --all-extras` (CI quality job's exact setup), then
  `uv run ruff check .` / `uv run ruff format --check .` — clean.
- `uv run python scripts/check-radon-baseline.py` — exit 0 (145→145 blocks;
  the previously reported `invoke` C(12)→C(11) improvement was banked in
  `9814654bf`, the candidate ledger carries 11).
- `uv run python scripts/check-vulture-baseline.py packages/*/src
  --min-confidence 60 --exclude '*/third_party/*'` — exit 0 (1355→1355).
- `check-reachability.py`, `check-reachability-dispositions.py`,
  `check-durable-table-inventory.py`, `check-promotion-surface.py`,
  `check-backlog-consistency.py`, `check-suite-inventory.py` — all exit 0.
- `uv run mypy --strict packages/maistro-core/src` — exit 0, 676 files (the
  5 `import-not-found` errors seen under `--extra dev`-only syncs are the
  documented missing-`maistro_bootstrap` env trap, not type violations).
- Live PostgreSQL (throwaway `pgvector:pg18` on :55433): `alembic upgrade
  head` / `downgrade base` / `upgrade head` — clean; `tests/migrations` —
  98 passed; `packages/maistro-core/tests/persistence` +
  `maistro-design/test_creative_brief_pg.py` — 525 passed (the brief PG leg
  needs a chain-migrated database, matching its docstring's CI assumption).
- `packages/maistro-core/tests/{capabilities,graph/durable_runs,runs,runtime,
  memory/working_graph,ontology,projects,a2a}` — 2480 passed, 317 skipped;
  `graph/nodes` + `maistro-design/tests` + `maistro-evolve/tests` — 1771
  passed; `maistro-canvas/tests` — 464 passed; the #42 verifier's exact
  16-file list — 570 passed; `hive-conductor` evolution tests touched by the
  sync — 35 passed.
