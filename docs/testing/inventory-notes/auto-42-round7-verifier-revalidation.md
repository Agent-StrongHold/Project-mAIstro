---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# auto-42 round 7: independent verifier re-validation at fa10be9086

Read-only re-derivation at the exact assigned head
`fa10be90863e151063046ded925abb9cc42ecf3a` (clean at start; code is
byte-identical to 7f8e31cfd — the only delta is the round-6 evidence note,
`git diff --stat` = 1 docs file). Every material claim below was executed
by this verifier at this head; nothing is inherited without re-execution.

## Independently executed this round

- Driver checks (job d06f7ec29): `uv sync --locked --extra dev`,
  `ruff check .` ("All checks passed!"), `ruff format --check .`
  (2603 files), suite inventories core (11415) + server (407) — all ok.
- Lane pytest selection re-run by the verifier: **159 passed**.
- `tests/tasks/test_attempt_execution.py` + `tests/runtime` +
  `tests/runs/test_chat_attempt_recovery.py`: **63 passed**.
- `uv run mypy` on all six package srcs: "Success: no issues found in
  725 source files".
- `scripts/check-execution-lifecycles.py`: exit 0, 19/19 classified
  (3 CANONICAL / 8 CONVERGE / 6 DOMAIN / 2 PROJECTION).
- **Live-PG runs suite re-run by this verifier** (pgvector container
  `auto-42-pg5`, fresh scratch DB, `alembic upgrade head` -> single head
  044; DB dropped afterwards): `MAISTRO_TEST_PG_DSN=… pytest
  packages/maistro-core/tests/runs -q -x` -> **1200 passed, 3 skipped**.
  The round-5-only "PG runs leg" prior evidence is now verifier-executed.
- **Live-PG effect race reproduced by this verifier** (verifier-authored
  script, scratch DB `verify42r7`, dropped afterwards): two independent
  `InvocationExecutionService` instances (separate process-local locks;
  NodeRun/Attempt `nr-1/at-1` vs `nr-2/at-2`) concurrently claim stable
  scope `run-race:charge:42` -> `DISPATCHES: ['a']` (exactly one physical
  dispatch), loser refused with `UnsafeEffectRetry: effect 'charge:42'
  already has an active or completed Invocation`, **exactly 1 persisted
  row** (`nr-1`, `at-1`, status `unknown`, `effect_scope
  'run-race:charge:42'`); `pg_indexes` shows the real
  `uq_capability_invocation_active_effect (run_id, effect_scope,
  binding_id, effect_key) WHERE status IN (created, running, completed,
  unknown)`. The original node_run_id-keyed double-dispatch
  (`dispatches=2`) is impossible on real PostgreSQL at this head.
- `check-vulture-baseline.py`: exit 1 at this head — and **also exit 1
  when executed at the develop base `0c8370a8e` itself** (git-archive
  run in /tmp): the NEW-identity lists are **byte-identical**
  (578 findings, `diff` empty; same 1403 -> 1434 summary). The residual
  is therefore develop-inherited candidate-ledger churn; this branch
  adds zero vulture identities. The round-1 `a2a.py:62 create_a2a_task`
  debt no longer appears (banked via the `chore(quality)` /
  `fix(quality)` commits on this branch).
- Closure keywords: PR 1326 body is "Refs #42" only (refreshed live;
  headRefOid matches fa10be9086, draft). Precise GitHub auto-close regex
  (`\b(close[sd]?|fix(e[sd])?|resolve[sd]?)\s*:?\s*#\d+`) over
  `0c8370a8e..HEAD` messages matches only "the upstream-closed
  #1169/#1170 implementation" inside the a5788b4 merge resolution note —
  both issues are already CLOSED, so no OPEN issue (#42, #1194) can be
  auto-closed by this branch.
- Live GitHub (read-only `gh`): #1169 CLOSED (2026-09-13), #1170 CLOSED
  (2026-09-10), **#1194 OPEN**.
- `tests/graph/durable_runs/test_ambiguous_effect_replay_guard.py`
  re-read: deep, not hollow — asserts `dispatches == 1`,
  `blocked_visits == 2`, three chronological NodeRuns (ordinals 1,2,3)
  each with one COMPLETED Attempt, Run FAILED truthfully, and the single
  UNKNOWN invocation retrievable through the stable scope under the
  first-visit identities.

## Acceptance state at this head

Every in-tree #42 acceptance criterion is proven by verifier-executed
evidence above. Sole issue-level residual, unchanged: **#1194 is OPEN**
while #42 requires "#1169, #1170 and #1194 close before this issue is
considered complete". Closure is an orchestrator action outside this
lane's GitHub authority; no code repair exists or is needed in this
lane. Secondary integrator-owned item: the develop-inherited vulture
ledger grant (identical failure at base, needs a reviewed grant/prune).
