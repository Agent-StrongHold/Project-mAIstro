---
inventory-delta:
  packages/maistro-core/tests: +0
  packages/maistro-server/tests: +0
---

# auto-42 round 6: independent verifier re-validation at 7f8e31cfd

Read-only re-derivation of every round-5 claim at the exact head
`7f8e31cfd3862176abf4f07c505a40b0be030cfa` (tree clean; nothing edited).
No code changed this round — this evidence record is the only delta.

## Independently executed this round

- Driver checks (job 5071f154): `uv sync --locked --extra dev`,
  `ruff check .` ("All checks passed!"), `ruff format --check .`
  (2603 files), suite inventories core (11415) + server (407) — all ok.
- Lane pytest selection re-run by the verifier: **159 passed**.
- `tests/tasks/test_attempt_execution.py`, `tests/runtime`,
  `tests/runs/test_chat_attempt_recovery.py`: **63 passed**.
- `uv run mypy` on all six package srcs: "Success: no issues found in
  725 source files".
- `scripts/check-execution-lifecycles.py`: 19/19 classified, exit 0
  (3 CANONICAL / 8 CONVERGE / 6 DOMAIN / 2 PROJECTION).
- `scripts/check-vulture-baseline.py`: **exit 1** (unchanged), but an
  awk-scoped pass over the NEW-identity blocks shows **zero** new
  identities on this branch's own surfaces (capabilities/ invocation
  stores, graph/durable_runs, graph/nodes, alembic 034/035,
  maistro_server/api/a2a) — the residual is the develop-inherited
  candidate-ledger churn the round-5 note proved multiset-identical to
  base `0c8370a8e`.
- Live GitHub (read-only `gh`): #42 OPEN, #1169 CLOSED (2026-09-13),
  #1170 CLOSED (2026-09-10), **#1194 OPEN**.
- PR 1326 refresh: draft, headRefOid `7f8e31cfd…`, body "Refs #42" only;
  `git log 0c8370a8e..HEAD` messages contain **no**
  fixes/closes/resolves keywords.
- In-tree fix surfaces confirmed by reading the code: scope-keyed
  partial unique index `uq_capability_invocation_active_effect` on
  `(run_id, effect_scope, binding_id, effect_key)` in
  `capabilities/invocation_store.py` `_CLAIM_DDL`,
  `capabilities/pg_invocation_store.py`, and
  `alembic/versions/035_capability_invocations.py` (with legacy
  backfill); stable-scope wiring in
  `graph/nodes/agent_spawn_harness.py` (`effect_scope=effect_key`,
  scoped by Run/node/input identity, not the physical visit) threaded
  through `capabilities/governed_invocation.py`.
- **Live-PG race reproduced by this verifier** (pgvector container
  `auto-42-pg5`, scratch DB `verify42r6`, `alembic upgrade head` ->
  single head 044; DB dropped afterwards): two concurrent
  `InvocationExecutionService` claims of stable scope
  `run-race:charge:42` from different NodeRun/Attempt identities ->
  `dispatches: ['a']` (exactly one physical dispatch), second claim
  refused with `UnsafeEffectRetry`, **exactly 1 persisted row**
  (`nr-1`, status `unknown`); `pg_indexes` shows the real scope-keyed
  unique index. The prior node_run_id-keyed double-dispatch
  (`dispatches=2`) is impossible on real PostgreSQL.
- `tests/graph/durable_runs/test_ambiguous_effect_replay_guard.py`
  inspected: deep, not hollow — asserts `dispatches == 1`,
  `blocked_visits == 2`, three chronological NodeRuns (ordinals 1,2,3)
  each with one COMPLETED Attempt, UNKNOWN invocation retrievable
  through the stable scope, Run FAILED truthfully.

## Acceptance state at this head

All in-tree #42 acceptance criteria remain test-proven, now with the
live-PG race and mypy independently re-executed by the verifier. Sole
residual, unchanged from round 5: **#1194 is OPEN** while #42 requires
"#1169, #1170 and #1194 close before this issue is considered
complete". #1169 and #1170 are closed; #1194 closure is an
orchestrator/integrator action outside this lane's GitHub authority.
No code repair is available or needed in this lane.
