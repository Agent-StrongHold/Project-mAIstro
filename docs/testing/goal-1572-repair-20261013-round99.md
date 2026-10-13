# #1572 round-99 repair verification — develop sync at ac69535ef (PR #1938 landed)

Dispatch head 47f0529375f15d6b3a04c0f88601cbbed65ea10c, develop base moved
3c761d14db94 → ac69535ef165ded3ca82cd3428728569de3251fa. That one develop
commit is the squash of PR #1938 — the branch's own content through
332c24c54a7c (the canonical Goal store: model, three stores, authorization,
migration 063, conformance suites, wiring). Every claim below was executed
first-hand this round; nothing is carried from earlier rounds on trust.

## The develop sync (merge 5bd6878a7209562c4bca1e3c57375991818f5457)

- `git merge-base --is-ancestor 332c24c54 origin/develop` — NOT an ancestor
  (squash, no shared commits), but `git diff origin/develop 332c24c54 --stat`
  is EMPTY: develop's tree is byte-identical to this branch's parent commit.
- All six merge conflicts are add/add between develop's copy (sha256 ==
  332c24c54's copy, verified per file) and this branch's newer copy carrying
  47f052937 (the owner-as-read CAS guard). Every conflict resolved as ours;
  `git diff HEAD` after resolution is empty, i.e. the merged tree equals the
  pre-merge branch tree exactly. The merge exists to move the merge-base to
  ac69535ef so quality gates read the goals vocabulary as trusted-base
  content (`_discover_at_revision(base)` now finds maistro/goals/model.py).

## CI "test: failure" — root cause and resolution, executed

- `uv run python scripts/check-execution-lifecycles.py` (exact CI argv,
  quality.yml:1541) — EXIT 0 at the merge head: "19 classified lifecycles ->
  19 discovered lifecycles, OK" (baseline read at base ac69535ef). The
  GoalStatus grant block from rounds 59–97 is resolved by the feature itself
  landing on develop; no ledger edit was made or needed.
- The shipped-ledger test that duplicated the gate (the 1:1 correlate of the
  merge-queue failure), `tests/test_check_execution_lifecycles.py`: 29 passed.
- Vulture at the lane-brief CI-repair argv (`check-vulture-baseline.py
  packages/*/src --min-confidence 60 --exclude '*/third_party/*'`): EXIT 0,
  1323 = 1323, never_allowlist 0 — no amendment target, ledger untouched.
- `check-m1-convergence-freeze.py --base ac69535ef165ded3ca82cd3428728569de3251fa`
  (formal-conformance.yml argv): EXIT 0.
- `git diff --check 3c761d14..HEAD` and `git diff --check origin/develop..HEAD`:
  EXIT 0 (the round-59/round-98 whitespace finding stays fixed).
- ruff check "All checks passed!", ruff format 3288 files clean, mypy 899
  source files clean, suite inventory ok at 16344 = recorded.

## Prior finding 1 — concurrent reassign_agent CAS (independently re-proven)

- Red first-hand this round: scratch worktree at the pre-fix tree 332c24c54
  with the HEAD conformance file — `test_concurrent_reassignments_record_truthful_ownership[postgres]`
  plus the four deterministic read-before-write refusal legs (sqlite+postgres)
  FAIL (5 failed), including `DID NOT RAISE GoalRevisionConflict` on the exact
  reported interleaving. Scratch worktree removed after.
- Green at the merge head: `-k "reassign or concurrent"` on the goals suite
  with PG legs required — 13 passed, 2 skipped (the 2 skips are the in-memory
  reference, which holds the read/write lock so the constructed window cannot
  open there — asserted in the test's own skip reason).
- Whole goals directory on a fresh, migrated pgvector:pg18 database:
  78 passed, 2 skipped with `MAISTRO_REQUIRE_PG_LEGS=1` +
  `MAISTRO_TEST_PG_DSN` + `MAISTRO_TEST_DATABASE_URL`; repeated on
  pgvector:pg17 (second supported major): 78 passed, 2 skipped.

## Acceptance battery executed at the merge head

- Migration chain on both majors from empty: single head, ends
  "062 -> 063, The canonical Goal store"; `canonical_goals`,
  `canonical_goal_revisions`, `canonical_goal_transitions` present; downgrade
  063 -> 062 drops the three tables 3 → 0, re-upgrade restores 0 → 3.
- CI postgres-job mirror with PG legs: tests/persistence +
  test_container_postgres.py + tests/workspaces — 1169 passed, 0 failed.
- Full `packages/maistro-core/tests` with PG legs required: 16213 passed,
  139 skipped, 3 xfailed, **6 failed** — see the out-of-lane finding below.
- Driver's nine-file set (events container PG, pack contracts, goal model,
  pg schema agreement, restart readback, conformance, wiring, run binding,
  sqlite/alembic parity): 197 passed, 2 skipped.

## Acceptance criteria → evidence (issue body re-read from dispatch-context.json)

1. Round-trip on all three backends via one conformance suite → goals suite
   green on memory/sqlite/postgres params, PG legs required, both majors.
2. Append-only revisions, stale refusal, one concurrent winner → conformance
   CAS/race legs green (see above).
3. Subgoal lineage + recorded agent transition → conformance lineage legs
   green (`from_agent_id`/`to_agent_id`/`actor` asserted).
4. Run binding immutable after admission → `test_run_goal_binding.py` green
   against the migrated database (PG legs on).
5. Two principals / foreign Goal == missing → conformance isolation legs
   green; `GoalNotVisible` for foreign and missing.
6. Production composition wires the store, shipped Container exposes it →
   `test_goal_wiring.py` green incl. the live-server bare-database bring-up
   and the end-to-end seam test; `create_container` is the one composition
   maistro-server (`main.py:29`) and Hive (`backend/adapters/maistro_core.py:195`)
   both call; `container.py:44/2412-2414` wire `goal_store` + `goal_reader`.
7. No GoalRun/OrchestratorRun/second executor/private lifecycle →
   `grep -rn "GoalRun\|OrchestratorRun" packages/*/src` rc=1 (absent);
   convergence freeze EXIT 0.

Residual for deep review: booting maistro-server / Hive as live service
processes was not executed (needs the full stack); the shipped Container
composition itself was executed by the wiring suite.

## Out-of-lane finding (recorded for the approval-store lane, NOT fixed here)

`packages/maistro-core/tests/conformance/test_approval_store_conformance.py`
postgres legs (6) fail on any alembic-only database: alembic 043 adds
`uq_capability_approval_effect UNIQUE (run_id, node_run_id, binding_id,
effect_key)` while `PgApprovalStore` ON CONFLICT targets `(run_id,
effect_scope, binding_id, effect_key)` (the columns `durable_schema.py`
creates). `ensure_capability_schema` is a no-op on the alembic-built table
(same constraint name, different columns) → `InvalidColumnReferenceError`.
Proven pre-existing: byte-identical failure on a fresh database at
origin/develop (ac69535ef). No CI job runs tests/conformance with PG legs,
and the branch delta vs develop (goals files + docs only) does not touch any
of these paths. Not repaired in this lane to keep the #1572 diff scoped.

No code, test, or ledger changes this round; docs only; no inventory delta.
