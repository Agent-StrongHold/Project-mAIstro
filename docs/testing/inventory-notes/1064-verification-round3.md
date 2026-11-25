# 1064-verification-round3

Round-3 independent re-verification of the #1064 replay-safety repair at head
`aa7aeb24de9b957bbfa226d4a037d2a4438e0429` (base
`a6a0969ca19852f1c27cf18299e448633ad52a7c`). This round adds no tests; it
re-executes prior rounds' evidence with fresh commands and closes the two
items the previous round left open (hosted settlement of the exact head, and
the #947 P1 disposition re-check).

## What this round established (all commands run fresh)

Local battery (pg18 container `maistro-1064-pg` on 5570,
`MAISTRO_TEST_PG_DSN=postgresql://maistro:maistro@localhost:5570/maistro_test`,
`alembic_version` at `069`, `evolve_domain_publications` present):

- pytest over the 7 changed-suite files (restart-replay, restart-replay-pg,
  startup-wiring, domain-retention, domain-store, domain-reconstruction,
  durable-snapshot): **82 passed, 0 skipped** in 39.1s.
- `pytest tests/migrations`: **173 passed** in 224s (broader than the
  28-file subset previous rounds ran; same verdict).
- `pytest tests/cross_product_parity`: **26 passed**.
- `pytest tests/test_ci_quality_split.py`: **96 passed**.
- `pytest tests/test_check_diff_coverage.py tests/test_check_suite_inventory.py`:
  **106 passed** — the coverage-gate self-tests, including the
  `MEASURED_ROOTS`/workflow `--source` agreement the cancelled hosted gate
  would have evaluated.
- `uv run ruff check .` clean; `uv run ruff format --check .` clean.
- `uv run python scripts/check-suite-inventory.py`: ok, 21 suites match.

Production-wiring anchors re-read at the head: `services/evolution.py:286`
calls `start_evolution_recovery()`; `services/evolution_recovery.py:61` starts
the idempotent tick; `services/evolution_graph.py:1479` `_recovery_resolver`
raises `EvolveRecoveryBlocked` fail-closed (:338, :568, :1546, :1554, :1597,
:1603). Exactly-once fences re-read in the PostgreSQL store
(`services/evolve_domain_store.py`): `record_battle_publication` at :378 and
`record_evaluation_publication` at :465, each a single-statement
`INSERT ... ON CONFLICT (workspace_id, effect_kind, node_run_id, benchmark)
DO NOTHING RETURNING seq`.

## Hosted CI status of the exact head (read-only API checks)

Previous round stopped while `Coverage gate (publish-set floor + diff
coverage)` and `test` were in_progress on the head's `quality` run. This
round:

- Commit check-runs on `aa7aeb24de` (81 total): **78 success / 2 skipped /
  1 cancelled**. The `test` job settled **success** between polls. The only
  cancelled check is the Coverage gate, completed
  `2026-11-24T08:36:53Z` (quality run 45351058958, attempt 1, event
  `pull_request`, created `07:50:07Z`, no re-attempt, no newer run — PR #2497
  head is unmoved at `aa7aeb24de`, `updated_at 07:50:03Z`).
- The `gates-ran` commit status (state failure, "Required execution evidence
  is missing or non-executed", "Gates Ran" workflow run 45357672870, created
  `08:36:58Z`, event `workflow_run`, head SHA = the base branch) fired five
  seconds after the cancellation — it is the downstream consequence of the
  cancelled gate, not an independent failure.

Why the cancelled gate cannot be a code failure:

- `git show --stat aa7aeb24de`: docs-only delta (+52 lines, one markdown
  file, `1064-verification-followup.md`) on top of parent
  `c467355f1c9ce484619441f726d0b8399040eaaa`.
- Parent settlement re-verified this round with a fresh check-runs API call:
  **79 success / 2 skipped / 0 failures**, including the same Coverage gate —
  identical Python content, identical workflow definition.
- The gate measures Python coverage (producers, `--fail-under=87` floor,
  `scripts/check-diff-coverage.py`); no producer measures the one markdown
  file the head adds. Its local self-tests pass (see battery above).

## #947 review disposition (live re-check)

GraphQL `reviewThreads` on PR #947 this round: the **only** open thread is
the P2 advisory "Record the durable executor on a ..." — all four P1 threads
remain resolved. The P1-disposition criterion holds at current state.

## Residual integration action (outside worker authority)

The cancelled Coverage gate on `aa7aeb24de` needs one hosted re-run before
merge (a GitHub mutation this lane is prohibited from performing). Expected
outcome: success, per the parent's identical-content green settlement plus
the passing local gate self-tests. A fresh local commit to "trigger" it would
restart CI from scratch and is not warranted: this round changed nothing in
the tree except this note.
